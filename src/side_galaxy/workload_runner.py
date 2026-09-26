"""Standalone runner for trusted experiments; directories are not a security sandbox."""
import argparse
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import selectors
import signal
import stat
import subprocess
import time
import unicodedata
import zipfile
import zlib

MAX_BUNDLE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_OUTPUTS = 512 * 1024
MAX_LOG = 64 * 1024


def relative_path(name):
    if not isinstance(name, str) or not name or len(name) > 512:
        raise ValueError('Archive and output paths must be nonempty relative paths')
    path = PurePosixPath(name)
    if ('\\' in name or ':' in name or any(ord(c) < 32 for c in name)
            or path.is_absolute() or any(p in ('', '.', '..') for p in name.rstrip('/').split('/'))
            or str(path) != name.rstrip('/')):
        raise ValueError('Archive and output paths must stay within the experiment directory')
    return path


def validate_environment(env):
    if (not isinstance(env, dict) or len(env) > 64
            or any(not isinstance(k, str) or not k or len(k) > 128 or '=' in k or '\x00' in k
                   or not isinstance(v, str) or '\x00' in v or len(v) > 4096 for k, v in env.items())):
        raise ValueError('Invalid environment')
    return env


def validate_arguments(argv, command=False):
    if (not isinstance(argv, list) or len(argv) > 64
            or any(not isinstance(s, str) or len(s) > 4096 or '\x00' in s for s in argv)
            or (command and (not argv or not argv[0]))):
        raise ValueError('Commands and arguments must be argv arrays of at most 64 strings')
    return argv


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1:
        raise ValueError('experiment.json must use schema 1')
    if set(manifest) - {'schema', 'name', 'description', 'setup', 'run', 'env', 'outputs'}:
        raise ValueError('Unknown manifest field')
    if not isinstance(manifest.get('name'), str) or not 1 <= len(manifest['name']) <= 80:
        raise ValueError('Manifest requires a name (1-80 characters)')
    if not isinstance(manifest.get('description', ''), str) or len(manifest.get('description', '')) > 2048:
        raise ValueError('description must be a string of at most 2048 characters')
    commands = manifest.get('setup', [])
    if not isinstance(commands, list) or len(commands) > 8:
        raise ValueError('setup must be an array of at most 8 argv arrays')
    for argv in commands + [manifest.get('run')]:
        validate_arguments(argv, command=True)
    validate_environment(manifest.get('env', {}))
    outputs = manifest.get('outputs', [])
    if not isinstance(outputs, list) or len(outputs) > 32:
        raise ValueError('outputs must list at most 32 relative files')
    names = set()
    for name in outputs:
        path = relative_path(name)
        key = unicodedata.normalize('NFC', str(path)).casefold()
        if name.endswith('/') or key in names:
            raise ValueError('outputs must name unique files')
        names.add(key)
    return manifest


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def validate_bundle(data):
    if len(data) > MAX_BUNDLE:
        raise ValueError('Bundle exceeds 16 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 512 or sum(m.file_size for m in members) > MAX_EXPANDED:
                raise ValueError('Bundle exceeds 512 members or 64 MiB expanded')
            names, files = {}, set()
            for member in members:
                path = relative_path(member.orig_filename)
                name = unicodedata.normalize('NFC', str(path)).casefold()
                if name in names:
                    raise ValueError('Duplicate ZIP member')
                names[name] = path
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('Only regular files and directories are allowed')
                if ((kind == stat.S_IFDIR and not member.is_dir())
                        or (kind == stat.S_IFREG and member.is_dir()) or (member.is_dir() and member.file_size)):
                    raise ValueError('Invalid ZIP directory')
                if not member.is_dir():
                    files.add(name)
                if member.flag_bits & 1:
                    raise ValueError('Encrypted archives are not supported')
                if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('Only stored or deflated ZIP members are supported')
            for path in names.values():
                if any(unicodedata.normalize('NFC', str(p)).casefold() in files for p in path.parents if str(p) != '.'):
                    raise ValueError('ZIP file conflicts with a parent directory')
            if 'experiment.json' not in archive.namelist() or archive.getinfo('experiment.json').is_dir():
                raise ValueError('Bundle must contain experiment.json at its root')
            if archive.getinfo('experiment.json').file_size > 32768:
                raise ValueError('Manifest too large')
            manifest = validate_manifest(json.loads(archive.read('experiment.json'), object_pairs_hook=_unique_object))
            # Stream every member to verify CRC and sizes without retaining expanded files.
            for member in members:
                with archive.open(member) as stream:
                    size = 0
                    while chunk := stream.read(65536):
                        size += len(chunk)
                        if size > member.file_size:
                            raise ValueError('Invalid expanded size')
                    if size != member.file_size:
                        raise ValueError('Invalid expanded size')
            return manifest
    except (zipfile.BadZipFile, UnicodeError, KeyError, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValueError('Invalid ZIP bundle or manifest') from exc


def _group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _cleanup(child):
    """Confirm the started group is gone; uncertain cleanup keeps the board reserved."""
    try:
        for sig, grace in ((signal.SIGTERM, 0.3), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                child.poll()  # Reap the direct child before checking its process group.
                if not _group_exists(child.pid):
                    return True
                time.sleep(0.02)
        return not _group_exists(child.pid)
    except OSError:
        return False


def _read_output(workspace, name, limit):
    """Open each component without symlinks, then bound reads from the same regular fd."""
    parts = relative_path(name).parts
    directory = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nested = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = nested
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError('Declared output must be a regular file with one hard link')
            if before.st_size > limit:
                raise ValueError('Declared outputs exceed 512 KiB')
            value = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(value) > limit:
                raise ValueError('Declared outputs exceed 512 KiB')
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('Declared output changed during collection')
            if len(value) != after.st_size:
                raise ValueError('Declared output changed during collection')
            return value
    finally:
        os.close(directory)


def execute(bundle, workspace, seconds, arguments=None, environment=None, artifact_sha256=None):
    result = {'exit_code': 125, 'stdout': '', 'stderr': '', 'outputs': [],
              'cleanup_ok': True, 'cleanup': [], 'steps': [], 'logs_truncated': False}
    logs = {'stdout': bytearray(), 'stderr': bytearray()}
    counts = {'stdout': 0, 'stderr': 0}
    cancelled = False

    def stop(signum, frame):
        nonlocal cancelled
        cancelled = True

    def check_deadline():
        if cancelled:
            raise InterruptedError('Experiment cancelled')
        if time.monotonic() >= deadline:
            raise TimeoutError('Experiment exceeded its total setup/run deadline')

    def drain(stream, key):
        try:
            chunk = os.read(stream.fileno(), 16384)
        except BlockingIOError:
            return True
        counts[key] += len(chunk)
        logs[key].extend(chunk[:max(0, MAX_LOG - len(logs[key]))])
        return bool(chunk)

    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 86400:
            raise ValueError('duration_seconds must be in (0, 86400]')
        arguments = validate_arguments([] if arguments is None else arguments)
        environment = validate_environment({} if environment is None else environment)
        deadline = time.monotonic() + seconds
        with Path(bundle).open('rb') as stream:
            data = stream.read(MAX_BUNDLE + 1)
        digest = hashlib.sha256(data).hexdigest()
        if artifact_sha256 is not None and artifact_sha256 != digest:
            raise ValueError('Bundle SHA-256 mismatch')
        manifest = validate_bundle(data)
        result['artifact_sha256'] = digest
        workspace = Path(workspace).absolute()
        workspace.mkdir(parents=True, exist_ok=False, mode=0o700)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                check_deadline()
                target = workspace / member.filename
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with target.open('xb') as output, archive.open(member) as source:
                        while chunk := source.read(65536):
                            output.write(chunk)
                    target.chmod(0o700 if member.external_attr >> 16 & 0o111 else 0o600)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ') if key in os.environ}
        env.update(manifest.get('env', {}))
        env.update(environment)
        env.update({'SG_WORKSPACE': str(workspace), 'PYTHONUNBUFFERED': '1'})
        commands = [('setup', argv) for argv in manifest.get('setup', [])] + [('run', manifest['run'] + arguments)]
        for phase, argv in commands:
            check_deadline()
            child = None
            with selectors.DefaultSelector() as selector:
                try:
                    child = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                    for key in logs:
                        stream = getattr(child, key)
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, key)
                    while child.poll() is None:
                        check_deadline()
                        for event, _ in selector.select(timeout=min(0.05, max(0, deadline - time.monotonic()))):
                            if not drain(event.fileobj, event.data):
                                selector.unregister(event.fileobj)
                finally:
                    if child is not None:
                        cleaned = _cleanup(child)
                        result['cleanup_ok'] &= cleaned
                        result['cleanup'].append({'phase': phase, 'process_group': child.pid, 'group_gone': cleaned})
                        # Descendants which retained pipes must not make log collection wait forever.
                        for key in logs:
                            stream = getattr(child, key)
                            for _ in range(256):
                                try:
                                    chunk = os.read(stream.fileno(), 16384)
                                except BlockingIOError:
                                    break
                                if not chunk:
                                    break
                                counts[key] += len(chunk)
                                logs[key].extend(chunk[:max(0, MAX_LOG - len(logs[key]))])
                            stream.close()
                        result['exit_code'] = child.poll()
                        result['steps'].append({'phase': phase, 'command': argv[0][:128], 'exit_code': child.returncode})
            check_deadline()
            if not result['cleanup_ok']:
                raise RuntimeError('Could not confirm experiment process group cleanup')
            if result['exit_code'] != 0:
                raise RuntimeError('Experiment command exited nonzero')
        total = 0
        for name in manifest.get('outputs', []):
            check_deadline()
            try:
                value = _read_output(workspace, name, MAX_OUTPUTS - total)
            except (OSError, ValueError) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                raise ValueError('Cannot collect declared output ' + name + ': ' + detail) from exc
            total += len(value)
            result['outputs'].append({'path': name, 'size': len(value), 'sha256': hashlib.sha256(value).hexdigest(),
                                      'data_base64': base64.b64encode(value).decode('ascii')})
    except (Exception, KeyboardInterrupt) as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
        for key in logs:
            # UTF-8 replacement characters must not expand the public log past its byte limit.
            encoded = bytes(logs[key]).decode(errors='replace').encode()
            result['logs_truncated'] |= len(encoded) > MAX_LOG
            result[key] = encoded[:MAX_LOG].decode(errors='ignore')
            result[key + '_bytes'] = counts[key]
        result['logs_truncated'] |= any(counts[key] > MAX_LOG for key in logs)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan)
        result = execute(args.bundle, args.workspace, plan['duration_seconds'], plan.get('arguments'),
                         plan.get('environment'), plan.get('artifact_sha256'))
    except Exception as exc:
        result = {'exit_code': 125, 'stdout': '', 'stderr': '', 'outputs': [], 'steps': [],
                  'error': type(exc).__name__ + ': ' + str(exc), 'cleanup_ok': False}
    print(json.dumps(result))
