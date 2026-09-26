import argparse
import hashlib
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument('--iterations', type=int, default=1000)
args = parser.parse_args()
if not 1 <= args.iterations <= 1000000:
    parser.error('--iterations 必须在 1 到 1000000 之间')

started = time.perf_counter()
value = b'side-galaxy'
for _ in range(args.iterations):
    value = hashlib.sha256(value).digest()
result = {
    'label': os.environ.get('EXPERIMENT_LABEL', 'baseline'),
    'iterations': args.iterations,
    'elapsed_seconds': time.perf_counter() - started,
    'checksum': value.hex(),
}
Path('results/summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False))
