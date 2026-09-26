from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from .models import Completion, Description, Heartbeat
from .profiles import profile


class Modules:
    def __init__(self, state_dir, board, system, extra=None, module_file=None):
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.board, self.system, self.extra = board, system, extra
        self.override = module_file
        self.current = None
        self.error = None
        self.reload(force=True)
        if not self.current: raise ValueError(self.error)

    def reload(self, force=False):
        try:
            board = profile("boards", self.board, self.extra)
            system = profile("systems", self.system, self.extra)
            if not board or not system: raise ValueError("Unknown board or system profile")
            source = Path(self.override) if self.override else Path(__file__).with_name("modules") / (system["module"] + ".py")
            # Built-in module IDs cannot turn profile manifests into arbitrary paths.
            if not self.override and (not system["module"].replace("_", "").isalnum()):
                raise ValueError("Use --module-file for trusted external modules")
            code = source.read_bytes()
            runner_code = Path(__file__).with_name("workload_runner.py").read_bytes()
            generation = hashlib.sha256(code + runner_code + json.dumps([board, system], sort_keys=True).encode()).hexdigest()
            if not force and generation == getattr(self, "attempted", None): return
            self.attempted = generation
            snapshot = self.root / (generation + ".py")
            if not snapshot.exists():
                with snapshot.open("xb") as stream: stream.write(code)
                snapshot.chmod(0o400)
            elif snapshot.read_bytes() != code:
                raise ValueError("Snapshot integrity mismatch")
            runner_snapshot = snapshot.with_suffix(".runner.py")
            if not runner_snapshot.exists():
                with runner_snapshot.open("xb") as stream: stream.write(runner_code)
                runner_snapshot.chmod(0o400)
            elif runner_snapshot.read_bytes() != runner_code:
                raise ValueError("Runner snapshot integrity mismatch")
            response = subprocess.run([sys.executable, str(snapshot)], input='{"op":"describe"}',
                                      text=True, capture_output=True, timeout=20, check=True)
            data = json.loads(response.stdout)
            data["module_sha256"] = generation
            data["reserved_cpus"] = sorted(set(data.get("reserved_cpus", [])) | set(board.get("reserved_cpus", [0])))
            desc = Description.model_validate(data)
            self.current = (snapshot, desc)
            self.error = None
        except Exception as exc:
            # Avoid publishing stderr, paths, domain names or local environment to the server.
            self.error = "Module validation failed: " + type(exc).__name__


class Execution:
    def __init__(self, snapshot, job, artifact_path=None):
        self.job = job
        self.output = tempfile.TemporaryFile()
        self.process = subprocess.Popen([sys.executable, str(snapshot)], stdin=subprocess.PIPE,
                                        stdout=self.output, stderr=subprocess.DEVNULL, start_new_session=True)
        context = {"op": "run", "plan": job["plan"], "run_id": job.get("id", "standalone")}
        if artifact_path:
            context.update(artifact_path=str(Path(artifact_path).resolve()), runner_path=str(snapshot.with_suffix(".runner.py").resolve()))
        self.process.stdin.write(json.dumps(context).encode())
        self.process.stdin.close()
        self.started = time.monotonic()
        self.stopping = None
        self.cancelled = False
        self.forced = False

    def stop(self, cancelled=False):
        self.cancelled |= cancelled
        if self.stopping is None:
            self.stopping = time.monotonic()
            try: os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError: pass

    def poll(self):
        workload = self.job["plan"]["template"] == "workload"
        if time.monotonic() - self.started > self.job["plan"]["duration_seconds"] + (120 if workload else 20):
            self.stop()
        if self.stopping and time.monotonic() - self.stopping > (45 if workload else 10):
            self.forced = True
            try: os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        code = self.process.poll()
        if code is None: return None
        # Kill any remaining worker descendants even when their parent has exited.
        try: os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        self.output.seek(0)
        raw = self.output.read(2 * 1024 * 1024 + 1)
        self.output.close()
        try:
            if len(raw) > 2 * 1024 * 1024: raise ValueError("Oversized result")
            result = json.loads(raw)
            if not isinstance(result, dict): raise ValueError("Result must be an object")
            cleanup = bool(result.get("cleanup_ok", False)) and not self.forced
        except (ValueError, UnicodeDecodeError):
            result, cleanup = {"error": "Module returned no valid result", "exit_code": code}, False
        if not workload and self.cancelled and self.job.get("cleanup_scope") == "process-group" and not self.forced:
            # These modules change only processes, all of which share the killed process group.
            cleanup = True
        result["mode"] = self.job.get("mode", "unknown")
        result["synthetic"] = self.job.get("mode") == "synthetic"
        state = "cancelled" if self.cancelled else "succeeded" if code == 0 and cleanup and not result.get("error") else "failed"
        return Completion(state=state, result=result, module_sha256=self.job["module_sha256"], cleanup_ok=cleanup)


class Agent:
    def __init__(self, client, board_id, modules):
        self.client, self.board_id, self.modules = client, board_id, modules
        self.execution = None
        self.pending = None
        self.staging = None
        self.downloads = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact")
        self.reload_ack = 0
        self.reload_requested = 0

    def tick(self):
        if not self.execution and not self.pending and not self.staging:
            self.modules.reload(force=self.reload_requested > self.reload_ack)
            self.reload_ack = self.reload_requested
        snapshot, desc = self.modules.current
        status = self.client.heartbeat(self.board_id, Heartbeat(description=desc, reload_ack=self.reload_ack,
                                                               reload_error=self.modules.error))
        self.reload_requested = status["reload_requested"]
        if self.pending:
            self.client.finish(self.board_id, self.pending[0], self.pending[1])
            self.pending = None
            return
        job = self.client.poll(self.board_id)
        if self.execution:
            if not job or job["id"] != self.execution.job["id"] or job["state"] == "cancelling": self.execution.stop(cancelled=True)
            completed = self.execution.poll()
            if completed:
                self.pending = (self.execution.job["id"], completed)
                self.execution = None
        elif self.staging:
            staged_snapshot, staged_job, future = self.staging
            if future.done():
                self.staging = None
                try:
                    artifact_path = future.result()
                    if not job or job["id"] != staged_job["id"] or job["state"] == "cancelling":
                        self.pending = (staged_job["id"], Completion(state="cancelled", result={"cleanup_ok": True, "code_executed": False}, module_sha256=staged_job["module_sha256"], cleanup_ok=True))
                    else:
                        self.execution = Execution(staged_snapshot, staged_job, artifact_path)
                except Exception as exc:
                    self.pending = (staged_job["id"], Completion(state="failed", result={"error": "Artifact staging failed: " + type(exc).__name__, "code_executed": False}, module_sha256=staged_job["module_sha256"], cleanup_ok=True))
        elif job:
            if not job["claimed"] or job["module_sha256"] != desc.module_sha256:
                self.pending = (job["id"], Completion(state="failed", result={"error": "Unknown or changed execution; inspect before recovery"},
                                                     module_sha256=job["module_sha256"], cleanup_ok=False))
            else:
                job["mode"] = desc.mode
                job["cleanup_scope"] = desc.cleanup_scope
                if job["plan"].get("artifact_sha256"):
                    future = self.downloads.submit(self.client.fetch_artifact, self.board_id, job["plan"]["artifact_sha256"], self.modules.root / "artifacts")
                    self.staging = (snapshot, job, future)
                else:
                    self.execution = Execution(snapshot, job)

    def shutdown(self):
        if self.staging:
            _, job, future = self.staging
            future.cancel()
            self.pending = (job["id"], Completion(state="cancelled", result={"code_executed": False}, module_sha256=job["module_sha256"], cleanup_ok=True))
            self.staging = None
        self.downloads.shutdown(wait=False, cancel_futures=True)
        if self.execution:
            self.execution.stop(cancelled=True)
            while (result := self.execution.poll()) is None: time.sleep(.1)
            self.pending = (self.execution.job["id"], result)
            self.execution = None
        if self.pending:
            try: self.client.finish(self.board_id, *self.pending)
            except Exception: pass


class LocalClient:
    def __init__(self, store): self.store = store
    def heartbeat(self, board, data): return self.store.heartbeat(board, data)
    def poll(self, board): return self.store.poll(board)
    def finish(self, board, run, data): return self.store.finish(board, run, data)

    def fetch_artifact(self, board, sha, root):
        return self.store.artifact_for_agent(board, sha)
