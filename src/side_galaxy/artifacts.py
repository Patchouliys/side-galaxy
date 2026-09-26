import hashlib
import os
from pathlib import Path
import tempfile

from .workload_runner import MAX_BUNDLE, validate_bundle


class Artifacts:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._metadata = {}

    @staticmethod
    def _identity(path):
        info = path.stat(follow_symlinks=False)
        return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def put(self, data):
        manifest = validate_bundle(data)
        digest = hashlib.sha256(data).hexdigest()
        target = self.root / (digest + '.zip')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        metadata = {'sha256': digest, 'size': len(data), 'manifest': manifest}
        self._metadata[digest] = (self._identity(target), metadata)
        return metadata

    def get(self, digest):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise KeyError(digest)
        path = self.root / (digest + '.zip')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BUNDLE:
                raise KeyError(digest)
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != digest:
                raise KeyError(digest)
            return path
        except OSError as exc:
            raise KeyError(digest) from exc

    def list(self):
        result = []
        for path in sorted(self.root.glob('*.zip')):
            try:
                digest = path.stem
                identity = self._identity(path)
                cached = self._metadata.get(digest)
                if cached is None or cached[0] != identity:
                    data = self.get(digest).read_bytes()
                    metadata = {'sha256': digest, 'size': len(data), 'manifest': validate_bundle(data)}
                    self._metadata[digest] = (identity, metadata)
                result.append(self._metadata[digest][1])
            except (KeyError, OSError, ValueError):
                self._metadata.pop(path.stem, None)
        return result
