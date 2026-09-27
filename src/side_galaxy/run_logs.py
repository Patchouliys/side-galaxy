"""Bounded experiment output; the native core still owns run state and leases."""
import hashlib
from .store import Conflict

MAX_LOG_BYTES = 512 * 1024
MAX_EVENTS = 4096


class RunLogs:
    def __init__(self, store):
        self.store = store
        with store.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS run_log_state (run_id TEXT PRIMARY KEY REFERENCES runs(id), sequence INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, truncated INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS run_log_events (run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, stream TEXT NOT NULL, text TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(run_id,sequence))')
            if 'retained' not in {row['name'] for row in db.execute('PRAGMA table_info(run_log_events)')}:
                db.execute('ALTER TABLE run_log_events ADD COLUMN retained INTEGER NOT NULL DEFAULT 1')

    def append(self, board_id, run_id, events, truncated=False):
        with self.store.tx() as db:
            run = db.execute('SELECT board_id,state,started FROM runs WHERE id=?', (run_id,)).fetchone()
            if not run or run['board_id'] != board_id: raise KeyError(run_id)
            if run['started'] is None or run['state'] in ('waiting', 'queued'):
                raise Conflict('Only claimed runs can publish output')
            db.execute('INSERT OR IGNORE INTO run_log_state(run_id) VALUES(?)', (run_id,))
            state = db.execute('SELECT * FROM run_log_state WHERE run_id=?', (run_id,)).fetchone()
            cursor, total, cut = state['sequence'], state['bytes'], bool(state['truncated']) or truncated
            for event in events:
                seq, stream, text = event['sequence'], event['stream'], event['text']
                data = text.encode('utf-8')
                digest = hashlib.sha256(stream.encode() + b'\0' + data).hexdigest()
                if seq <= cursor:
                    old = db.execute('SELECT digest FROM run_log_events WHERE run_id=? AND sequence=?', (run_id, seq)).fetchone()
                    if old is None: raise Conflict('Log sequence fingerprint expired; resume from acknowledged cursor')
                    if old['digest'] != digest: raise Conflict('Log sequence has different content')
                    continue
                if seq != cursor + 1: raise Conflict('Log sequence gap; retry from acknowledged cursor')
                cursor = seq
                retained = total + len(data) <= MAX_LOG_BYTES and seq <= MAX_EVENTS
                if seq <= MAX_EVENTS:
                    db.execute('INSERT INTO run_log_events(run_id,sequence,stream,text,digest,retained) VALUES(?,?,?,?,?,?)',
                               (run_id, seq, stream, text if retained else '', digest, retained))
                if retained: total += len(data)
                else: cut = True
            db.execute('UPDATE run_log_state SET sequence=?,bytes=?,truncated=? WHERE run_id=?', (cursor, total, cut, run_id))
        return {'next_sequence': cursor, 'truncated': cut}

    def read(self, run_id, after=0):
        with self.store.tx() as db:
            if not db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone(): raise KeyError(run_id)
            state = db.execute('SELECT * FROM run_log_state WHERE run_id=?', (run_id,)).fetchone()
            rows = db.execute('SELECT sequence,stream,text FROM run_log_events WHERE run_id=? AND sequence>? AND retained=1 ORDER BY sequence LIMIT 128', (run_id, after)).fetchall()
        cursor = rows[-1]['sequence'] if len(rows) == 128 else max(after, state['sequence'] if state else 0)
        return {'events': [dict(row) for row in rows], 'next_sequence': cursor, 'truncated': bool(state and state['truncated'])}
