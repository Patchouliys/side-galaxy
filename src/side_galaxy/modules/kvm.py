"""Live experiments in one administrator-configured, dedicated libvirt domain."""
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import signal
import runpy
import subprocess
import sys
import time
import uuid


PYTHON = "/usr/bin/python3"
MAX_RESULT = 2 * 1024 * 1024


class GuestTransferUncertain(RuntimeError):
    """A guest file handle may remain open after a lost acknowledgement."""


# These helpers are fixed module code; network requests never supply guest shell text.
MAKE_DIRECTORY = """import os,stat,sys
base='/tmp/side-galaxy'
os.makedirs(base,mode=0o700,exist_ok=True)
s=os.lstat(base)
assert stat.S_ISDIR(s.st_mode) and s.st_uid==os.geteuid() and not s.st_mode & 0o022
os.mkdir(sys.argv[1],0o700)
"""
REMOVE_DIRECTORY = """import os,shutil,sys,uuid
root=sys.argv[1]
assert root=='/tmp/side-galaxy/'+str(uuid.UUID(root.rsplit('/',1)[1]))
assert not os.path.islink('/tmp/side-galaxy') and not os.path.islink(root)
shutil.rmtree(root)
assert not os.path.lexists(root)
"""
START_RUNNER = """import hashlib,os,pathlib,sys
runner,bundle,runner_hash,bundle_hash=sys.argv[1:5]
assert hashlib.sha256(pathlib.Path(runner).read_bytes()).hexdigest()==runner_hash
assert hashlib.sha256(pathlib.Path(bundle).read_bytes()).hexdigest()==bundle_hash
os.execv(sys.executable,[sys.executable,runner,'--bundle',bundle,*sys.argv[5:]])
"""
STOP_RUNNER = """import os,pathlib,signal,sys
try:
 fd=os.pidfd_open(int(sys.argv[1]))
 try:
  command=pathlib.Path('/proc/'+sys.argv[1]+'/cmdline').read_bytes().split(b'\\0')
  assert sys.argv[2].encode() in command
  signal.pidfd_send_signal(fd,signal.SIGTERM)
 finally: os.close(fd)
except (ProcessLookupError,FileNotFoundError): pass
"""


def virsh(*args):
    uri = os.environ.get("SG_LIBVIRT_URI", "qemu:///system")
    return subprocess.check_output(["virsh", "--connect", uri, *args], text=True, timeout=10,
                                   env={**os.environ, "LC_ALL": "C"}, stderr=subprocess.PIPE).strip()


def domain():
    value = os.environ.get("SG_KVM_DOMAIN", "")
    if not value or value.startswith("-"): raise ValueError("Set SG_KVM_DOMAIN to a dedicated experiment VM")
    return str(uuid.UUID(virsh("domuuid", value)))


def pins(dom):
    rows = virsh("vcpupin", dom, "--live").splitlines()
    return {parts[0]: parts[1] for row in rows if len(parts := row.split()) == 2 and parts[0].isdigit()}


def qga(dom, command, **arguments):
    request = {"execute": command}
    if arguments: request["arguments"] = arguments
    response = json.loads(virsh("qemu-agent-command", dom, json.dumps(request), "--timeout", "5"))
    if "error" in response or "return" not in response:
        raise RuntimeError("Guest agent command failed: " + command)
    return response["return"]


def guest_start(dom, argv):
    response = qga(dom, "guest-exec", path=PYTHON, arg=argv, **{"capture-output": True})
    pid = response.get("pid")
    if not isinstance(pid, int) or pid <= 0: raise ValueError("Invalid guest process ID")
    return pid


def guest_wait(dom, pid, deadline, cancelled=lambda: False):
    while True:
        if cancelled(): raise InterruptedError("Experiment cancelled")
        if time.monotonic() >= deadline: raise TimeoutError("Guest execution timed out")
        status = qga(dom, "guest-exec-status", pid=pid)
        if status.get("exited"): return status
        time.sleep(.15)


def guest_command(dom, argv, timeout=8):
    status = guest_wait(dom, guest_start(dom, argv), time.monotonic() + timeout)
    if status.get("exitcode") != 0: raise RuntimeError("Guest helper failed")
    return status


def guest_available(dom):
    try:
        qga(dom, "guest-ping")
        guest_command(dom, ["-c", "import os,signal,sys; assert sys.version_info >= (3,11); assert hasattr(signal,'pidfd_send_signal'); fd=os.pidfd_open(os.getpid()); os.close(fd)"], timeout=3)
        return True
    except Exception:
        return False


def guest_environment(dom):
    runner = Path(__file__).with_suffix('.runner.py')
    if not runner.is_file():
        runner = Path(__file__).resolve().parents[1] / 'workload_runner.py'
    probe = runpy.run_path(str(runner))['probe_execution_environment']
    code = 'import json\n' + inspect.getsource(probe) + '\nprint(json.dumps(probe_execution_environment()))'
    status = guest_command(dom, ['-c', code])
    if status.get('out-truncated') or len(status.get('out-data', '')) > 512 * 1024:
        raise ValueError('Guest environment probe output was truncated or oversized')
    value = json.loads(base64.b64decode(status.get('out-data', ''), validate=True))
    if not isinstance(value, dict):
        raise ValueError('Invalid guest environment probe')
    return value


def describe():
    dom = domain()
    if virsh("domstate", dom) != "running": raise ValueError("Dedicated VM must be running")
    capabilities, templates = ["cpu-affinity"], ["kvm-affinity"]
    environment = None
    if guest_available(dom):
        capabilities += ["workload-bundle", "guest-agent"]
        templates.append("workload")
        try: environment = guest_environment(dom)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError): pass
    return {"protocol": 1, "name": "KVM live experiments", "mode": "kvm",
            "cpus": sorted(os.sched_getaffinity(0)), "reserved_cpus": [0], "memory_mib": 128,
            "capabilities": capabilities, "templates": templates, "execution_environment": environment}


def guest_upload(dom, target, source, deadline, cancelled):
    try:
        handle = qga(dom, "guest-file-open", path=target, mode="wb")
    except Exception as exc:
        raise GuestTransferUncertain("Guest file open was not confirmed") from exc
    try:
        with source.open("rb") as stream:
            # ponytail: QGA suits small bundles; switch to guest-side object storage for large images.
            while chunk := stream.read(64 * 1024):
                while chunk:
                    if cancelled(): raise InterruptedError("Experiment cancelled")
                    if time.monotonic() >= deadline: raise TimeoutError("Guest transfer timed out")
                    reply = qga(dom, "guest-file-write", handle=handle,
                                **{"buf-b64": base64.b64encode(chunk).decode()})
                    count = reply.get("count", 0)
                    if not isinstance(count, int) or not 0 < count <= len(chunk):
                        raise RuntimeError("Guest file write made no valid progress")
                    chunk = chunk[count:]
    finally:
        try: qga(dom, "guest-file-close", handle=handle)
        except Exception as exc: raise GuestTransferUncertain("Guest file close was not confirmed") from exc


def runner_result(status):
    if status.get("out-truncated") or status.get("err-truncated"):
        raise ValueError("Guest agent truncated runner output")
    raw = base64.b64decode(status.get("out-data", ""), validate=True)
    if len(raw) > MAX_RESULT: raise ValueError("Oversized runner result")
    result = json.loads(raw)
    if (not isinstance(result, dict) or "exit_code" not in result
            or (result["exit_code"] is not None and type(result["exit_code"]) is not int)):
        raise ValueError("Invalid runner result")
    if result["exit_code"] is None:
        result["cleanup_ok"] = False
        result.setdefault("error", "Workload exit was not confirmed")
    if status.get("exitcode") != 0 and not result.get("error"):
        result["error"] = "Runner process failed"
    if result["exit_code"] != 0 and not result.get("error"):
        result["error"] = "Workload exited with nonzero status"
    return result


def workload(dom, plan, request, cancelled):
    run_id = str(uuid.UUID(request["run_id"]))
    root = "/tmp/side-galaxy/" + run_id
    bundle, runner = Path(request["artifact_path"]), Path(request["runner_path"])
    if not bundle.is_absolute() or not runner.is_absolute(): raise ValueError("Internal paths must be absolute")
    bundle_hash, runner_hash = hashlib.sha256(bundle.read_bytes()).hexdigest(), hashlib.sha256(runner.read_bytes()).hexdigest()
    if bundle_hash != plan["artifact_sha256"]: raise ValueError("Artifact integrity mismatch")
    result = {"artifact_sha256": bundle_hash, "runner_sha256": runner_hash,
              "guest_workspace": root, "cleanup_ok": False, "stage": "guest-prepare"}
    created = False
    start_attempted, pid, status = False, None, None
    try:
        if cancelled(): raise InterruptedError("Experiment cancelled")
        guest_command(dom, ["-c", MAKE_DIRECTORY, root])
        created = True
        result["stage"] = "guest-transfer"
        deadline = time.monotonic() + 60
        guest_upload(dom, root + "/bundle.zip", bundle, deadline, cancelled)
        guest_upload(dom, root + "/runner.py", runner, deadline, cancelled)
        if cancelled(): raise InterruptedError("Experiment cancelled")
        result["stage"] = "guest-run"
        start_attempted = True  # Lost acknowledgement can mean an active guest process.
        pid = guest_start(dom, ["-c", START_RUNNER, root + "/runner.py", root + "/bundle.zip",
                               runner_hash, bundle_hash, "--workspace", root + "/work",
                               "--plan", json.dumps(plan)])
        result["guest_pid"] = pid
        status = guest_wait(dom, pid, time.monotonic() + plan["duration_seconds"] + 15, cancelled)
        result.update(runner_result(status))
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = type(exc).__name__
        if isinstance(exc, GuestTransferUncertain): result["transfer_cleanup_confirmed"] = False
    finally:
        # A finished runner's JSON is the cleanup evidence for its own child groups.
        stopped = not start_attempted and result.get("transfer_cleanup_confirmed", True)
        if pid is not None and status is None:
            try:
                guest_command(dom, ["-c", STOP_RUNNER, str(pid), root + "/runner.py"], timeout=5)
                status = guest_wait(dom, pid, time.monotonic() + 12)
                details = runner_result(status)
                original_error = result.get("error")
                result.update(details)
                if original_error: result["error"] = original_error
            except Exception as exc:
                result["cleanup_error"] = type(exc).__name__
        if status is not None: stopped = result.get("cleanup_ok") is True
        result["guest_processes_stopped"] = stopped
        result["cleanup_ok"] = False
        if stopped and created:
            try:
                guest_command(dom, ["-c", REMOVE_DIRECTORY, root])
                result["guest_workspace_removed"] = True
                result["cleanup_ok"] = True
            except Exception as exc:
                result["cleanup_error"] = type(exc).__name__
        # Unknown guest execution is quarantined with its workspace retained for inspection.
    return result


def run(plan, request=None):
    desc, dom = describe(), domain()
    duration_limit = 86400 if plan["template"] == "workload" else 120
    if (plan["template"] not in desc["templates"] or plan["interference_cpus"] or plan["memory_mib"] is not None
            or plan.get("bandwidth_percent") is not None or not plan["cpus"] or 0 in plan["cpus"]
            or len(set(plan["cpus"])) != len(plan["cpus"])
            or not set(plan["cpus"]) <= set(desc["cpus"]) or not 1 <= plan["duration_seconds"] <= duration_limit):
        raise ValueError("Unsupported KVM plan; memory must be null and interferers empty")
    before = pins(dom)
    if not before: raise ValueError("No live vCPU affinity found")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    result = {"mode": "kvm", "synthetic": False, "domain_uuid": dom, "affinity_before": before,
              "boot_id_before": boot, "cleanup_ok": False}
    cancelled = False
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    guest_clean = True
    try:
        for vcpu in before:
            if cancelled: raise InterruptedError("Experiment cancelled")
            virsh("vcpupin", dom, vcpu, ",".join(map(str, plan["cpus"])), "--live")
        result["affinity_applied"] = pins(dom)
        result["stats_before"] = virsh("domstats", dom, "--cpu-total", "--vcpu")
        if plan["template"] == "workload":
            guest_clean = False
            details = workload(dom, plan, request or {}, lambda: cancelled)
            result.update(details)
            guest_clean = details.get("cleanup_ok") is True
        else:
            deadline = time.monotonic() + plan["duration_seconds"]
            while time.monotonic() < deadline:
                if cancelled: raise InterruptedError("Experiment cancelled")
                time.sleep(min(.2, max(0, deadline - time.monotonic())))
        if cancelled: result.setdefault("error", "InterruptedError")
        result["stats_after"] = virsh("domstats", dom, "--cpu-total", "--vcpu")
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = type(exc).__name__
    finally:
        failures = []
        for vcpu, affinity in before.items():
            try: virsh("vcpupin", dom, vcpu, affinity, "--live")
            except Exception: failures.append(vcpu)
        try:
            result["affinity_restored"] = pins(dom)
            result["cleanup_ok"] = guest_clean and not failures and result["affinity_restored"] == before
        except Exception:
            result["cleanup_ok"] = False
        result["boot_id_after"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        for sig, handler in previous.items(): signal.signal(sig, handler)
    return result


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"], request)))
