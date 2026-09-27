"""Bounded measured history, independent of scheduling transactions."""
import json
import time

MAX_SAMPLES = 720


class Telemetry:
    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS telemetry (id INTEGER PRIMARY KEY, board_id TEXT NOT NULL REFERENCES boards(id), sampled REAL NOT NULL, received REAL NOT NULL, sample TEXT NOT NULL)')
            if 'physical_host_key' not in {row['name'] for row in db.execute('PRAGMA table_info(telemetry)')}:
                db.execute('ALTER TABLE telemetry ADD COLUMN physical_host_key TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS telemetry_board ON telemetry(board_id,id)')

    def append(self, board_id, sample):
        if sample is None: return
        now = time.time()
        with self.store.tx() as db:
            board = db.execute('SELECT physical_host_id FROM boards WHERE id=?', (board_id,)).fetchone()
            if board is None: raise KeyError(board_id)
            host = 'host:' + board['physical_host_id'] if board['physical_host_id'] else 'board:' + board_id
            previous = db.execute('SELECT sampled,received FROM telemetry WHERE board_id=? AND physical_host_key=? ORDER BY id DESC LIMIT 1', (board_id, host)).fetchone()
            if previous and (sample.sampled_at == previous['sampled'] or now - previous['received'] < 4): return
            body = sample.model_dump()
            db.execute('INSERT INTO telemetry(board_id,sampled,received,sample,physical_host_key) VALUES(?,?,?,?,?)', (board_id, sample.sampled_at, now, json.dumps(body), host))
            db.execute('DELETE FROM telemetry WHERE board_id=? AND id NOT IN (SELECT id FROM telemetry WHERE board_id=? ORDER BY id DESC LIMIT ?)', (board_id, board_id, MAX_SAMPLES))

    def read(self, board_id, limit=60):
        if type(limit) is not int or not 1 <= limit <= MAX_SAMPLES: raise ValueError('History limit must be between 1 and 720')
        boards = self.store.boards()
        board = next((b for b in boards if b['id'] == board_id), None)
        if board is None: raise KeyError(board_id)
        host = board.get('physical_host_key') or 'board:' + board_id
        with self.store.tx() as db:
            rows = db.execute('SELECT received,sample FROM telemetry WHERE board_id=? AND physical_host_key=? ORDER BY id DESC LIMIT ?', (board_id, host, limit)).fetchall()
            history = [{**json.loads(r['sample']), 'received_at': r['received']} for r in reversed(rows)]
            allocations = []
            for item in db.execute("SELECT r.id,r.board_id,r.batch_id,r.state,b.plan,d.description FROM runs r JOIN batches b ON b.id=r.batch_id JOIN boards d ON d.id=r.board_id WHERE r.physical_host_key=? AND r.state IN ('queued','running','cancelling')", (host,)):
                plan = json.loads(item['plan'])
                allocations.append({'run_id': item['id'], 'board_id': item['board_id'], 'batch_id': item['batch_id'], 'state': item['state'],
                                    'cpus': plan['cpus'], 'interference_cpus': plan.get('interference_cpus', []), 'memory_mib': plan.get('memory_mib'),
                                    'resource_policy': plan.get('resource_policy', 'auto'),
                                    'memory_overhead_mib': json.loads(item['description'] or '{}').get('memory_overhead_mib', 0)})
        latest = history[-1] if history else None
        return {'board_id': board_id, 'physical_host_id': board.get('physical_host_id'), 'sample_interval_seconds': 5,
                'stale_after_seconds': 20, 'latest': latest, 'history': history, 'allocations': allocations,
                'stale': latest is None or time.time() - latest['received_at'] > 20,
                'host_quarantined': board.get('host_quarantined', bool(board.get('quarantined')))}
