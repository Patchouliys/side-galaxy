"""Local-only launchd/systemd user services; definitions never come from the API."""
from contextlib import contextmanager, nullcontext
import fcntl
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

KINDS = ('controller', 'tunnel')


def canonical(value):
    path = Path(value).expanduser().resolve()
    if any(ord(c) < 32 for c in str(path)): raise ValueError('Service paths cannot contain control characters')
    return path


def port(value):
    if type(value) is not int or not 1024 <= value <= 65535: raise ValueError('Service port must be between 1024 and 65535')
    return value


def atomic_private(path, content):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def private_json(path):
    try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError: return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 128 * 1024:
            raise ValueError('Service configuration must be a bounded private file')
        return json.load(stream)


def systemd_quote(value, command=False):
    value = str(value)
    if any(ord(c) < 32 for c in value): raise ValueError('Invalid service definition text')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if command: value = value.replace('$', '$$')
    return '"' + value + '"'


def render_definition(config, system, root):
    if system == 'Darwin':
        return plistlib.dumps({'Label': config['label'], 'ProgramArguments': config['argv'],
            'WorkingDirectory': config['cwd'], 'EnvironmentVariables': config['environment'],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5, 'ExitTimeOut': 60,
            'ProcessType': 'Background', 'Umask': 0o077,
            'StandardOutPath': str(root / (config['kind'] + '.stdout.log')),
            'StandardErrorPath': str(root / (config['kind'] + '.stderr.log'))})
    lines = ['[Unit]', 'Description=Side Galaxy ' + config['kind'], 'StartLimitIntervalSec=0', '',
             '[Service]', 'Type=exec', 'WorkingDirectory=' + systemd_quote(config['cwd']),
             'ExecStart=' + ' '.join(systemd_quote(item, command=True) for item in config['argv']),
             'Restart=always', 'RestartSec=5', 'TimeoutStopSec=60', 'KillMode=control-group', 'UMask=0077']
    lines.extend('Environment=' + systemd_quote(key + '=' + value) for key, value in config['environment'].items())
    lines += ['', '[Install]', 'WantedBy=default.target', '']
    return '\n'.join(lines).encode()


class ServiceManager:
    def __init__(self, state_dir='.data/services', *, system=None, home=None):
        self.root = canonical(state_dir)
        self.system = system or platform.system()
        if self.system not in ('Darwin', 'Linux'): raise ValueError('Services require macOS launchd or Linux systemd')
        self.home = canonical(home or Path.home())
        self.suffix = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]

    def label(self, kind):
        if kind not in KINDS: raise ValueError('Unknown service kind')
        return 'dev.side-galaxy.' + kind + '.' + self.suffix

    def definition_path(self, kind):
        label = self.label(kind)
        if self.system == 'Darwin': return self.home / 'Library/LaunchAgents' / (label + '.plist')
        return self.home / '.config/systemd/user' / (label + '.service')

    def _config(self, kind):
        self.label(kind)
        config = private_json(self.root / (kind + '.json'))
        if config is not None and (not isinstance(config, dict) or config.get('schema') != 1
                or config.get('kind') != kind or config.get('label') != self.label(kind)):
            raise ValueError('Invalid local service identity')
        return config

    @contextmanager
    def _lock(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077: raise ValueError('Service state directory must be private')
        fd = os.open(self.root / 'manager.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally: os.close(fd)

    def _run(self, args, check=True):
        try: result = subprocess.run(args, capture_output=True, text=True, timeout=65)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('Service manager unavailable: ' + type(exc).__name__) from None
        if check and result.returncode:
            # Manager stderr may contain private paths, configuration or SSH host identities.
            raise ValueError('Service manager operation failed; inspect local supervisor diagnostics')
        return result

    def _manager_status(self, kind):
        if self.system == 'Darwin':
            result = self._run(['launchctl', 'print', f'gui/{os.getuid()}/' + self.label(kind)], check=False)
            pid = re.search(r'^\s*pid = (\d+)\s*$', result.stdout, re.MULTILINE)
            last_exit = re.search(r'^\s*last exit code = (-?\d+)\s*$', result.stdout, re.MULTILINE)
            return {'registered': result.returncode == 0, 'running': bool(pid),
                    'pid': int(pid[1]) if pid else None, 'last_exit_code': int(last_exit[1]) if last_exit else None}
        result = self._run(['systemctl', '--user', 'show', self.label(kind) + '.service',
                            '--property=LoadState,ActiveState,MainPID,ExecMainStatus'], check=False)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        pid = int(values.get('MainPID', '0'))
        return {'registered': result.returncode == 0 and values.get('LoadState') == 'loaded',
                'running': values.get('ActiveState') == 'active' and pid > 0, 'pid': pid or None,
                'last_exit_code': int(values['ExecMainStatus']) if values.get('ExecMainStatus', '').isdigit() else None}

    @staticmethod
    def _health(config):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:' + str(config['port']) + '/healthz', timeout=1) as response:
                return json.loads(response.read(4096)).get('status') == 'ok'
        except (OSError, ValueError, AttributeError): return False

    def status(self, kind=None):
        if kind is None: return [self.status(item) for item in KINDS]
        config = self._config(kind)
        try: manager = self._manager_status(kind)
        except ValueError: manager = {'registered': False, 'running': False, 'pid': None, 'last_exit_code': None, 'manager_available': False}
        return {'kind': kind, 'manager': 'launchd' if self.system == 'Darwin' else 'systemd-user',
                'installed': config is not None and self.definition_path(kind).is_file(), **manager,
                'reachable': self._health(config) if config and kind == 'controller' else None}

    def _base(self, kind):
        return {'schema': 1, 'kind': kind, 'label': self.label(kind), 'cwd': str(canonical(Path.cwd())),
                'environment': {'PATH': os.environ.get('PATH', os.defpath), 'PYTHONUNBUFFERED': '1'}}

    def install_controller(self, db, port_number=7980, lab_dirs=None):
        db = canonical(db)
        config = self._base('controller')
        config.update(db=str(db), port=port(port_number), argv=[str(Path(sys.executable).absolute()),
            '-m', 'side_galaxy.cli', 'serve', '--host', '127.0.0.1', '--port', str(port_number), '--db', str(db)])
        for directory in lab_dirs or []:
            config['argv'].extend(['--lab-state-dir', str(canonical(directory))])
        for key in ('SG_TOKEN', 'SG_READ_TOKEN', 'SG_PROFILES_DIR'):
            if key in os.environ: config['environment'][key] = os.environ[key]
        return self._install(config)

    def install_tunnel(self, ssh_config, ssh_host, local_port=7980, remote_port=17980):
        controller = self._config('controller')
        if controller is None: raise ValueError('Install the paired controller service first')
        if port(local_port) != controller['port']:
            raise ValueError('Tunnel local port must match the paired controller port')
        path = canonical(ssh_config)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('SSH configuration must be an existing private regular file')
        if not isinstance(ssh_host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', ssh_host):
            raise ValueError('Use a configured SSH host alias')
        ssh = shutil.which('ssh')
        if not ssh: raise ValueError('OpenSSH is required for the tunnel service')
        config = self._base('tunnel')
        config.update(local_port=port(local_port), remote_port=port(remote_port), argv=[ssh, '-F', str(path), '-N', '-T',
            '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=10',
            '-o', 'ServerAliveCountMax=3', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ForwardAgent=no', '-o', 'PermitLocalCommand=no',
            '-R', f'127.0.0.1:{remote_port}:127.0.0.1:{local_port}', ssh_host])
        return self._install(config)

    def _install(self, config):
        kind = config['kind']
        with self._lock():
            previous = self._config(kind)
            if previous is not None and previous != config:
                raise ValueError('Service configuration differs; uninstall it before installing new settings')
            if previous is None and kind == 'controller':
                with socket.socket() as listener:
                    try: listener.bind(('127.0.0.1', config['port']))
                    except OSError as exc:
                        if exc.errno == errno.EADDRINUSE:
                            raise ValueError('Controller port is already occupied; stop the existing idle controller first') from None
                        raise ValueError('Cannot inspect controller port: ' + type(exc).__name__) from None
            atomic_private(self.definition_path(kind), render_definition(config, self.system, self.root))
            atomic_private(self.root / (kind + '.json'), json.dumps(config, ensure_ascii=False).encode())
            self._start(kind)
        return self.status(kind)

    def _start(self, kind):
        if self.system == 'Darwin':
            if not self._manager_status(kind)['registered']:
                self._run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(self.definition_path(kind))])
            else: self._run(['launchctl', 'kickstart', f'gui/{os.getuid()}/' + self.label(kind)])
        else:
            self._run(['systemctl', '--user', 'daemon-reload'])
            self._run(['systemctl', '--user', 'enable', '--now', self.label(kind) + '.service'])

    @contextmanager
    def _idle_guard(self, kind):
        config = self._config('controller')
        if config is None:
            if kind == 'tunnel': raise ValueError('Paired controller configuration is required to check active work')
            yield
            return
        db = Path(config['db'])
        if not db.exists():
            yield
            return
        connection = None
        try:
            connection = sqlite3.connect(db.as_uri() + '?mode=rw', uri=True, timeout=2)
            # Hold admission writers while checking and stopping; an idle snapshot alone has a race.
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                if connection.execute("SELECT 1 FROM runs WHERE state IN ('waiting','queued','running','cancelling') LIMIT 1").fetchone():
                    raise ValueError('Finish or cancel active experiments before changing services')
            yield
        except sqlite3.Error:
            raise ValueError('Cannot verify experiment inactivity; leave the service running') from None
        finally:
            if connection is not None:
                connection.rollback()
                connection.close()

    def _stop(self, kind):
        if self.system == 'Darwin':
            if self._manager_status(kind)['registered']:
                self._run(['launchctl', 'bootout', f'gui/{os.getuid()}/' + self.label(kind)])
                deadline = time.monotonic() + 65
                while self._manager_status(kind)['registered']:
                    if time.monotonic() >= deadline: raise ValueError('Supervisor has not confirmed service removal')
                    time.sleep(.05)
        else: self._run(['systemctl', '--user', 'stop', self.label(kind) + '.service'])

    def action(self, kind, action):
        if action not in ('start', 'stop', 'restart', 'uninstall'): raise ValueError('Unknown service action')
        with self._lock():
            config = self._config(kind)
            if config is None: raise ValueError('Service is not installed')
            if action == 'uninstall' and kind == 'controller' and self._config('tunnel') is not None:
                raise ValueError('Uninstall the paired tunnel before uninstalling its controller')
            with self._idle_guard(kind) if action != 'start' else nullcontext():
                if action == 'start': self._start(kind)
                elif action == 'restart':
                    self._stop(kind)
                    self._start(kind)
                elif action == 'stop': self._stop(kind)
                else:
                    self._stop(kind)
                    if self.system == 'Linux':
                        self._run(['systemctl', '--user', 'disable', self.label(kind) + '.service'])
                    self.definition_path(kind).unlink(missing_ok=True)
                    (self.root / (kind + '.json')).unlink(missing_ok=True)
                    if self.system == 'Linux': self._run(['systemctl', '--user', 'daemon-reload'])
        return self.status(kind)
