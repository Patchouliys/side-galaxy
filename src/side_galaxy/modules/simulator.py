"""Standalone module protocol v1. All outputs are synthetic, never measurements."""
import hashlib
import json
from pathlib import Path
import zipfile
import sys
import time


def describe():
    return {"protocol": 1, "name": "Galaxy simulator", "mode": "synthetic", "cpus": list(range(4)),
            "reserved_cpus": [0], "memory_mib": 4096,
            "cleanup_scope": "process-group", "capabilities": ["cpu-affinity", "memory-limit", "interference"],
            "templates": ["cpu-contention", "memory-copy", "workload"]}


def run(plan):
    time.sleep(plan["duration_seconds"])
    return {"mode": "synthetic", "synthetic": True, "cleanup_ok": True,
            "boot_id_before": "simulation", "boot_id_after": "simulation",
            "metrics": {"sample_operations": 12000 * plan["duration_seconds"],
                        "sample_latency_ms": 1.25 + len(plan["interference_cpus"]) * .4},
            "note": "Deterministic illustrative values; not hardware measurements"}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    if request["op"] == "run" and request["plan"]["template"] == "workload":
        data = Path(request["artifact_path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != request["plan"]["artifact_sha256"]: raise ValueError("Artifact digest mismatch")
        with zipfile.ZipFile(request["artifact_path"]) as bundle:
            manifest = json.loads(bundle.read("experiment.json"))
        print(json.dumps({"mode": "synthetic", "synthetic": True, "cleanup_ok": True, "code_executed": False,
                          "artifact_sha256": request["plan"]["artifact_sha256"], "manifest": manifest,
                          "stdout": "Artifact received and verified. Simulator does not execute uploaded code.", "outputs": []}))
        sys.exit(0)
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"])))
