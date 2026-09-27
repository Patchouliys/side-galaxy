from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import threading

from .models import Completion, Description, Heartbeat
from .agent_state import AgentJournal
from .host import HostMonitor
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
            helpers = {}
            if system['module'] == 'qemu_environment':
                helpers = {'.kvm.py': Path(__file__).with_name('modules').joinpath('kvm.py').read_bytes(),
                           '.environments.py': Path(__file__).with_name('environments.py').read_bytes()}
            generation = hashlib.sha256(code + runner_code + b''.join(helpers.values()) + json.dumps([board, system], sort_keys=True).encode()).hexdigest()
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
            for suffix, content in helpers.items():
                helper = snapshot.with_suffix(suffix)
                if not helper.exists():
                    with helper.open('xb') as stream: stream.write(content)
                    helper.chmod(0o400)
                elif helper.read_bytes() != content: raise ValueError('Helper snapshot integrity mismatch')
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
    def __init__(self, snapshot, job, artifact_path=None, environment_path=None, journal=None, spawn_guard=None, finish_guard=None):
        self.job = job
        self.completion = None
        self.resource_scope = None
        self.finish_guard = finish_guard
        if journal is not None: journal.launching()
        self.output = tempfile.TemporaryFile()
        self.event_fd, writer = os.pipe()
        os.set_blocking(self.event_fd, False)
        os.set_blocking(writer, False)
        self.event_buffer = b''
        self.log_events, self.log_sequence, self.log_bytes = [], 0, 0
        self.logs_truncated = False
        self.logs_suppressed = False
        try:
            self.process = subprocess.Popen([sys.executable, str(snapshot)], stdin=subprocess.PIPE,
                                            stdout=self.output, stderr=subprocess.DEVNULL, start_new_session=True,
                                            pass_fds=(writer,), env={**os.environ, 'SG_EVENT_FD': str(writer)})
        except BaseException:
            os.close(self.event_fd)
            self.output.close()
            raise
        finally: os.close(writer)
        context = {"op": "run", "plan": job["plan"], "run_id": job.get("id", "standalone")}
        if artifact_path:
            context.update(artifact_path=str(Path(artifact_path).resolve()), runner_path=str(snapshot.with_suffix(".runner.py").resolve()))
        if environment_path: context["environment_path"] = str(Path(environment_path).resolve())
        try:
            self.resource_scope = spawn_guard(self.process.pid, job) if spawn_guard is not None else None
            if self.resource_scope is not None and not isinstance(self.resource_scope, dict):
                raise ValueError("Invalid resource placement receipt")
            contained = self.resource_scope is not None and self.resource_scope.get('enforcement') == 'cgroup-v2'
            if contained and job.get('process_tree_execution') is not True:
                raise ValueError("Execution module does not declare process-tree containment")
            if job['plan'].get('resource_policy') == 'cgroup' and not contained:
                raise ValueError("Explicit resource policy has no cgroup placement receipt")
            if journal is not None: journal.started(self.process.pid, self.resource_scope)
            # A restarted agent must have durable identity before this gate permits experiment code.
            self.process.stdin.write(json.dumps(context).encode())
            self.process.stdin.close()
        except BaseException:
            try:
                self.process.kill()
                self.process.wait(timeout=3)
            finally:
                # Cleanup failure must not skip descriptor closure or replace the
                # original launch failure. The agent retains uncertain admission.
                if self.resource_scope and self.finish_guard:
                    with suppress(Exception): self.finish_guard(self.resource_scope)
                with suppress(OSError): self.process.stdin.close()
                os.close(self.event_fd)
                self.event_fd = None
                self.output.close()
            raise
        self.started = time.monotonic()
        self.stopping = None
        self.cancelled = False
        self.forced = False

    def drain_logs(self):
        if self.event_fd is None: return
        for _ in range(16):
            try: chunk = os.read(self.event_fd, 65536)
            except BlockingIOError: break
            if not chunk: break
            self.event_buffer += chunk
            while b'\n' in self.event_buffer:
                line, self.event_buffer = self.event_buffer.split(b'\n', 1)
                try:
                    event = json.loads(line)
                    text = event['text']
                    if event['stream'] not in ('stdout', 'stderr', 'console') or not isinstance(text, str): continue
                    self.logs_truncated |= bool(event.get('truncated'))
                    for start in range(0, len(text), 2048):
                        part = text[start:start+2048]
                        size = len(part.encode())
                        if self.log_bytes + size > 512 * 1024 or self.log_sequence >= 4096:
                            self.logs_truncated = True
                            break
                        self.log_sequence += 1
                        self.log_bytes += size
                        self.log_events.append({'sequence': self.log_sequence, 'stream': event['stream'], 'text': part})
                except (ValueError, KeyError, TypeError): self.logs_truncated = True
            if len(self.event_buffer) > 65536:
                self.event_buffer = b''
                self.logs_truncated = True

    def stop(self, cancelled=False):
        self.cancelled |= cancelled
        if self.stopping is None:
            self.stopping = time.monotonic()
            try: os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError: pass

    def poll(self):
        if self.completion is not None: return self.completion
        self.drain_logs()
        workload = self.job["plan"]["template"] == "workload"
        if time.monotonic() - self.started > self.job["plan"]["duration_seconds"] + (240 if self.job["plan"].get("environment_sha256") else 120 if workload else 20):
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
        group_gone = False
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try: os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                group_gone = True
                break
            except PermissionError: break
            time.sleep(.02)
        self.drain_logs()
        os.close(self.event_fd)
        self.event_fd = None
        self.output.seek(0)
        raw = self.output.read(2 * 1024 * 1024 + 1)
        self.output.close()
        try:
            if len(raw) > 2 * 1024 * 1024: raise ValueError("Oversized result")
            result = json.loads(raw)
            if not isinstance(result, dict): raise ValueError("Result must be an object")
            cleanup = bool(result.get("cleanup_ok", False)) and not self.forced and group_gone
        except (ValueError, UnicodeDecodeError):
            result, cleanup = {"error": "Module returned no valid result", "exit_code": code}, False
        if not workload and self.cancelled and self.job.get("cleanup_scope") == "process-group" and not self.forced and group_gone:
            # These modules change only processes, all of which share the killed process group.
            cleanup = True
        if self.resource_scope:
            result["resource_scope"] = self.resource_scope
            if self.resource_scope.get('enforcement') == 'cgroup-v2':
                try:
                    evidence = self.finish_guard(self.resource_scope) if self.finish_guard else None
                except Exception as exc:
                    evidence = {'empty': False, 'removed': False, 'error': 'Resource cleanup failed: ' + type(exc).__name__}
                if not isinstance(evidence, dict):
                    evidence = {'empty': False, 'removed': False, 'error': 'Resource cleanup evidence unavailable'}
                result["resource_cleanup"] = evidence
                cleanup = cleanup and evidence.get('empty') is True and evidence.get('removed') is True
        result["module_cleanup_ok"] = result.get("cleanup_ok")
        result["cleanup_ok"] = cleanup
        result["module_group_gone"] = group_gone
        result["mode"] = self.job.get("mode", "unknown")
        result["synthetic"] = self.job.get("mode") == "synthetic"
        state = "cancelled" if self.cancelled else "succeeded" if code == 0 and cleanup and not result.get("error") else "failed"
        self.completion = Completion(state=state, result=result, module_sha256=self.job["module_sha256"], cleanup_ok=cleanup)
        return self.completion


class Agent:
    def __init__(self, client, board_id, modules, spawn_guard=None, recover_scope=None):
        self.client, self.board_id, self.modules = client, board_id, modules
        self.journal = AgentJournal(getattr(modules, 'root', Path(modules.current[0]).parent), board_id)
        self.execution = None
        try:
            self.host = HostMonitor(getattr(modules, "root", Path(modules.current[0]).parent), enabled=modules.current[1].mode != "synthetic")
            self.spawn_guard = spawn_guard or self.host.place
            self._pending = self.journal.reconcile(recover_scope)
        except BaseException:
            self.journal.close()
            raise
        self.staging = None
        self.staging_cancel = threading.Event()
        self.downloads = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact")
        self.log_uploads = ThreadPoolExecutor(max_workers=1, thread_name_prefix="run-output")
        self.log_backlog, self.log_upload = {}, None
        self.log_retry_after = 0
        self.reload_ack = 0
        self.reload_requested = 0

    @property
    def pending(self):
        return self._pending

    @pending.setter
    def pending(self, value):
        if value is not None:
            self._pending = value
            try: self.journal.complete(*value)
            except OSError:
                # Keep the consumed execution result in memory. Delivery remains
                # gated on a durable checkpoint in _finish_pending, retried by tick.
                pass
        elif self._pending is not None:
            self.journal.acknowledge()
        self._pending = value

    def _finish_pending(self):
        run_id, completion = self.pending
        record = self.journal.record
        if not record or record.get('run_id') != run_id or record.get('phase') != 'completion' or record.get('completion') != completion.model_dump():
            self.journal.complete(run_id, completion)
        self.client.finish(self.board_id, run_id, completion)
        self.pending = None

    def _launch(self, snapshot, job, artifact_path=None, environment_path=None):
        try:
            self.execution = Execution(snapshot, job, artifact_path, environment_path,
                                       journal=self.journal, spawn_guard=self.spawn_guard, finish_guard=self.host.finish)
        except Exception as exc:
            # Launch failure can follow a partially applied external resource guard.
            self.pending = (job['id'], Completion(state='failed', result={
                'error': 'Execution launch failed: ' + type(exc).__name__, 'recovery_required': True},
                module_sha256=job['module_sha256'], cleanup_ok=False))

    def _stage(self, job, cancelled):
        artifact = self.client.fetch_artifact(self.board_id, job['plan']['artifact_sha256'], self.modules.root / 'artifacts')
        environment = None
        if job['plan'].get('environment_sha256'):
            environment = self.client.fetch_environment(self.board_id, job['plan']['environment_sha256'], self.modules.root / 'environments', cancelled=cancelled.is_set)
        return artifact, environment

    def _flush_logs(self):
        if not hasattr(self.client, 'logs'): return
        if self.execution:
            execution, run_id = self.execution, self.execution.job['id']
            execution.drain_logs()
            if not execution.logs_suppressed and (execution.log_events or execution.logs_truncated):
                # Eight runs, each with at most 512 KiB / 4096 events. Do not grow
                # a network-outage backlog at the expense of experiment execution.
                if run_id not in self.log_backlog and len(self.log_backlog) >= 8:
                    execution.logs_suppressed = execution.logs_truncated = True
                else:
                    record = self.log_backlog.setdefault(run_id, {'events': [], 'truncated': False, 'reported': False, 'closed': False})
                    record['events'].extend(execution.log_events)
                    record['truncated'] |= execution.logs_truncated
            execution.log_events = []
        if self.log_upload and self.log_upload[1].done():
            run_id, future, sent_cursor, sent_truncated = self.log_upload
            self.log_upload = None
            try:
                response = future.result()
                cursor = response['next_sequence']
                if not isinstance(cursor, int) or cursor < sent_cursor:
                    raise ValueError('Invalid log acknowledgement')
                record = self.log_backlog[run_id]
                record['events'] = [e for e in record['events'] if e['sequence'] > sent_cursor]
                record['reported'] |= sent_truncated
            except (ValueError, OSError, KeyError, TypeError):
                self.log_retry_after = time.monotonic() + 1
        for run_id, record in list(self.log_backlog.items()):
            if record['closed'] and not record['events'] and (not record['truncated'] or record['reported']):
                self.log_backlog.pop(run_id)
        if self.log_upload or time.monotonic() < self.log_retry_after: return
        for run_id, record in self.log_backlog.items():
            # 32 maximum-size Unicode events fit the API's 300 kB body limit.
            events = record['events'][:32]
            if not events and (not record['truncated'] or record['reported']): continue
            cursor = events[-1]['sequence'] if events else 0
            future = self.log_uploads.submit(self.client.logs, self.board_id, run_id, events, record['truncated'])
            self.log_upload = (run_id, future, cursor, record['truncated'])
            break

    def _close_logs(self, completion):
        self._flush_logs()
        record = self.log_backlog.get(self.execution.job['id'])
        if record:
            record['closed'] = True
            completion.result['live_logs_delivery_pending'] = bool(record['events'] or record['truncated'] and not record['reported'])
        if self.execution.logs_truncated:
            completion.result['live_logs_truncated'] = True

    def tick(self):
        self._flush_logs()
        if not self.execution and not self.pending and not self.staging:
            self.modules.reload(force=self.reload_requested > self.reload_ack)
            self.reload_ack = self.reload_requested
        snapshot, desc = self.modules.current
        desc = self.host.describe(desc)
        status = self.client.heartbeat(self.board_id, Heartbeat(description=desc, reload_ack=self.reload_ack,
                                                               reload_error=self.modules.error, physical_host_id=self.host.identity, telemetry=self.host.sample()))
        self.reload_requested = status["reload_requested"]
        if self.pending:
            self._finish_pending()
            return
        job = self.client.poll(self.board_id)
        if self.execution:
            if not job or job["id"] != self.execution.job["id"] or job["state"] == "cancelling": self.execution.stop(cancelled=True)
            completed = self.execution.poll()
            if completed:
                self._close_logs(completed)
                self.pending = (self.execution.job["id"], completed)
                self.execution = None
        elif self.staging:
            staged_snapshot, staged_job, future = self.staging
            if not job or job["id"] != staged_job["id"] or job["state"] == "cancelling":
                # A download owns no board processes; discard it without waiting to reload.
                self.staging_cancel.set()
                future.cancel()
                self.staging = None
                self.pending = (staged_job["id"], Completion(state="cancelled", result={"cleanup_ok": True, "code_executed": False}, module_sha256=staged_job["module_sha256"], cleanup_ok=True))
            elif future.done():
                self.staging = None
                try:
                    artifact_path, environment_path = future.result()
                except Exception as exc:
                    self.pending = (staged_job["id"], Completion(state="failed", result={"error": "Artifact staging failed: " + type(exc).__name__, "code_executed": False}, module_sha256=staged_job["module_sha256"], cleanup_ok=True))
                else:
                    self._launch(staged_snapshot, staged_job, artifact_path, environment_path)
        elif job:
            if not job["claimed"] or job["module_sha256"] != desc.module_sha256:
                self.pending = (job["id"], Completion(state="failed", result={"error": "Unknown or changed execution; inspect before recovery"},
                                                     module_sha256=job["module_sha256"], cleanup_ok=False))
            else:
                job["mode"] = desc.mode
                job["cleanup_scope"] = desc.cleanup_scope
                job["process_tree_execution"] = desc.process_tree_execution
                job["memory_overhead_mib"] = desc.memory_overhead_mib
                self.journal.claim(job)
                if job["plan"].get("artifact_sha256"):
                    self.staging_cancel = threading.Event()
                    future = self.downloads.submit(self._stage, job, self.staging_cancel)
                    self.staging = (snapshot, job, future)
                else:
                    self._launch(snapshot, job)

    def shutdown(self):
        try:
            if self.staging:
                _, job, future = self.staging
                self.staging_cancel.set()
                future.cancel()
                self.pending = (job["id"], Completion(state="cancelled", result={"code_executed": False}, module_sha256=job["module_sha256"], cleanup_ok=True))
                self.staging = None
            self.downloads.shutdown(wait=False, cancel_futures=True)
            if self.execution:
                self.execution.stop(cancelled=True)
                while (result := self.execution.poll()) is None: time.sleep(.1)
                self._close_logs(result)
                self.pending = (self.execution.job["id"], result)
                self.execution = None
            if self.pending:
                try:
                    self._finish_pending()
                except Exception: pass
            self.log_uploads.shutdown(wait=False, cancel_futures=True)
        finally:
            self.journal.close()


class LocalClient:
    def __init__(self, store): self.store = store
    def heartbeat(self, board, data): return self.store.heartbeat(board, data)
    def poll(self, board): return self.store.poll(board)
    def finish(self, board, run, data): return self.store.finish(board, run, data)

    def fetch_artifact(self, board, sha, root):
        return self.store.artifact_for_agent(board, sha)

    def fetch_environment(self, board, sha, root, cancelled=lambda: False):
        return self.store.environment_for_agent(board, sha)

    def logs(self, board, run, events, truncated=False):
        from .run_logs import RunLogs
        return RunLogs(self.store).append(board, run, events, truncated)
