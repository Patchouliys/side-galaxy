"""Non-privileged Linux microbenchmarks. Affinity is not exclusive CPU isolation."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import resource
import sys
import time


def describe():
    if platform.system() != "Linux" or not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("Linux sched_setaffinity is required")
    mem = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))) // 1024
    return {"protocol": 1, "name": "Linux process runtime", "mode": "linux-process",
            "cpus": sorted(os.sched_getaffinity(0)), "reserved_cpus": [0],
            "memory_mib": max(128, mem // 2), "cleanup_scope": "process-group", "capabilities": ["cpu-affinity", "memory-limit", "interference"],
            "templates": ["cpu-contention", "memory-copy"]}


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


def run(plan):
    desc = describe()
    cores = plan["cpus"] + plan["interference_cpus"]
    if (not set(cores) <= set(desc["cpus"]) or 0 in cores or len(set(cores)) != len(cores)
            or plan["bandwidth_percent"] is not None or plan["template"] not in desc["templates"]):
        raise ValueError("Unsupported resource plan")
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
    print(json.dumps(describe() if request["op"] == "describe" else run(request["plan"])))
