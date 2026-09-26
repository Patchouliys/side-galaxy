"""Live affinity experiments on one locally configured, dedicated libvirt domain."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def virsh(*args):
    uri = os.environ.get("SG_LIBVIRT_URI", "qemu:///system")
    # No shell and no domain/URI supplied through network requests.
    return subprocess.check_output(["virsh", "--connect", uri, *args], text=True, timeout=10,
                                   env={**os.environ, "LC_ALL": "C"}, stderr=subprocess.PIPE).strip()


def domain():
    value = os.environ.get("SG_KVM_DOMAIN", "")
    if not value or value.startswith("-"): raise ValueError("Set SG_KVM_DOMAIN to a dedicated experiment VM")
    return str(uuid.UUID(virsh("domuuid", value)))


def pins(dom):
    rows = virsh("vcpupin", dom, "--live").splitlines()
    return {parts[0]: parts[1] for row in rows if len(parts := row.split()) == 2 and parts[0].isdigit()}


def describe():
    dom = domain()
    if virsh("domstate", dom) != "running": raise ValueError("Dedicated VM must be running")
    return {"protocol": 1, "name": "KVM live affinity", "mode": "kvm",
            "cpus": sorted(os.sched_getaffinity(0)), "reserved_cpus": [0], "memory_mib": 128,
            "capabilities": ["cpu-affinity"], "templates": ["kvm-affinity"]}


def run(plan):
    desc, dom = describe(), domain()
    if (plan["template"] != "kvm-affinity" or plan["interference_cpus"] or plan["memory_mib"] is not None
            or plan["bandwidth_percent"] is not None or 0 in plan["cpus"]
            or not set(plan["cpus"]) <= set(desc["cpus"])):
        raise ValueError("KVM module supports only live affinity; memory must be null and interferers empty")
    before = pins(dom)
    if not before: raise ValueError("No live vCPU affinity found")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    result = {"mode": "kvm", "synthetic": False, "domain_uuid": dom, "affinity_before": before,
              "boot_id_before": boot, "cleanup_ok": False}
    def cancel(signum, frame):
        raise InterruptedError("Experiment cancelled")
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        for vcpu in before:
            virsh("vcpupin", dom, vcpu, ",".join(map(str, plan["cpus"])), "--live")
        result["affinity_applied"] = pins(dom)
        result["stats_before"] = virsh("domstats", dom, "--cpu-total", "--vcpu")
        time.sleep(plan["duration_seconds"])
        result["stats_after"] = virsh("domstats", dom, "--cpu-total", "--vcpu")
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = type(exc).__name__
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        failures = []
        for vcpu, affinity in before.items():
            try: virsh("vcpupin", dom, vcpu, affinity, "--live")
            except Exception: failures.append(vcpu)
        try:
            result["affinity_restored"] = pins(dom)
            result["cleanup_ok"] = not failures and result["affinity_restored"] == before
        except Exception:
            result["cleanup_ok"] = False
        result["boot_id_after"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return result


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"])))
