import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import Plan

ACTIVE = ("queued", "running", "cancelling")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS boards (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, board_profile TEXT NOT NULL,
                  system_profile TEXT NOT NULL, token_hash TEXT NOT NULL,
                  description TEXT, seen REAL NOT NULL DEFAULT 0,
                  quarantined INTEGER NOT NULL DEFAULT 0,
                  reload_requested INTEGER NOT NULL DEFAULT 0,
                  reload_ack INTEGER NOT NULL DEFAULT 0, reload_error TEXT,
                  local INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS batches (
                  id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL,
                  plan TEXT NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
                  board_id TEXT NOT NULL REFERENCES boards(id),
                  state TEXT NOT NULL, created REAL NOT NULL, started REAL,
                  finished REAL, module_sha256 TEXT, result TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS board_lease ON runs(board_id)
                  WHERE state IN ('queued','running','cancelling');
            """)

    @contextmanager
    def tx(self):
        # ponytail: one SQLite writer; use PostgreSQL when multi-server scheduling is needed.
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enroll(self, data, local=False, board_id=None):
        token = secrets.token_urlsafe(32)
        board_id = board_id or str(uuid.uuid4())
        with self.tx() as db:
            db.execute("INSERT INTO boards(id,name,board_profile,system_profile,token_hash,local) VALUES(?,?,?,?,?,?)",
                       (board_id, data.name, data.board_profile, data.system_profile, digest(token), local))
        return {"board_id": board_id, "agent_token": token}

    def agent_allowed(self, board_id, token):
        with self.tx() as db:
            row = db.execute("SELECT token_hash FROM boards WHERE id=?", (board_id,)).fetchone()
        return bool(row and secrets.compare_digest(row[0], digest(token)))

    def heartbeat(self, board_id, heartbeat):
        with self.tx() as db:
            db.execute("UPDATE boards SET description=?, seen=?, reload_ack=?, reload_error=? WHERE id=?",
                       (canonical(heartbeat.description.model_dump()), time.time(), heartbeat.reload_ack,
                        heartbeat.reload_error, board_id))
            row = db.execute("SELECT reload_requested,quarantined FROM boards WHERE id=?", (board_id,)).fetchone()
        return dict(row)

    def _expire(self, db):
        now = time.time()
        rows = db.execute("""SELECT r.*, b.seen, ba.plan FROM runs r JOIN boards b ON b.id=r.board_id
                             JOIN batches ba ON ba.id=r.batch_id WHERE r.state IN ('queued','running','cancelling')""").fetchall()
        for row in rows:
            duration = json.loads(row["plan"])["duration_seconds"]
            if now - row["seen"] > 30 or (row["started"] and now - row["started"] > duration + 45):
                state = "failed" if row["state"] == "queued" else "lost"
                db.execute("UPDATE runs SET state=?,finished=?,result=? WHERE id=?",
                           (state, now, canonical({"error": "agent heartbeat or execution deadline expired"}), row["id"]))
                db.execute("UPDATE boards SET quarantined=1 WHERE id=?", (row["board_id"],))

    def boards(self):
        with self.tx() as db:
            self._expire(db)
            rows = db.execute("""SELECT b.*,r.id AS active_run FROM boards b LEFT JOIN runs r
                ON b.id=r.board_id AND r.state IN ('queued','running','cancelling') ORDER BY b.name""").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop("token_hash")
            item["description"] = json.loads(item["description"]) if item["description"] else None
            item["status"] = ("quarantined" if item["quarantined"] else "offline" if time.time()-item["seen"]>30
                              else "busy" if item["active_run"] else "ready")
            result.append(item)
        return result

    def _check(self, db, plan):
        errors, targets = [], []
        for board_id in plan.boards:
            b = db.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
            reasons = []
            if not b:
                errors.append({"board_id": board_id, "reasons": ["unknown board"]})
                continue
            desc = json.loads(b["description"]) if b["description"] else {}
            if time.time() - b["seen"] > 30: reasons.append("board offline")
            if b["quarantined"]: reasons.append("board quarantined; verify cleanup before recovery")
            if db.execute("SELECT 1 FROM runs WHERE board_id=? AND state IN ('queued','running','cancelling')", (board_id,)).fetchone():
                reasons.append("board lease occupied")
            cores = set(plan.cpus + plan.interference_cpus)
            if not cores <= set(desc.get("cpus", [])): reasons.append("CPU unavailable")
            if cores & set(desc.get("reserved_cpus", [])): reasons.append("management CPU reserved")
            if plan.template not in desc.get("templates", []): reasons.append("template unsupported")
            caps = desc.get("capabilities", [])
            if "cpu-affinity" not in caps: reasons.append("CPU affinity unsupported")
            if plan.memory_mib is not None and ("memory-limit" not in caps or plan.memory_mib > desc.get("memory_mib", 0)):
                reasons.append("memory limit unsupported or exceeds available budget")
            if plan.bandwidth_percent is not None and "bandwidth-limit" not in caps:
                reasons.append("hardware bandwidth control unsupported")
            if plan.interference_cpus and "interference" not in caps:
                reasons.append("module does not support interferers")
            if reasons: errors.append({"board_id": board_id, "reasons": reasons})
            targets.append({"board_id": board_id, "name": b["name"], "mode": desc.get("mode"),
                            "module_sha256": desc.get("module_sha256")})
        return {"valid": not errors, "errors": errors, "targets": targets,
                "plan_sha256": digest(canonical(plan.model_dump()))}

    def preflight(self, plan):
        with self.tx() as db:
            self._expire(db)
            return self._check(db, plan)

    def submit(self, plan, key):
        body = canonical(plan.model_dump())
        with self.tx() as db:
            self._expire(db)
            old = db.execute("SELECT id,plan FROM batches WHERE key=?", (key,)).fetchone()
            if old:
                if old["plan"] != body: raise Conflict("Idempotency key belongs to a different plan")
                batch_id = old["id"]
            else:
                checked = self._check(db, plan)
                if not checked["valid"]: raise Conflict(canonical(checked))
                batch_id, now = str(uuid.uuid4()), time.time()
                db.execute("INSERT INTO batches VALUES(?,?,?,?,?)", (batch_id, key, body, digest(body), now))
                for target in checked["targets"]:
                    db.execute("INSERT INTO runs(id,batch_id,board_id,state,created,module_sha256) VALUES(?,?,?,?,?,?)",
                               (str(uuid.uuid4()), batch_id, target["board_id"], "queued", now, target["module_sha256"]))
        return self.batch(batch_id)

    def batch(self, batch_id):
        with self.tx() as db:
            self._expire(db)
            row = db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not row: raise KeyError(batch_id)
            result = dict(row)
            result.pop("key")
            result["plan"] = json.loads(result["plan"])
            result["runs"] = [self._run(r) for r in db.execute("SELECT * FROM runs WHERE batch_id=? ORDER BY created,id", (batch_id,))]
            return result

    @staticmethod
    def _run(row):
        item = dict(row)
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def batches(self):
        with self.tx() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM batches ORDER BY created DESC LIMIT 100")]
        return [self.batch(i) for i in ids]

    def poll(self, board_id):
        with self.tx() as db:
            self._expire(db)
            board = db.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
            if not board or board["quarantined"]: return None
            row = db.execute("SELECT * FROM runs WHERE board_id=? AND state IN ('queued','running','cancelling')", (board_id,)).fetchone()
            if not row: return None
            claimed = row["state"] == "queued"
            if claimed:
                current = json.loads(board["description"])["module_sha256"]
                if current != row["module_sha256"]:
                    db.execute("UPDATE runs SET state='failed',finished=?,result=? WHERE id=?",
                               (time.time(), canonical({"error": "module changed after admission; submit again"}), row["id"]))
                    return None
                db.execute("UPDATE runs SET state='running',started=? WHERE id=?", (time.time(), row["id"]))
                row = db.execute("SELECT * FROM runs WHERE id=?", (row["id"],)).fetchone()
            result = self._run(row)
            result["claimed"] = claimed
            result["plan"] = json.loads(db.execute("SELECT plan FROM batches WHERE id=?", (row["batch_id"],)).fetchone()[0])
            return result

    def finish(self, board_id, run_id, completion):
        with self.tx() as db:
            row = db.execute("SELECT * FROM runs WHERE id=? AND board_id=?", (run_id, board_id)).fetchone()
            if not row: raise KeyError(run_id)
            if row["state"] == "queued": raise Conflict("Run must be claimed before completion")
            if completion.module_sha256 != row["module_sha256"]: raise Conflict("Module generation mismatch")
            if row["state"] in ("succeeded", "failed", "cancelled", "lost"):
                return self._run(row)
            state = "cancelled" if row["state"] == "cancelling" and completion.cleanup_ok else completion.state
            if not completion.cleanup_ok:
                state = "failed"
                db.execute("UPDATE boards SET quarantined=1 WHERE id=?", (board_id,))
            db.execute("UPDATE runs SET state=?,finished=?,result=? WHERE id=?",
                       (state, time.time(), canonical(completion.result), run_id))
            return self._run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def cancel(self, batch_id):
        with self.tx() as db:
            if not db.execute("SELECT 1 FROM batches WHERE id=?", (batch_id,)).fetchone(): raise KeyError(batch_id)
            db.execute("UPDATE runs SET state='cancelled',finished=? WHERE batch_id=? AND state='queued'", (time.time(), batch_id))
            db.execute("UPDATE runs SET state='cancelling' WHERE batch_id=? AND state='running'", (batch_id,))
        return self.batch(batch_id)

    def board_action(self, board_id, action):
        with self.tx() as db:
            if not db.execute("SELECT 1 FROM boards WHERE id=?", (board_id,)).fetchone(): raise KeyError(board_id)
            if action == "reload":
                db.execute("UPDATE boards SET reload_requested=reload_requested+1 WHERE id=?", (board_id,))
            else:
                if db.execute("SELECT 1 FROM runs WHERE board_id=? AND state IN ('queued','running','cancelling')", (board_id,)).fetchone():
                    raise Conflict("Active run must be stopped before recovery")
                db.execute("UPDATE boards SET quarantined=0 WHERE id=?", (board_id,))
        return {"board_id": board_id, "action": action}
