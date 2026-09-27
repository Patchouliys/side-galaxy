import asyncio
from contextlib import asynccontextmanager
import hmac
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from urllib.parse import quote
from .workload_runner import MAX_BUNDLE
from fastapi.staticfiles import StaticFiles

from pydantic import Field
from .models import Completion, Enrollment, Heartbeat, Plan, Strict, LogChunk
from .profiles import catalog
from .store import Conflict, Store
from .workspace import Workspace

class ReplayRequest(Strict):
    boards: list[str] = Field(min_length=1, max_length=32)


class WorkspaceRequest(Strict):
    demo: bool


class RestartRequest(Strict):
    force: bool = False


STATIC = Path(__file__).with_name("static")


def create_app(db_path=".data/galaxy.db", demo=False, token=None, read_token=None, background=True,
               local_access=False, lab_dirs=None):
    if token is not None and len(token) < 24:
        raise ValueError("SG_TOKEN must contain at least 24 characters")
    if not demo and not local_access and not token:
        raise ValueError("Set SG_TOKEN (at least 24 characters) or use a local loopback workspace")
    loopback_only = local_access or demo
    anonymous_local = loopback_only and token is None
    store = Store(db_path)
    from .run_logs import RunLogs
    logs = RunLogs(store)
    from .telemetry import Telemetry
    telemetry = Telemetry(store)
    workspace = Workspace(store, demo)
    managed_dirs = [Path(p).resolve() for p in (lab_dirs if lab_dirs is not None else [Path(db_path).parent / 'lab'])]
    restart_tasks, restart_operations = {}, {}
    restart_lock = asyncio.Lock()

    def managed_labs():
        from .lab import Lab
        entries = []
        for path in managed_dirs:
            if not (path / 'state.json').is_file(): continue
            lab = Lab(path)
            state = lab.status()
            if state.get('instance_id'):
                entries.append((lab, {**state, 'operation': restart_operations.get(state['instance_id'])}))
        return entries

    @asynccontextmanager
    async def lifespan(app):
        async def worker():
            while True:
                await asyncio.to_thread(workspace.tick)
                await asyncio.sleep(.5)
        task = asyncio.create_task(worker()) if background else None
        yield
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        if restart_tasks: await asyncio.gather(*restart_tasks.values(), return_exceptions=True)
        await asyncio.to_thread(workspace.shutdown)

    app = FastAPI(title="Side Galaxy", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.telemetry = telemetry
    app.state.workspace = workspace

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        host = request.url.hostname
        if loopback_only and (host not in ("localhost", "127.0.0.1", "::1", "testserver")
                              or (request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"))):
            return JSONResponse({"detail": "Local workspace is loopback only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin access denied"}, status_code=403)
        from .environments import MAX_ENVIRONMENT
        limit = MAX_ENVIRONMENT if request.url.path == "/api/environments" else MAX_BUNDLE if request.url.path == "/api/artifacts" else 3 * 1024 * 1024 if request.url.path.endswith("/finish") else 300000
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > limit:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH") and request.url.path != "/api/environments":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                                 "Cache-Control": "no-store"})
        return response

    def bearer(value): return value[7:] if value and value.startswith("Bearer ") else ""

    def reader(authorization: str | None = Header(default=None)):
        supplied = bearer(authorization)
        if anonymous_local: return
        if not any(expected and hmac.compare_digest(supplied, expected) for expected in (token, read_token)):
            raise HTTPException(401, "Authentication required")

    def writer(authorization: str | None = Header(default=None)):
        if anonymous_local: return
        if not token or not hmac.compare_digest(bearer(authorization), token):
            raise HTTPException(403, "Operator token required")

    def board_auth(board_id: str, authorization: str | None = Header(default=None)):
        if not store.agent_allowed(board_id, bearer(authorization)):
            raise HTTPException(403, "Board-scoped token required")

    @app.exception_handler(Conflict)
    async def conflict(request, exc): return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(request, exc): return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.post("/api/artifacts", dependencies=[Depends(writer)], status_code=201)
    async def upload_artifact(request: Request):
        try: return await asyncio.to_thread(store.artifacts.put, await request.body())
        except ValueError as exc: raise HTTPException(422, str(exc)) from None

    @app.get("/api/artifacts", dependencies=[Depends(reader)])
    def artifacts(): return store.artifacts.list()

    @app.get("/api/artifacts/{sha}/download", dependencies=[Depends(reader)])
    def download_artifact(sha: str):
        return FileResponse(store.artifacts.get(sha), media_type="application/zip", filename=sha + ".zip")

    @app.get("/api/agent/{board_id}/artifacts/{sha}", dependencies=[Depends(board_auth)])
    def agent_artifact(board_id: str, sha: str):
        return FileResponse(store.artifact_for_agent(board_id, sha), media_type="application/zip")

    @app.get("/api/runs/{run_id}/outputs/{index}", dependencies=[Depends(reader)])
    def download_output(run_id: str, index: int):
        item, content = store.output_file(run_id, index)
        name = str(item.get("path", "output")).split("/")[-1]
        return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""), "X-Content-SHA256": item["sha256"]})

    @app.post('/api/environments', dependencies=[Depends(writer)], status_code=201)
    async def upload_environment(request: Request):
        from .environments import MAX_ENVIRONMENT
        fd, name = tempfile.mkstemp(prefix='.upload-', dir=store.environments.root)
        total = 0
        try:
            with os.fdopen(fd, 'wb') as stream:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_ENVIRONMENT: raise HTTPException(413, 'Environment package exceeds limit')
                    await asyncio.to_thread(stream.write, chunk)
            try: return await asyncio.to_thread(store.environments.put_file, name)
            except ValueError as exc: raise HTTPException(422, str(exc)) from None
        finally:
            Path(name).unlink(missing_ok=True)

    @app.get('/api/environments', dependencies=[Depends(reader)])
    def environments(): return store.environments.list()

    @app.get('/api/agent/{board_id}/environments/{sha}', dependencies=[Depends(board_auth)])
    def agent_environment(board_id: str, sha: str):
        return FileResponse(store.environment_for_agent(board_id, sha), media_type='application/zip')

    @app.get('/api/runs/{run_id}/logs', dependencies=[Depends(reader)])
    def run_logs(run_id: str, after: int = Query(default=0, ge=0, le=1000000)):
        return logs.read(run_id, after)

    @app.post('/api/agent/{board_id}/runs/{run_id}/logs', dependencies=[Depends(board_auth)])
    def append_logs(board_id: str, run_id: str, data: LogChunk):
        return logs.append(board_id, run_id, [event.model_dump() for event in data.events], data.truncated)

    @app.get("/healthz")
    def health(): return {"status": "ok", **store.workspace_mode(), "version": "0.1.0"}

    @app.get("/api/workspace", dependencies=[Depends(reader)])
    def workspace_status(): return {**store.workspace_mode(), 'local_access': anonymous_local}

    @app.put("/api/workspace", dependencies=[Depends(writer)])
    async def workspace_mode(data: WorkspaceRequest):
        try: mode = await asyncio.to_thread(workspace.set_demo, data.demo)
        except ValueError as exc: raise HTTPException(409, str(exc)) from None
        return {**mode, 'local_access': anonymous_local}

    @app.get('/api/labs', dependencies=[Depends(reader)])
    def labs(): return [status for _, status in managed_labs()]

    @app.post('/api/labs/{instance_id}/restart', dependencies=[Depends(writer)], status_code=202)
    async def restart_lab(instance_id: str, data: RestartRequest):
        async with restart_lock:
            if instance_id in restart_tasks and not restart_tasks[instance_id].done():
                raise HTTPException(409, 'Lab restart already in progress')
            selected = next(((lab, status) for lab, status in await asyncio.to_thread(managed_labs)
                             if status['instance_id'] == instance_id), None)
            if not selected: raise HTTPException(404, 'Managed lab not found; configure --lab-state-dir on the server')
            lab, status = selected
            if status['status'] != 'running' or not status.get('board_id'):
                raise HTTPException(409, 'Lab must be running with an enrolled board')
            gate = await asyncio.to_thread(store.board_action, status['board_id'], 'restart')
            operation = {'id': str(uuid.uuid4()), 'state': 'running'}
            restart_operations[instance_id] = operation

            async def perform():
                try:
                    evidence = await asyncio.to_thread(lab.restart, force=data.force, token=token)
                    await asyncio.to_thread(store.board_action, status['board_id'], 'restart-complete',
                                            restart_id=gate['restart_id'], instance_id=instance_id,
                                            boot_id_before=evidence['boot_id_before'], boot_id_after=evidence['boot_id_after'],
                                            agent_ready=evidence['agent_ready'])
                    operation['state'] = 'succeeded'
                except Exception as exc:
                    operation.update(state='failed', error='Restart failed; device remains protected: ' + type(exc).__name__)
            restart_tasks[instance_id] = asyncio.create_task(perform())
            return {'operation_id': operation['id'], 'state': operation['state']}

    @app.get("/api/catalog", dependencies=[Depends(reader)])
    def get_catalog(): return catalog(os.environ.get("SG_PROFILES_DIR"))

    @app.get("/api/boards", dependencies=[Depends(reader)])
    def boards(): return workspace.boards()

    @app.get('/api/boards/{board_id}/telemetry', dependencies=[Depends(reader)])
    def device_telemetry(board_id: str, limit: int = Query(default=60, ge=1, le=720)):
        return telemetry.read(board_id, limit)

    @app.post("/api/boards", dependencies=[Depends(writer)], status_code=201)
    def enroll(data: Enrollment): return store.enroll(data)

    @app.post("/api/boards/{board_id}/reload", dependencies=[Depends(writer)])
    def reload_board(board_id: str, force: bool = False):
        return store.board_action(board_id, "force-reload" if force else "reload")

    @app.post("/api/boards/{board_id}/recover", dependencies=[Depends(writer)])
    def recover(board_id: str, cleanup_confirmed: bool = False):
        if not cleanup_confirmed: raise HTTPException(422, "Confirm workload stopped and configuration restored")
        return store.board_action(board_id, "recover")

    @app.post("/api/preflight", dependencies=[Depends(reader)])
    def preflight(plan: Plan, enqueue: bool = False): return store.preflight(plan, enqueue=enqueue)

    @app.post("/api/batches", dependencies=[Depends(writer)], status_code=201)
    def submit(plan: Plan, idempotency_key: str = Header(min_length=1, max_length=128), enqueue: bool = False):
        return store.submit(plan, idempotency_key, enqueue=enqueue)

    @app.get("/api/batches", dependencies=[Depends(reader)])
    def batches(): return workspace.batches()

    @app.get("/api/batches/{batch_id}", dependencies=[Depends(reader)])
    def batch(batch_id: str): return store.batch(batch_id)

    @app.post("/api/batches/{batch_id}/replay", dependencies=[Depends(writer)], status_code=201)
    def replay(batch_id: str, data: ReplayRequest, idempotency_key: str = Header(min_length=1, max_length=128)):
        source = store.batch(batch_id)
        try: plan = Plan.model_validate({**source["plan"], "boards": data.boards})
        except ValueError: raise HTTPException(422, "Invalid replay targets") from None
        result = store.submit(plan, idempotency_key)
        if result["id"] == source["id"]:
            raise HTTPException(422, "Replay requires a new idempotency key")
        return result

    @app.post("/api/batches/{batch_id}/cancel", dependencies=[Depends(writer)])
    def cancel(batch_id: str): return store.cancel(batch_id)

    @app.post("/api/agent/{board_id}/heartbeat", dependencies=[Depends(board_auth)])
    def heartbeat(board_id: str, data: Heartbeat):
        with store._lock:
            result = store.heartbeat(board_id, data)
            telemetry.append(board_id, data.telemetry)
        return result

    @app.post("/api/agent/{board_id}/poll", dependencies=[Depends(board_auth)])
    def poll(board_id: str): return store.poll(board_id)

    @app.post("/api/agent/{board_id}/runs/{run_id}/finish", dependencies=[Depends(board_auth)])
    def finish(board_id: str, run_id: str, data: Completion): return store.finish(board_id, run_id, data)

    @app.get("/")
    def index(): return FileResponse(STATIC / "homepage.html")

    @app.get("/console")
    def console(): return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
