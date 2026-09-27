"""Non-privileged Linux microbenchmarks. Affinity is not exclusive CPU isolation."""
import json
import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import platform
import resource
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def execution_environment():
    runner = Path(__file__).with_suffix('.runner.py')
    if not runner.is_file():
        runner = Path(__file__).resolve().parents[1] / 'workload_runner.py'
    return runpy.run_path(str(runner))['probe_execution_environment']()


def describe():
    if platform.system() != "Linux" or not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("Linux sched_setaffinity is required")
    mem = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))) // 1024
    return {"protocol": 1, "name": "Linux process runtime", "mode": "linux-process",
            "cpus": sorted(os.sched_getaffinity(0)), "reserved_cpus": [0],
            "memory_mib": max(128, mem // 2), "memory_limit_required": True,
            "cleanup_scope": "process-group", "process_tree_execution": True, "capabilities": ["cpu-affinity", "memory-limit", "interference", "workload-bundle"],
            "templates": ["cpu-contention", "memory-copy", "workload"],
            "execution_environment": execution_environment()}


def worker(core, seconds, memory_mib, template, send):
    os.sched_setaffinity(0, {core})
    budget = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    count, started = 0, time.monotonic()
    block = bytearray(1024 * 1024) if template == "memory-copy" else None
    while time.monotonic() - started < seconds:
        if block is not None:
            copied = block[:]
            count += len(copied)
        else:
            sum(i * i for i in range(1000))
            count += 1
    send.send({"cpu": core, "work_units": count, "elapsed_seconds": time.monotonic() - started,
               "unit": "copied_bytes" if block is not None else "1000_integer_squares"})
    send.close()


def workload(plan, request):
    bundle, runner = Path(request["artifact_path"]), Path(request["runner_path"])
    run_id = str(uuid.UUID(request["run_id"]))
    if not bundle.is_absolute() or not runner.is_absolute(): raise ValueError("Internal paths must be absolute")
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if bundle_hash != plan["artifact_sha256"]: raise ValueError("Artifact integrity mismatch")
    if plan["interference_cpus"]: raise ValueError("Workload bundles define their own interference")
    if not plan["memory_mib"] or plan["memory_mib"] < 128:
        raise ValueError("At least 128 MiB address-space budget is required")
    result = {"artifact_sha256": bundle_hash, "runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
              "cleanup_ok": False, "resource_limits": {"cpus": plan["cpus"], "per_process_address_space_mib": plan["memory_mib"]}}
    cancelled = False
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    def limits():
        os.sched_setaffinity(0, set(plan["cpus"]))
        budget = plan["memory_mib"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    root = None
    try:
        root = tempfile.mkdtemp(prefix="side-galaxy-" + run_id + "-")
        with tempfile.TemporaryFile() as output:
            # The runner tracks child process groups; do not detach it from the module's group.
            process = subprocess.Popen([sys.executable, str(runner), "--bundle", str(bundle),
                                        "--workspace", str(Path(root) / "work"), "--plan", json.dumps(plan)],
                                       stdout=output, stderr=subprocess.DEVNULL, preexec_fn=limits,
                                       pass_fds=(int(os.environ['SG_EVENT_FD']),) if os.environ.get('SG_EVENT_FD') else (),
                                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
                                            **({'SG_EVENT_FD': os.environ['SG_EVENT_FD']} if os.environ.get('SG_EVENT_FD') else {})})
            deadline, stopping, forced = time.monotonic() + plan["duration_seconds"] + 15, None, False
            try:
                while process.poll() is None:
                    if (cancelled or time.monotonic() >= deadline) and stopping is None:
                        stopping = time.monotonic()
                        process.terminate()
                    if stopping is not None and time.monotonic() - stopping > 12:
                        forced = True
                        process.kill()
                    time.sleep(.1)
                output.seek(0)
                raw = output.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024: raise ValueError("Oversized runner result")
                data = json.loads(raw)
                if (not isinstance(data, dict) or "exit_code" not in data
                        or (data["exit_code"] is not None and type(data["exit_code"]) is not int)):
                    raise ValueError("Invalid runner result")
                result.update(data)
                result["cleanup_ok"] = data.get("cleanup_ok") is True and data["exit_code"] is not None and not forced
                if (process.returncode != 0 or data["exit_code"] != 0) and not result.get("error"):
                    result["error"] = "Workload exited with nonzero status"
                if stopping is not None: result.setdefault("error", "InterruptedError" if cancelled else "TimeoutError")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                    result["cleanup_ok"] = False
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = type(exc).__name__
        result["cleanup_ok"] = False
    finally:
        if root is not None:
            if result.get("cleanup_ok") is True:
                try:
                    shutil.rmtree(root)
                    result["workspace_removed"] = True
                except OSError:
                    result["cleanup_ok"] = False
            if result.get("cleanup_ok") is not True:
                result["workspace_retained"] = root
        for sig, handler in previous.items(): signal.signal(sig, handler)
    return result


def run(plan, request=None):
    desc = describe()
    cores = plan["cpus"] + plan["interference_cpus"]
    duration_limit = 86400 if plan["template"] == "workload" else 120
    if (not set(cores) <= set(desc["cpus"]) or 0 in cores or len(set(cores)) != len(cores)
            or not cores or plan.get("bandwidth_percent") is not None or plan["template"] not in desc["templates"]
            or not 1 <= plan["duration_seconds"] <= duration_limit):
        raise ValueError("Unsupported resource plan")
    if plan["template"] == "workload":
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        result = workload(plan, request or {})
        result.update(mode="linux-process", synthetic=False, boot_id_before=boot,
                      boot_id_after=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                      note="Trusted host processes; affinity and per-process RLIMIT_AS are not a security sandbox or aggregate memory limit")
        return result
    if not plan["memory_mib"] or plan["memory_mib"] // len(cores) < 64:
        raise ValueError("At least 64 MiB of address-space budget per worker required")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    ctx, children, samples = mp.get_context("fork"), [], []
    try:
        for core in cores:
            receive, send = ctx.Pipe(duplex=False)
            child = ctx.Process(target=worker, args=(core, plan["duration_seconds"], plan["memory_mib"] // len(cores), plan["template"], send))
            child.start()
            send.close()
            children.append((child, receive))
        for child, receive in children:
            child.join(plan["duration_seconds"] + 5)
            if child.exitcode != 0 or not receive.poll(): raise RuntimeError("Worker failed or timed out")
            samples.append(receive.recv())
            receive.close()
    finally:
        for child, _ in children:
            if child.is_alive(): child.kill()
            child.join()
    return {"mode": "linux-process", "synthetic": False, "cleanup_ok": True, "samples": samples,
            "boot_id_before": boot, "boot_id_after": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "note": "Host processes only; no exclusive CPU, guest isolation or hardware QoS guarantee"}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"], request)))
