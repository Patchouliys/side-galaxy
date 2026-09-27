"""Small real workload for live logs, cancellation and portable environments."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import time

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=float, default=5)
args = parser.parse_args()
if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120:
    parser.error('--seconds must be in (0, 120]')
started, steps = time.monotonic(), 0
while time.monotonic() - started < args.seconds:
    steps += 1
    print(json.dumps({'step': steps, 'elapsed_seconds': round(time.monotonic() - started, 3)}), flush=True)
    time.sleep(min(.5, max(0, args.seconds - (time.monotonic() - started))))
result = {'architecture': platform.machine(), 'steps': steps, 'elapsed_seconds': time.monotonic() - started,
          'allowed_cpus': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None}
Path('result.json').write_text(json.dumps(result))
print('Completed; result.json is ready.', flush=True)
