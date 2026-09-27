"""Control-plane adapter; scheduling and state transitions live in the C++ core."""
import base64
import hashlib
import json
import secrets
import sqlite3
import uuid
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path

from .artifacts import Artifacts
from .native import call, NativeError
from .workload_runner import MAX_OUTPUTS

ACTIVE = ("queued", "running", "cancelling")
_DATABASE_LOCKS = weakref.WeakValueDictionary()
_DATABASE_LOCKS_GUARD = threading.Lock()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        # Native and Python can load different SQLite builds. Their in-process
        # file-lock registries must not race on the same database/WAL files.
        with _DATABASE_LOCKS_GUARD:
            key = str(Path(path).resolve())
            self._lock = _DATABASE_LOCKS.setdefault(key, threading.RLock())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = Artifacts(Path(path).parent / "artifacts")
        from .environments import EnvironmentStore
        self.environments = EnvironmentStore(Path(path).parent / "environments")
        self._call("init")

    def _call(self, operation, **payload):
        try:
            with self._lock: return call(self.path, operation, payload)
        except NativeError as exc:
            if exc.kind == "conflict": raise Conflict(str(exc)) from None
            if exc.kind == "not_found": raise KeyError(str(exc)) from None
            if exc.kind == "invalid": raise ValueError(str(exc)) from None
            raise RuntimeError(str(exc)) from None

    @contextmanager
    def tx(self):
        # Administrative queries and output bytes only; the C++ engine owns scheduling.
        with self._lock:
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
        identity = body.copy()
        # An omitted optional environment and an explicit null are the same
        # legacy request; adding this field must not invalidate existing keys.
        if identity.get('environment_sha256') is None: identity.pop('environment_sha256', None)
        available, requirements = True, {}
        if plan.artifact_sha256:
            try: requirements = self.artifacts.metadata(plan.artifact_sha256)['manifest'].get('requires', {})
            except (KeyError, ValueError): available = False
        env_available, env_runtime, env_architecture = True, {}, None
        if plan.environment_sha256:
            try:
                manifest = self.environments.metadata(plan.environment_sha256)['manifest']
                env_architecture = manifest['architecture']
                env_runtime = {'architecture': env_architecture, 'os': 'linux', 'commands': [], 'commands_complete': False, **manifest.get('runtime', {})}
            except (KeyError, ValueError): env_available = False
        return {"plan": body, "plan_sha256": digest(canonical(identity)), "artifact_available": available,
                "artifact_requirements": requirements, "environment_available": env_available,
                "environment_runtime": env_runtime, "environment_architecture": env_architecture}


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
    def workspace_mode(self): return self._call("workspace_mode")
    def set_workspace_mode(self, enabled): return self._call("set_workspace_mode", enabled=enabled)
    def preflight(self, plan, enqueue=False): return self._call("preflight", enqueue=enqueue, **self._plan(plan))

    def submit(self, plan, key, enqueue=False):
        return self._call("submit", key=key, enqueue=enqueue, batch_id=str(uuid.uuid4()),
                          run_ids=[str(uuid.uuid4()) for _ in plan.boards], **self._plan(plan))

    def batch(self, batch_id): return self._call("batch", batch_id=batch_id)
    def batches(self, real_only=False): return self._call("batches", real_only=real_only)
    def poll(self, board_id): return self._call("poll", board_id=board_id)

    def finish(self, board_id, run_id, completion):
        return self._call("finish", board_id=board_id, run_id=run_id, completion=completion.model_dump())

    def cancel(self, batch_id): return self._call("cancel", batch_id=batch_id)
    def board_action(self, board_id, action, **evidence):
        if action == "restart": evidence.setdefault("restart_id", str(uuid.uuid4()))
        return self._call("board_action", board_id=board_id, action=action, **evidence)

    def artifact_for_agent(self, board_id, sha):
        with self.tx() as db:
            row = db.execute("SELECT b.plan FROM runs r JOIN batches b ON b.id=r.batch_id WHERE r.board_id=? AND r.state IN ('running','cancelling')", (board_id,)).fetchone()
            if not row or json.loads(row[0]).get("artifact_sha256") != sha: raise KeyError(sha)
        return self.artifacts.get(sha)

    def environment_for_agent(self, board_id, sha):
        with self.tx() as db:
            row = db.execute("SELECT b.plan FROM runs r JOIN batches b ON b.id=r.batch_id WHERE r.board_id=? AND r.state IN ('running','cancelling')", (board_id,)).fetchone()
            if not row or json.loads(row[0]).get('environment_sha256') != sha: raise KeyError(sha)
        return self.environments.get(sha)

    def output_file(self, run_id, index):
        with self.tx() as db:
            row = db.execute("SELECT result,state FROM runs WHERE id=?", (run_id,)).fetchone()
        try:
            if index < 0 or not row or not row[0]: raise ValueError()
            result = json.loads(row[0])
            if row['state'] == 'lost': result = result.get("late_completion", {}).get("result", result)
            item = result["outputs"][index]
            if len(item["data_base64"]) > (MAX_OUTPUTS + 2) // 3 * 4: raise ValueError()
            content = base64.b64decode(item["data_base64"], validate=True)
            if len(content) > MAX_OUTPUTS: raise ValueError()
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]: raise ValueError()
            return item, content
        except (KeyError, ValueError, IndexError, TypeError): raise KeyError(run_id) from None
