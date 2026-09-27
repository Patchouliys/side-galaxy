"""Bounded, content-addressed offline VM packages; no image downloads or installers."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

MAX_ENVIRONMENT = 2 * 1024**3
MAX_EXPANDED = 8 * 1024**3
MAX_MANIFEST = 64 * 1024
NAMES = {'rootfs.raw', 'kernel', 'initrd', 'firmware.fd'}
DIGEST = re.compile(r'^[0-9a-f]{64}$')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate manifest key')
        result[key] = value
    return result


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) - {'runtime'} != {'schema', 'name', 'architecture', 'disk', 'boot', 'files'}:
        raise ValueError('Invalid environment manifest fields')
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Unsupported environment schema')
    if not isinstance(value['name'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}', value['name']):
        raise ValueError('Invalid environment name')
    if value['architecture'] not in ('aarch64', 'x86_64'):
        raise ValueError('Unsupported environment architecture')
    if value['disk'] != {'file': 'rootfs.raw', 'format': 'raw'}:
        raise ValueError('Environment disk must be rootfs.raw in RAW format')
    boot = value['boot']
    if not isinstance(boot, dict): raise ValueError('Invalid boot configuration')
    required = {'rootfs.raw'}
    if set(boot) == {'firmware'} and boot['firmware'] == 'firmware.fd':
        required.add('firmware.fd')
    elif set(boot) in ({'kernel', 'cmdline'}, {'kernel', 'cmdline', 'initrd'}):
        if boot['kernel'] != 'kernel' or ('initrd' in boot and boot['initrd'] != 'initrd'):
            raise ValueError('Invalid boot file')
        if not isinstance(boot['cmdline'], str) or len(boot['cmdline']) > 4096 or any(c in boot['cmdline'] for c in '\x00\r\n'):
            raise ValueError('Invalid kernel command line')
        required.add('kernel')
        if 'initrd' in boot: required.add('initrd')
    else:
        raise ValueError('Choose direct kernel boot or bundled firmware')
    files = value['files']
    if not isinstance(files, dict) or set(files) != required or any(not isinstance(h, str) or not DIGEST.fullmatch(h) for h in files.values()):
        raise ValueError('Manifest must hash exactly its boot files and root disk')
    runtime = value.get('runtime')
    if 'runtime' in value:
        if not isinstance(runtime, dict) or set(runtime) - {'os', 'commands', 'commands_complete'} or runtime.get('os') != 'linux':
            raise ValueError('Invalid guest runtime contract')
        commands = runtime.get('commands', [])
        if not isinstance(commands, list) or len(commands) > 4096 or any(not isinstance(c, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}', c) for c in commands):
            raise ValueError('Invalid guest command contract')
        if type(runtime.get('commands_complete', False)) is not bool:
            raise ValueError('Invalid guest command completeness')
    return value


def _archive_manifest(archive):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if not 2 <= len(entries) <= 8 or len(set(names)) != len(names) or 'environment.json' not in names:
        raise ValueError('Invalid or duplicate environment entries')
    if set(names) - NAMES - {'environment.json'}:
        raise ValueError('Unknown environment file or unsafe path')
    if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
        raise ValueError('Environment expands beyond limit')
    for entry in entries:
        mode = entry.external_attr >> 16
        if entry.is_dir() or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)) or entry.flag_bits & 1:
            raise ValueError('Environment files must be regular and unencrypted')
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('Unsupported compression')
        if entry.file_size <= 0: raise ValueError('Empty environment file')
    if archive.getinfo('environment.json').file_size > MAX_MANIFEST:
        raise ValueError('Environment manifest exceeds limit')
    manifest = validate_manifest(json.loads(archive.read('environment.json'), object_pairs_hook=_object))
    if set(names) != set(manifest['files']) | {'environment.json'}:
        raise ValueError('Environment package and manifest differ')
    return manifest


def archive_manifest(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return _archive_manifest(archive)
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid environment package") from exc


def validate_environment(path, destination=None):
    """Hash and optionally extract every entry, never using ZipFile.extract."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ENVIRONMENT:
        raise ValueError('Invalid or oversized environment package')
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _archive_manifest(archive)
            for name, digest in manifest['files'].items():
                expected_size = archive.getinfo(name).file_size
                count, checksum = 0, hashlib.sha256()
                output = (Path(destination) / name).open('xb') if destination is not None else None
                try:
                    with archive.open(name) as stream:
                        while chunk := stream.read(1024 * 1024):
                            count += len(chunk)
                            if count > expected_size: raise ValueError('Environment entry exceeds declared size')
                            checksum.update(chunk)
                            if output: output.write(chunk)
                    if count != expected_size or checksum.hexdigest() != digest:
                        raise ValueError('Environment file integrity mismatch')
                finally:
                    if output: output.close()
            if destination is not None:
                (Path(destination) / 'environment.json').write_text(json.dumps(manifest, sort_keys=True))
            return manifest
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid environment package') from exc


class EnvironmentStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._metadata = {}

    @staticmethod
    def _identity(path):
        value = path.stat(follow_symlinks=False)
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def put_stream(self, stream):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as target:
                temporary = Path(target.name)
                checksum, size = hashlib.sha256(), 0
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ENVIRONMENT: raise ValueError('Environment package exceeds limit')
                    checksum.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            manifest = validate_environment(temporary)
            digest = checksum.hexdigest()
            temporary.chmod(0o400)
            os.replace(temporary, self.root / (digest + '.zip'))
            metadata = {'sha256': digest, 'size': size, 'manifest': manifest}
            self._metadata[digest] = (self._identity(self.root / (digest + '.zip')), metadata)
            return metadata
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)

    def put_file(self, path):
        with Path(path).open('rb') as stream:
            return self.put_stream(stream)

    def get(self, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest): raise KeyError(digest)
        path = self.root / (digest + '.zip')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ENVIRONMENT or sha256(path) != digest:
                raise KeyError(digest)
            return path
        except OSError as exc: raise KeyError(digest) from exc

    def metadata(self, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest): raise KeyError(digest)
        path = self.root / (digest + '.zip')
        try: identity = self._identity(path)
        except OSError as exc: raise KeyError(digest) from exc
        cached = self._metadata.get(digest)
        if cached is None or cached[0] != identity:
            path = self.get(digest)
            self._metadata[digest] = (identity, {'sha256': digest, 'size': path.stat().st_size, 'manifest': validate_environment(path)})
        return self._metadata[digest][1]

    def list(self):
        result = []
        for path in sorted(self.root.glob('*.zip')):
            try: result.append(self.metadata(path.stem))
            except (ValueError, KeyError, OSError): pass
        return result

    def unpack(self, digest):
        archive = self.get(digest)
        destination = self.root / digest
        if destination.exists():
            if verify_directory(destination) != archive_manifest(archive):
                raise ValueError('Cached environment manifest differs from package')
            return destination
        temporary = Path(tempfile.mkdtemp(prefix='.unpack-', dir=self.root))
        try:
            validate_environment(archive, temporary)
            for child in temporary.iterdir(): child.chmod(0o400)
            # rename publishes only a complete directory; concurrent publishers verify the winner.
            try: temporary.rename(destination)
            except OSError:
                if not destination.is_dir(): raise
                if verify_directory(destination) != archive_manifest(archive):
                    raise ValueError('Concurrent environment publication mismatch')
            return destination
        finally:
            if temporary.exists(): shutil.rmtree(temporary)


def read_manifest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir(): raise ValueError('Invalid environment directory')
    manifest_path = path / 'environment.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST:
        raise ValueError('Invalid cached manifest')
    return validate_manifest(json.loads(manifest_path.read_text(), object_pairs_hook=_object))


def verify_directory(path):
    path = Path(path)
    manifest = read_manifest(path)
    if {p.name for p in path.iterdir()} != set(manifest['files']) | {'environment.json'}:
        raise ValueError('Unexpected cached files')
    total = 0
    for name, digest in manifest['files'].items():
        entry = path / name
        if entry.is_symlink() or not entry.is_file(): raise ValueError('Invalid cached file')
        total += entry.stat().st_size
        if total > MAX_EXPANDED or sha256(entry) != digest: raise ValueError('Cached image integrity mismatch')
    return manifest


def pack_environment(source, output):
    source, output = Path(source), Path(output)
    if (source / 'environment.json').stat().st_size > MAX_MANIFEST: raise ValueError('Oversized manifest')
    manifest = json.loads((source / 'environment.json').read_text(), object_pairs_hook=_object)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('boot'), dict):
        raise ValueError('Invalid boot configuration')
    names = {'rootfs.raw'}
    boot = manifest['boot']
    for key in ('kernel', 'initrd', 'firmware'):
        if key in boot:
            if not isinstance(boot[key], str): raise ValueError('Invalid boot file')
            names.add(boot[key])
    if not names <= NAMES: raise ValueError('Unknown environment file')
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file(): raise ValueError('Environment files must be regular')
    if sum((source / name).stat().st_size for name in names) > MAX_EXPANDED:
        raise ValueError('Environment expands beyond limit')
    manifest['files'] = {name: sha256(source / name) for name in sorted(names)}
    validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.writestr('environment.json', json.dumps(manifest, sort_keys=True))
            for name in sorted(names): archive.write(source / name, name)
        validate_environment(temporary)
        if output.resolve() in {p.resolve() for p in source.iterdir()}:
            raise ValueError('Output must not overwrite a source file')
        os.replace(temporary, output)
        return {'sha256': sha256(output), 'size': output.stat().st_size, 'manifest': manifest}
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
