import os
from urllib.parse import urlparse
import httpx


class Client:
    def __init__(self, server=None, token=None):
        server = server or os.environ.get("SG_SERVER", "http://127.0.0.1:7980")
        url = urlparse(server)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Server URL must not embed credentials, query or fragment")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("Remote connections require HTTPS; use a loopback SSH tunnel for HTTP")
        token = token if token is not None else os.environ.get("SG_TOKEN", "")
        self.http = httpx.Client(base_url=server.rstrip("/"), headers={"Authorization": "Bearer " + token} if token else {},
                                 timeout=10, trust_env=False)

    def request(self, method, path, data=None, key=None):
        try:
            response = self.http.request(method, path, json=data, headers={"Idempotency-Key": key} if key else {})
        except httpx.HTTPError as exc:
            raise ValueError("Control plane connection failed: " + type(exc).__name__) from None
        if response.is_error:
            try: detail = response.json().get("detail", "Request failed")
            except ValueError: detail = "Request failed"
            raise ValueError(f"HTTP {response.status_code}: {detail}")
        return response.json()

    def heartbeat(self, board, data): return self.request("POST", f"/api/agent/{board}/heartbeat", data.model_dump())
    def poll(self, board): return self.request("POST", f"/api/agent/{board}/poll")
    def finish(self, board, run, data): return self.request("POST", f"/api/agent/{board}/runs/{run}/finish", data.model_dump())
