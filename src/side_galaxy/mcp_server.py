from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .client import Client
from .models import Plan


def create_mcp(allow_writes=False):
    server = FastMCP("Side Galaxy", instructions="Embedded board experiments. Always preflight; synthetic results are not hardware measurements.")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def request(method, path, data=None, key=None):
        client = Client()
        try: return client.request(method, path, data, key)
        finally: client.http.close()

    @server.tool(annotations=read)
    def list_boards() -> list[dict]:
        """List board health, runtime capabilities, module generation and occupancy."""
        return request("GET", "/api/boards")

    @server.tool(annotations=read)
    def list_profiles() -> dict:
        """List modular board and system profiles."""
        return request("GET", "/api/catalog")

    @server.tool(annotations=read)
    def preflight(plan: Plan) -> dict:
        """Check all targets without allocating resources or starting experiments."""
        return request("POST", "/api/preflight", plan.model_dump())

    @server.tool(annotations=read)
    def get_batch(batch_id: str) -> dict:
        """Read states and provenance. Only succeeded represents completed execution."""
        return request("GET", "/api/batches/" + batch_id)

    if allow_writes:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
        def run_experiment(plan: Plan, idempotency_key: str) -> dict:
            """Allocate boards and start an experiment. Reuse the key for retries of the same intent."""
            return request("POST", "/api/batches", plan.model_dump(), idempotency_key)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
        def cancel_batch(batch_id: str) -> dict:
            """Request cancellation. Wait for agent cleanup acknowledgement."""
            return request("POST", f"/api/batches/{batch_id}/cancel")

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        def reload_module(board_id: str) -> dict:
            """Request validation and reload of already-deployed trusted module code at the next idle boundary."""
            return request("POST", f"/api/boards/{board_id}/reload")
    return server
