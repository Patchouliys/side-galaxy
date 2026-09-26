"""Measure the Store API boundary; optional comparison with a prior Git revision."""
import argparse
import ctypes
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import statistics
import sqlite3
import subprocess
import tempfile
import time

from side_galaxy.models import Enrollment, Heartbeat, Description, Plan
from side_galaxy.store import Store
from side_galaxy.native import library


def legacy_store(ref):
    # Explicit revision input, never a shell command; no baseline implementation is shipped.
    source = subprocess.check_output(['git', 'show', ref + ':src/side_galaxy/store.py'], text=True)
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / 'legacy_store.py'
        file.write_text(source)
        spec = importlib.util.spec_from_file_location('side_galaxy._benchmark_legacy', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        class BaselineStore(module.Store):
            @contextmanager
            def tx(self):
                # Match the native engine's explicit durability settings; keep legacy SQL unchanged.
                db = sqlite3.connect(self.path, timeout=10)
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA checkpoint_fullfsync=ON")
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                finally:
                    db.close()
        return BaselineStore


def run(store_type, board_count, iterations, rounds):
    measurements = {'preflight': [], 'submit_cancel': []}
    with tempfile.TemporaryDirectory() as directory:
        store = store_type(Path(directory) / 'benchmark.db')
        desc = Description(name='Benchmark runtime', mode='synthetic', cpus=[0,1,2,3],
                           reserved_cpus=[0], memory_mib=4096, capabilities=['cpu-affinity','memory-limit','interference'],
                           templates=['cpu-contention'], module_sha256='f'*64, cleanup_scope='process-group')
        ids = []
        for number in range(board_count):
            board = store.enroll(Enrollment(name='benchmark-' + str(number)))['board_id']
            store.heartbeat(board, Heartbeat(description=desc))
            ids.append(board)
        plan = Plan(boards=ids, duration_seconds=1)
        # Warm up parsing, SQLite schema and native loading outside measured intervals.
        for _ in range(5): assert store.preflight(plan)['valid']
        for round_index in range(rounds):
            for board in ids: store.heartbeat(board, Heartbeat(description=desc))
            start = time.perf_counter_ns()
            for _ in range(iterations): assert store.preflight(plan)['valid']
            measurements['preflight'].append((time.perf_counter_ns()-start)/iterations/1e6)
            start = time.perf_counter_ns()
            for index in range(iterations):
                batch = store.submit(plan, f'{round_index}-{index}')
                cancelled = store.cancel(batch['id'])
                assert all(run['state'] == 'cancelled' for run in cancelled['runs'])
            measurements['submit_cancel'].append((time.perf_counter_ns()-start)/iterations/1e6)
    return {operation: {'median_ms': round(statistics.median(samples),4),
                        'operations_per_second': round(1000/statistics.median(samples),1),
                        'round_ms': [round(value,4) for value in samples]}
            for operation, samples in measurements.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--boards', type=int, default=16, choices=range(1,33))
    parser.add_argument('--iterations', type=int, default=60)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--baseline-ref', help='Explicit previous Git revision containing the Python Store')
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000 or not 1 <= args.rounds <= 20: parser.error('Invalid benchmark size')
    sqlite_version = library().sqlite3_libversion
    sqlite_version.argtypes = []
    sqlite_version.restype = ctypes.c_char_p
    result = {'boards': args.boards, 'iterations_per_round': args.iterations, 'rounds': args.rounds,
              'boundary': 'public Store methods including JSON bridge and SQLite transactions',
              'durability': 'WAL, synchronous=FULL, checkpoint_fullfsync=ON for both implementations',
              'sqlite_versions': {'native': sqlite_version().decode(), 'python': sqlite3.sqlite_version},
              'native': run(Store, args.boards, args.iterations, args.rounds)}
    if args.baseline_ref:
        result['baseline_ref'] = args.baseline_ref
        result['python'] = run(legacy_store(args.baseline_ref), args.boards, args.iterations, args.rounds)
        result['speedup'] = {name: round(result['python'][name]['median_ms']/result['native'][name]['median_ms'],3)
                             for name in result['native']}
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
