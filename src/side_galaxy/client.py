import os
import hashlib
import time
from pathlib import Path
from .artifacts import Artifacts
from .workload_runner import MAX_BUNDLE, MAX_OUTPUTS
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

    def upload_artifact(self, data):
        if len(data) > MAX_BUNDLE: raise ValueError("Artifact exceeds 16 MiB")
        response = self.http.post("/api/artifacts", content=data, headers={"Content-Type": "application/zip"}, timeout=60)
        if response.is_error: raise ValueError(f"Artifact upload rejected: HTTP {response.status_code}")
        return response.json()

    def fetch_artifact(self, board, sha, root):
        artifacts = Artifacts(root)
        try: return artifacts.get(sha)
        except KeyError: pass
        data = bytearray()
        deadline = time.monotonic() + 90
        with self.http.stream("GET", f"/api/agent/{board}/artifacts/{sha}", timeout=30) as response:
            if response.is_error: raise ValueError("Artifact download rejected")
            for chunk in response.iter_bytes(65536):
                if time.monotonic() > deadline: raise ValueError("Artifact download deadline exceeded")
                data.extend(chunk)
                if len(data) > MAX_BUNDLE: raise ValueError("Artifact exceeds size limit")
        if hashlib.sha256(data).hexdigest() != sha: raise ValueError("Artifact digest mismatch")
        artifacts.put(bytes(data))
        return artifacts.get(sha)

    def download_output(self, run, index):
        data = bytearray()
        with self.http.stream("GET", f"/api/runs/{run}/outputs/{index}") as response:
            if response.is_error: raise ValueError(f"Output unavailable: HTTP {response.status_code}")
            for chunk in response.iter_bytes(65536):
                data.extend(chunk)
                if len(data) > MAX_OUTPUTS: raise ValueError("Output exceeds size limit")
            expected = response.headers.get("X-Content-SHA256")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Output digest mismatch")
        return bytes(data)
