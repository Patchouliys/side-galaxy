import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from urllib.parse import quote
from .workload_runner import MAX_BUNDLE
from fastapi.staticfiles import StaticFiles

from .models import Completion, Enrollment, Heartbeat, Plan
from .profiles import catalog
from .runtime import Agent, LocalClient, Modules
from .store import Conflict, Store

STATIC = Path(__file__).with_name("static")


def create_app(db_path=".data/galaxy.db", demo=False, token=None, read_token=None, background=True):
    if not demo and (not token or len(token) < 24):
        raise ValueError("Set SG_TOKEN (at least 24 characters) or explicitly use --demo")
    store = Store(db_path)
    agents = []
    if demo:
        existing = {b["id"] for b in store.boards()}
        for board_id, name, board in [("pi4-lab", "PI 4 · ORION", "pi4"), ("pi5-lab", "PI 5 · LYRA", "pi5"), ("pi5-edge", "PI 5 · CYGNUS", "pi5")]:
            if board_id not in existing:
                store.enroll(Enrollment(name=name.replace("·", "-"), board_profile=board), local=True, board_id=board_id)
            agent = Agent(LocalClient(store), board_id, Modules(Path(db_path).parent / "modules" / board_id, board, "simulator"))
            agents.append(agent)
            agent.tick()

    @asynccontextmanager
    async def lifespan(app):
        async def worker():
            while True:
                for agent in agents:
                    try: await asyncio.to_thread(agent.tick)
                    except Exception: pass  # Heartbeat expiry quarantines failed local workers.
                await asyncio.to_thread(store.boards)
                await asyncio.sleep(.5)
        task = asyncio.create_task(worker()) if background else None
        yield
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        for agent in agents: await asyncio.to_thread(agent.shutdown)

    app = FastAPI(title="Side Galaxy", version="0.1.0", lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        host = request.url.hostname
        if demo and host not in ("localhost", "127.0.0.1", "::1", "testserver"):
            return JSONResponse({"detail": "Demo is loopback only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin access denied"}, status_code=403)
        limit = MAX_BUNDLE if request.url.path == "/api/artifacts" else 3 * 1024 * 1024 if request.url.path.endswith("/finish") else 300000
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > limit:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH"):
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
        if demo and token is None: return
        if not any(expected and hmac.compare_digest(supplied, expected) for expected in (token, read_token)):
            raise HTTPException(401, "Authentication required")

    def writer(authorization: str | None = Header(default=None)):
        if demo and token is None: return
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

    @app.get("/healthz")
    def health(): return {"status": "ok", "demo": demo, "version": "0.1.0"}

    @app.get("/api/catalog", dependencies=[Depends(reader)])
    def get_catalog(): return catalog(os.environ.get("SG_PROFILES_DIR"))

    @app.get("/api/boards", dependencies=[Depends(reader)])
    def boards(): return store.boards()

    @app.post("/api/boards", dependencies=[Depends(writer)], status_code=201)
    def enroll(data: Enrollment): return store.enroll(data)

    @app.post("/api/boards/{board_id}/reload", dependencies=[Depends(writer)])
    def reload_board(board_id: str): return store.board_action(board_id, "reload")

    @app.post("/api/boards/{board_id}/recover", dependencies=[Depends(writer)])
    def recover(board_id: str, cleanup_confirmed: bool = False):
        if not cleanup_confirmed: raise HTTPException(422, "Confirm workload stopped and configuration restored")
        return store.board_action(board_id, "recover")

    @app.post("/api/preflight", dependencies=[Depends(reader)])
    def preflight(plan: Plan): return store.preflight(plan)

    @app.post("/api/batches", dependencies=[Depends(writer)], status_code=201)
    def submit(plan: Plan, idempotency_key: str = Header(min_length=1, max_length=128)):
        return store.submit(plan, idempotency_key)

    @app.get("/api/batches", dependencies=[Depends(reader)])
    def batches(): return store.batches()

    @app.get("/api/batches/{batch_id}", dependencies=[Depends(reader)])
    def batch(batch_id: str): return store.batch(batch_id)

    @app.post("/api/batches/{batch_id}/cancel", dependencies=[Depends(writer)])
    def cancel(batch_id: str): return store.cancel(batch_id)

    @app.post("/api/agent/{board_id}/heartbeat", dependencies=[Depends(board_auth)])
    def heartbeat(board_id: str, data: Heartbeat): return store.heartbeat(board_id, data)

    @app.post("/api/agent/{board_id}/poll", dependencies=[Depends(board_auth)])
    def poll(board_id: str): return store.poll(board_id)

    @app.post("/api/agent/{board_id}/runs/{run_id}/finish", dependencies=[Depends(board_auth)])
    def finish(board_id: str, run_id: str, data: Completion): return store.finish(board_id, run_id, data)

    @app.get("/")
    def index(): return FileResponse(STATIC / "index.html")

    @app.get("/console")
    def console(): return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
