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

    def logs(self, board, run, events, truncated=False):
        return self.request('POST', f'/api/agent/{board}/runs/{run}/logs', {'events': events, 'truncated': truncated})

    def upload_environment(self, path):
        from .environments import MAX_ENVIRONMENT, validate_environment
        path = Path(path)
        if path.stat().st_size > MAX_ENVIRONMENT: raise ValueError('Environment package exceeds limit')
        validate_environment(path)
        with path.open('rb') as stream:
            response = self.http.post('/api/environments', content=iter(lambda: stream.read(1024 * 1024), b''),
                                      headers={'Content-Type': 'application/zip', 'Content-Length': str(path.stat().st_size)}, timeout=900)
        if response.is_error: raise ValueError(f'Environment upload rejected: HTTP {response.status_code}')
        return response.json()

    def fetch_environment(self, board, sha, root, cancelled=lambda: False):
        import tempfile
        from .environments import EnvironmentStore, MAX_ENVIRONMENT
        environments = EnvironmentStore(root)
        try: return environments.get(sha)
        except KeyError: pass
        deadline = time.monotonic() + 900
        fd, name = tempfile.mkstemp(prefix='.download-', dir=environments.root)
        try:
            total, checksum = 0, hashlib.sha256()
            with os.fdopen(fd, 'wb') as stream:
                with self.http.stream('GET', f'/api/agent/{board}/environments/{sha}', timeout=30) as response:
                    if response.is_error: raise ValueError('Environment download rejected')
                    for chunk in response.iter_bytes(1024 * 1024):
                        if cancelled(): raise InterruptedError("Environment download cancelled")
                        total += len(chunk)
                        if total > MAX_ENVIRONMENT or time.monotonic() > deadline:
                            raise ValueError('Environment transfer exceeded size or time limit')
                        checksum.update(chunk)
                        stream.write(chunk)
            if checksum.hexdigest() != sha: raise ValueError('Environment digest mismatch')
            if cancelled(): raise InterruptedError("Environment download cancelled")
            environments.put_file(name)
            return environments.get(sha)
        finally: Path(name).unlink(missing_ok=True)

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
