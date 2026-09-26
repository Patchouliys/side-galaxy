"""Protocol/failure checks; the QGA below is a fake, never Pi/KVM acceptance."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from side_galaxy.modules import kvm, linux_process


DOMAIN = "00000000-0000-0000-0000-000000000001"
RUN = "00000000-0000-0000-0000-000000000002"


class Guest:
    def __init__(self, failure=None, cancel=False):
        self.failure, self.cancel = failure, cancel
        self.calls, self.files, self.handles, self.processes = [], {}, {}, {}
        self.started = self.stopped = self.removed = False
        self.partial = True

    def virsh(self, *args):
        self.calls.append(args)
        if args[0] != "qemu-agent-command" or args[1] != DOMAIN:
            raise AssertionError("Unexpected virsh request")
        command = json.loads(args[2])
        name, data = command["execute"], command.get("arguments", {})
        if name == "guest-ping":
            if self.failure == "missing-agent": raise RuntimeError("Guest unavailable")
            result = {}
        elif name == "guest-file-open":
            handle = len(self.handles) + 1
            self.handles[handle] = data["path"]
            self.files[data["path"]] = b""
            result = handle
        elif name == "guest-file-write":
            if self.failure == "write": raise RuntimeError("Transfer failed")
            chunk = base64.b64decode(data["buf-b64"])
            if self.partial:
                chunk, self.partial = chunk[:max(1, len(chunk) // 2)], False
            self.files[self.handles[data["handle"]]] += chunk
            result = {"count": len(chunk)}
        elif name == "guest-file-close":
            if self.failure == "close-ack": raise TimeoutError("Close reply lost")
            result = {}
        elif name == "guest-exec":
            self.assert_python(data)
            argv = data["arg"]
            code = argv[1]
            if code == kvm.START_RUNNER:
                self.started = True
                if self.failure == "start-ack": raise TimeoutError("Reply lost")
            if code == kvm.STOP_RUNNER:
                if self.failure == "stop": raise RuntimeError("Guest disconnected")
                self.stopped = True
            if code == kvm.REMOVE_DIRECTORY:
                if self.failure == "remove": raise RuntimeError("Cleanup failed")
                self.removed = True
            pid = len(self.processes) + 100
            self.processes[pid] = code
            result = {"pid": pid}
        elif name == "guest-exec-status":
            code = self.processes[data["pid"]]
            result = {"exited": True, "exitcode": 0}
            if self.failure == "python": result["exitcode"] = 1
            if code == kvm.START_RUNNER:
                if self.failure == "poll": raise RuntimeError("Lost guest")
                if self.cancel and not self.stopped:
                    result = {"exited": False}
                else:
                    body = {"exit_code": 1 if self.failure == "command" else 0,
                            "stdout": "experiment output", "stderr": "", "outputs": [],
                            "cleanup_ok": self.failure != "runner-cleanup", "steps": []}
                    if self.stopped: body.update(exit_code=-15, error="InterruptedError")
                    result["out-data"] = base64.b64encode(json.dumps(body).encode()).decode()
                    if self.failure == "truncate": result["out-truncated"] = True
        else:
            raise AssertionError(name)
        return json.dumps({"return": result})

    @staticmethod
    def assert_python(data):
        if data["path"] != "/usr/bin/python3" or data["arg"][0] != "-c":
            raise AssertionError("Only structured Python helper argv is expected")


class TransportTests(unittest.TestCase):
    def execute(self, failure=None, cancel=False):
        guest = Guest(failure, cancel)
        with tempfile.TemporaryDirectory() as root:
            bundle, runner = Path(root) / "bundle.zip", Path(root) / "runner.py"
            bundle.write_bytes(b"ZIP test bytes" * 12000)
            runner.write_bytes(b"runner test bytes")
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            plan = {"boards": ["test"], "template": "workload", "cpus": [1], "interference_cpus": [],
                    "memory_mib": None, "duration_seconds": 1, "artifact_sha256": digest,
                    "arguments": [], "environment": {}}
            request = {"artifact_path": str(bundle), "runner_path": str(runner), "run_id": RUN}
            with patch.object(kvm, "virsh", side_effect=guest.virsh):
                result = kvm.workload(DOMAIN, plan, request, lambda: cancel and guest.started)
            return result, guest, bundle.read_bytes(), runner.read_bytes()

    def test_qga_transfers_exact_bytes_in_chunks_and_runs_fixed_runner(self):
        result, guest, bundle, runner = self.execute()
        root = "/tmp/side-galaxy/" + RUN
        self.assertEqual(guest.files[root + "/bundle.zip"], bundle)
        self.assertEqual(guest.files[root + "/runner.py"], runner)
        self.assertGreater(len([x for x in guest.calls if "guest-file-write" in x[2]]), 3)
        self.assertEqual(result["stdout"], "experiment output")
        self.assertTrue(result["cleanup_ok"])
        self.assertTrue(guest.removed)
        self.assertNotIn("error", result)

    def test_transfer_failure_closes_file_and_removes_unused_workspace(self):
        result, guest, *_ = self.execute("write")
        self.assertTrue(result["cleanup_ok"])
        self.assertFalse(guest.started)
        self.assertTrue(any("guest-file-close" in x[2] for x in guest.calls))
        self.assertIn("error", result)

    def test_cancellation_waits_for_runner_cleanup_before_removing_workspace(self):
        result, guest, *_ = self.execute(cancel=True)
        self.assertTrue(guest.stopped)
        self.assertTrue(result["guest_processes_stopped"])
        self.assertTrue(result["cleanup_ok"])
        self.assertEqual(result["error"], "InterruptedError")

    def test_ambiguous_start_lost_guest_and_unconfirmed_cleanup_are_quarantined(self):
        for failure in ("start-ack", "poll", "runner-cleanup", "truncate", "remove", "close-ack"):
            with self.subTest(failure=failure):
                result, guest, *_ = self.execute(failure)
                self.assertFalse(result["cleanup_ok"])
                self.assertFalse(guest.removed)
        result, guest, *_ = self.execute("stop", cancel=True)
        self.assertFalse(result["cleanup_ok"])
        self.assertFalse(guest.removed)

    def test_nonzero_workload_exit_cannot_report_success(self):
        result, guest, *_ = self.execute("command")
        self.assertTrue(result["cleanup_ok"])
        self.assertIn("error", result)
        self.assertEqual(result["exit_code"], 1)

    def test_qga_capability_requires_ping_and_python(self):
        for failure, available in ((None, True), ("missing-agent", False), ("python", False)):
            guest = Guest(failure)
            with patch.object(kvm, "virsh", side_effect=guest.virsh):
                self.assertEqual(kvm.guest_available(DOMAIN), available)

    def test_linux_transports_real_bundle_to_runner_with_mocked_linux_limits(self):
        # Executes a real local program; mocks only Linux-specific resource calls on this host.
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("experiment.json", json.dumps({"schema": 1, "name": "transport-test",
                                  "run": [sys.executable, "-c", "print('module to runner')"]}))
            runner = Path(__file__).resolve().parents[1] / "src/side_galaxy/workload_runner.py"
            plan = {"cpus": [1], "interference_cpus": [], "memory_mib": 128, "duration_seconds": 3,
                    "artifact_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    "arguments": [], "environment": {}}
            request = {"artifact_path": str(bundle), "runner_path": str(runner), "run_id": RUN}
            with patch.object(linux_process.os, "sched_setaffinity", create=True), \
                 patch.object(linux_process.resource, "setrlimit"):
                result = linux_process.workload(plan, request)
            self.assertNotIn("error", result)
            self.assertTrue(result["cleanup_ok"])
            self.assertTrue(result["workspace_removed"])
            self.assertEqual(result["stdout"], "module to runner\n")
            self.assertEqual(result["resource_limits"]["per_process_address_space_mib"], 128)

    def test_affinity_restores_but_guest_cleanup_failure_remains_failure(self):
        desc = {"templates": ["workload"], "cpus": [0, 1, 2, 3]}
        plan = {"template": "workload", "cpus": [1], "interference_cpus": [], "memory_mib": None,
                "duration_seconds": 1}
        before = {"0": "0-3", "1": "0-3"}
        with patch.object(kvm, "describe", return_value=desc), patch.object(kvm, "domain", return_value=DOMAIN), \
             patch.object(kvm, "pins", side_effect=[before, {"0": "1", "1": "1"}, before]), \
             patch.object(kvm, "virsh", return_value="stats") as virsh, patch.object(kvm, "Path") as path, \
             patch.object(kvm, "workload", return_value={"cleanup_ok": False, "error": "Lost guest"}):
            path.return_value.read_text.return_value = "boot-id"
            result = kvm.run(plan, {})
        self.assertFalse(result["cleanup_ok"])
        self.assertEqual(result["affinity_restored"], before)
        self.assertEqual(result["boot_id_after"], result["boot_id_before"])
        virsh.assert_any_call("vcpupin", DOMAIN, "0", "0-3", "--live")

    def test_linux_limit_setup_failure_is_explicit_and_keeps_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            bundle, runner = Path(root) / "bundle.zip", Path(root) / "runner.py"
            bundle.write_bytes(b"bundle")
            runner.write_bytes(b"runner")
            plan = {"cpus": [1], "interference_cpus": [], "memory_mib": 128, "duration_seconds": 1,
                    "artifact_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}
            request = {"artifact_path": str(bundle), "runner_path": str(runner), "run_id": RUN}
            with patch.object(linux_process.subprocess, "Popen", side_effect=subprocess.SubprocessError("preexec failure")):
                result = linux_process.workload(plan, request)
            self.assertFalse(result["cleanup_ok"])
            self.assertEqual(result["error"], "SubprocessError")
            self.assertTrue(Path(result["workspace_retained"]).is_dir())
            shutil.rmtree(result["workspace_retained"])


if __name__ == "__main__": unittest.main()
