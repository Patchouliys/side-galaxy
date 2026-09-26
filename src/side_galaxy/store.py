"""Control-plane adapter; scheduling and state transitions live in the C++ core."""
import base64
import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .artifacts import Artifacts
from .native import call, NativeError
from .workload_runner import MAX_OUTPUTS

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
        self.artifacts = Artifacts(Path(path).parent / "artifacts")
        self._call("init")

    def _call(self, operation, **payload):
        try: return call(self.path, operation, payload)
        except NativeError as exc:
            if exc.kind == "conflict": raise Conflict(str(exc)) from None
            if exc.kind == "not_found": raise KeyError(str(exc)) from None
            if exc.kind == "invalid": raise ValueError(str(exc)) from None
            raise RuntimeError(str(exc)) from None

    @contextmanager
    def tx(self):
        # Administrative queries and output bytes only; the C++ engine owns scheduling.
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

    def _plan(self, plan):
        body = plan.model_dump()
        available, requirements = True, {}
        if plan.artifact_sha256:
            try: requirements = self.artifacts.metadata(plan.artifact_sha256)['manifest'].get('requires', {})
            except (KeyError, ValueError): available = False
        return {"plan": body, "plan_sha256": digest(canonical(body)), "artifact_available": available,
                "artifact_requirements": requirements}

    def enroll(self, data, local=False, board_id=None):
        token = secrets.token_urlsafe(32)
        board_id = board_id or str(uuid.uuid4())
        self._call("enroll", data=data.model_dump(), board_id=board_id, token_hash=digest(token), local=local)
        return {"board_id": board_id, "agent_token": token}

    def agent_allowed(self, board_id, token):
        return self._call("agent_allowed", board_id=board_id, token_hash=digest(token))

    def heartbeat(self, board_id, heartbeat):
        return self._call("heartbeat", board_id=board_id, heartbeat=heartbeat.model_dump())

    def boards(self): return self._call("boards")
    def preflight(self, plan): return self._call("preflight", **self._plan(plan))

    def submit(self, plan, key):
        return self._call("submit", key=key, batch_id=str(uuid.uuid4()),
                          run_ids=[str(uuid.uuid4()) for _ in plan.boards], **self._plan(plan))

    def batch(self, batch_id): return self._call("batch", batch_id=batch_id)
    def batches(self): return self._call("batches")
    def poll(self, board_id): return self._call("poll", board_id=board_id)

    def finish(self, board_id, run_id, completion):
        return self._call("finish", board_id=board_id, run_id=run_id, completion=completion.model_dump())

    def cancel(self, batch_id): return self._call("cancel", batch_id=batch_id)
    def board_action(self, board_id, action): return self._call("board_action", board_id=board_id, action=action)

    def artifact_for_agent(self, board_id, sha):
        with self.tx() as db:
            row = db.execute("SELECT b.plan FROM runs r JOIN batches b ON b.id=r.batch_id WHERE r.board_id=? AND r.state IN ('running','cancelling')", (board_id,)).fetchone()
            if not row or json.loads(row[0]).get("artifact_sha256") != sha: raise KeyError(sha)
        return self.artifacts.get(sha)

    def output_file(self, run_id, index):
        with self.tx() as db:
            row = db.execute("SELECT result FROM runs WHERE id=?", (run_id,)).fetchone()
        try:
            if index < 0 or not row or not row[0]: raise ValueError()
            item = json.loads(row[0])["outputs"][index]
            if len(item["data_base64"]) > (MAX_OUTPUTS + 2) // 3 * 4: raise ValueError()
            content = base64.b64decode(item["data_base64"], validate=True)
            if len(content) > MAX_OUTPUTS: raise ValueError()
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]: raise ValueError()
            return item, content
        except (KeyError, ValueError, IndexError, TypeError): raise KeyError(run_id) from None
