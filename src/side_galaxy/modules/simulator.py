"""Standalone module protocol v1. All outputs are synthetic, never measurements."""
import json
import sys
import time


def describe():
    return {"protocol": 1, "name": "Galaxy simulator", "mode": "synthetic", "cpus": list(range(4)),
            "reserved_cpus": [0], "memory_mib": 4096,
            "cleanup_scope": "process-group", "capabilities": ["cpu-affinity", "memory-limit", "interference"],
            "templates": ["cpu-contention", "memory-copy"]}


def run(plan):
    time.sleep(plan["duration_seconds"])
    return {"mode": "synthetic", "synthetic": True, "cleanup_ok": True,
            "boot_id_before": "simulation", "boot_id_after": "simulation",
            "metrics": {"sample_operations": 12000 * plan["duration_seconds"],
                        "sample_latency_ms": 1.25 + len(plan["interference_cpus"]) * .4},
            "note": "Deterministic illustrative values; not hardware measurements"}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"])))
