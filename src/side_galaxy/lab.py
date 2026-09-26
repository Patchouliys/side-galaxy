"""Local QEMU lifecycle using private disks, SSH and identity-checked QMP."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import subprocess
import time
from urllib.parse import urlparse
import uuid

from .client import Client


GUEST_PORT = 17980
GUEST_ROOT = '/tmp/side-galaxy-lab'
EXTRACT_REQUIREMENTS = '''import sys
import tarfile
from pathlib import Path, PurePosixPath

with tarfile.open(sys.argv[1], 'r:gz') as archive:
    matches, expanded = [], 0
    for index, member in enumerate(archive):
        expanded += member.size
        if index >= 4096 or expanded > 128 * 1024 * 1024:
            raise SystemExit('Side Galaxy source archive exceeds size or entry limits')
        parts = PurePosixPath(member.name).parts
        if len(parts) == 3 and parts[0] not in ('.', '..', '/') and parts[1:] == ('deploy', 'requirements.txt'):
            matches.append(member)
    if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size <= 1024 * 1024:
        raise SystemExit('Supply a complete Side Galaxy sdist with one regular deploy/requirements.txt (max 1 MiB)')
    with archive.extractfile(matches[0]) as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) != matches[0].size:
        raise SystemExit('Side Galaxy requirements file is truncated or oversized')
    Path(sys.argv[2]).write_bytes(data)
'''
SERVICE = '''[Unit]
Description=Side Galaxy lab agent
After=network-online.target
Wants=network-online.target
[Service]
User=galaxy-agent
Group=galaxy-agent
WorkingDirectory=/var/lib/side-galaxy
ExecStart=/opt/side-galaxy/venv/bin/sg agent --config /var/lib/side-galaxy/agent.json --state-dir /var/lib/side-galaxy/modules
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/side-galaxy
[Install]
WantedBy=multi-user.target
'''


def _digest(path, algorithm='sha256'):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def _architecture(value=None):
    value = value or platform.machine().lower()
    value = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(value, value)
    if value not in ('aarch64', 'x86_64'):
        raise ValueError('Lab architecture must be aarch64 or x86_64')
    return value


def _endpoint(server):
    url = urlparse(server)
    if (url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1')
            or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('Local lab requires a loopback HTTP control server')
    return url.hostname, url.port or 80


def _tool(value, default):
    found = shutil.which(str(value or default))
    if not found:
        raise ValueError(f'Install {default} or supply its executable path')
    return str(Path(found).resolve())


class Lab:
    def __init__(self, state_dir='.data/lab'):
        path = Path(state_dir).absolute()
        if path.is_symlink():
            raise ValueError('Lab state directory must not be a symlink')
        self.root = path.resolve()
        # QMP and SSH both use Unix sockets with a short, platform-defined limit.
        if len(os.fsencode(self.root / 'ssh.sock')) >= 100:
            raise ValueError('Use a shorter lab state directory for Unix sockets')

    def _read(self):
        path = self.root / 'state.json'
        if not path.exists(): return None
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Lab state must be a private regular file')
        state = json.loads(path.read_text())
        uuid.UUID(state['instance_id'])
        return state

    def _write(self, name, data):
        path = self.root / name
        temp = path.with_name(path.name + '.new')
        fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(data if isinstance(data, str) else json.dumps(data, indent=2))
        temp.replace(path)

    @contextmanager
    def _lock(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise ValueError('Lab state directory must be private: chmod 700')
        fd = os.open(self.root / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another lab operation is in progress') from None
            yield

    def _run(self, command, *, input=None, timeout=60, check=True):
        try:
            result = subprocess.run(command, input=input, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._log(exc.stdout, exc.stderr)
            raise ValueError('Lab command timed out; inspect the private bootstrap log') from None
        # Commands and stdin may contain credentials or host paths; never print them.
        self._log(result.stdout, result.stderr)
        if check and result.returncode:
            raise ValueError(f'{Path(command[0]).name} failed; inspect the private bootstrap log')
        return result

    def _log(self, *parts):
        fd = os.open(self.root / 'bootstrap.log', os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            for part in parts:
                if isinstance(part, bytes): part = part.decode(errors='replace')
                if part: stream.write(part)

    def _qmp(self, state, command):
        """Never address a VM by PID; verify its QEMU UUID on every connection."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(3)
            conn.connect(str(self.root / 'qmp.sock'))
            stream = conn.makefile('rwb')
            with stream:
                greeting = json.loads(stream.readline(65536))
                if 'QMP' not in greeting: raise ValueError('Invalid lab QMP greeting')
                def execute(name):
                    stream.write((json.dumps({'execute': name, 'id': name}) + '\n').encode())
                    stream.flush()
                    while True:
                        line = stream.readline(65536)
                        if not line: raise ConnectionError('Lab QMP disconnected')
                        response = json.loads(line)
                        if response.get('id') != name: continue
                        if 'error' in response: raise ValueError('Lab QMP command was rejected')
                        return response.get('return', {})
                execute('qmp_capabilities')
                identity = execute('query-uuid').get('UUID')
                if identity != state['instance_id']:
                    raise ValueError('QMP identity does not match this lab; refusing VM control')
                return execute(command)

    def _running(self, state):
        try: return self._qmp(state, 'query-status').get('status')
        except (FileNotFoundError, ConnectionRefusedError): return None

    def _ssh(self, state):
        return ['ssh', '-F', '/dev/null', '-i', str(self.root / 'id_ed25519'),
                '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(self.root / 'known_hosts'),
                '-p', str(state['ssh_port'])]

    def _remote(self, state, script, timeout=60, check=True):
        return self._run(self._ssh(state) + ['galaxy@127.0.0.1', 'sudo -n /bin/sh -s'],
                         input='set -eu\n' + script, timeout=timeout, check=check)

    def _copy(self, state, sources, destination):
        args = self._ssh(state)
        args[0] = 'scp'
        args[args.index('-p')] = '-P'
        return self._run(args + [str(p) for p in sources] + ['galaxy@127.0.0.1:' + destination], timeout=180)

    def _seed(self, state):
        key = self.root / 'id_ed25519'
        if not key.exists():
            self._run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'side-galaxy-lab', '-f', str(key)])
        os.chmod(key, 0o600)
        public_key = key.with_suffix('.pub').read_text().strip()
        if not public_key.startswith('ssh-ed25519 '): raise ValueError('Invalid lab SSH public key')
        seed = self.root / 'seed'
        seed.mkdir(mode=0o700, exist_ok=True)
        user = {'users': [{'name': 'galaxy', 'shell': '/bin/bash', 'lock_passwd': True,
                           'sudo': 'ALL=(ALL) NOPASSWD:ALL', 'ssh_authorized_keys': [public_key]}],
                'ssh_pwauth': False, 'disable_root': True, 'preserve_hostname': False,
                'hostname': 'side-galaxy-lab', 'manage_etc_hosts': True}
        self._write('seed/user-data', '#cloud-config\n' + json.dumps(user))
        self._write('seed/meta-data', {'instance-id': state['instance_id'], 'local-hostname': 'side-galaxy-lab'})
        output = self.root / 'seed.iso'
        if shutil.which('cloud-localds'):
            self._run(['cloud-localds', str(output), str(seed / 'user-data'), str(seed / 'meta-data')])
        elif platform.system() == 'Darwin':
            self._run(['hdiutil', 'makehybrid', '-iso', '-joliet', '-default-volume-name', 'cidata',
                       '-o', str(output), str(seed)], timeout=60)
        else:
            program = shutil.which('genisoimage') or shutil.which('mkisofs')
            if not program: raise ValueError('Install cloud-image-utils or genisoimage for the NoCloud seed')
            self._run([program, '-output', str(output), '-volid', 'cidata', '-joliet', '-rock',
                       str(seed / 'user-data'), str(seed / 'meta-data')])
        os.chmod(output, 0o600)

    def _command(self, state, qemu, firmware=None, accel='auto'):
        arch = state['arch']
        if accel not in ('auto', 'hvf', 'kvm', 'tcg'): raise ValueError('Invalid QEMU accelerator')
        accelerators = [accel]
        if accel == 'auto':
            accelerators = ['tcg']
            if arch == _architecture():
                if platform.system() == 'Darwin': accelerators = ['hvf', 'tcg']
                elif os.access('/dev/kvm', os.R_OK | os.W_OK): accelerators = ['kvm', 'tcg']
        command = [qemu, '-name', 'side-galaxy-lab', '-uuid', state['instance_id'],
                   '-machine', 'virt' if arch == 'aarch64' else 'q35', '-cpu', 'max',
                   '-smp', str(state['cpus']), '-m', str(state['memory_mib'])]
        for accelerator in accelerators: command += ['-accel', accelerator]
        if arch == 'aarch64' and not firmware:
            base = Path(qemu).resolve().parent.parent
            candidates = [base / 'share/qemu/edk2-aarch64-code.fd', Path('/usr/share/qemu/edk2-aarch64-code.fd'),
                          Path('/usr/share/AAVMF/AAVMF_CODE.fd')]
            firmware = next((str(p) for p in candidates if p.is_file()), None)
            if not firmware: raise ValueError('Supply an ARM64 UEFI firmware with --firmware')
        if firmware:
            firmware = Path(firmware).resolve(strict=True)
            command += ['-bios', str(firmware)]
        for node, filename, driver in [('disk0', 'disk.qcow2', 'qcow2'), ('seed0', 'seed.iso', 'raw')]:
            block = {'driver': driver, 'node-name': node, 'file': {'driver': 'file', 'filename': str(self.root / filename)}}
            if node == 'seed0': block['read-only'] = True
            command += ['-blockdev', json.dumps(block), '-device', 'virtio-blk-pci,drive=' + node]
        # QEMU keyval doubles commas; disk paths above use its JSON parser.
        serial = str(self.root / 'console.log').replace(',', ',,')
        qmp = str(self.root / 'qmp.sock').replace(',', ',,')
        command += ['-nic', f'user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{state["ssh_port"]}-:22',
                    '-display', 'none', '-monitor', 'none', '-chardev', 'file,id=serial0,path=' + serial,
                    '-serial', 'chardev:serial0', '-qmp', f'unix:{qmp},server=on,wait=off',
                    '-pidfile', str(self.root / 'qemu.pid'), '-daemonize']
        return command

    def _tunnel(self, state, host, port, timeout=60):
        control = ['-S', str(self.root / 'ssh.sock')]
        options = self._ssh(state)
        active = self._run(options + control + ['-O', 'check', 'galaxy@127.0.0.1'], check=False, timeout=min(timeout, 10))
        if active.returncode == 0: return
        target = '[' + host + ']' if ':' in host else host
        self._run(options + control + ['-M', '-fN', '-o', 'ExitOnForwardFailure=yes',
                  '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
                  '-R', f'127.0.0.1:{GUEST_PORT}:{target}:{port}', 'galaxy@127.0.0.1'], timeout=timeout)

    def _install(self, state, source, source_hash, wheelhouse, timeout):
        self._remote(state, f'install -d -m 700 -o galaxy -g galaxy {GUEST_ROOT}\n')
        self._copy(state, [source], GUEST_ROOT + '/source.tar.gz')
        pip_options = ''
        if wheelhouse:
            wheels = sorted(Path(wheelhouse).resolve(strict=True).glob('*.whl'))
            if not wheels: raise ValueError('Wheelhouse must contain guest-compatible dependency wheels')
            self._remote(state, f'install -d -m 700 -o galaxy -g galaxy {GUEST_ROOT}/wheels\n')
            self._copy(state, wheels, GUEST_ROOT + '/wheels/')
            pip_options = '--no-index --find-links ' + GUEST_ROOT + '/wheels'
        script = f'''export DEBIAN_FRONTEND=noninteractive
printf '%s  %s\\n' {shlex.quote(source_hash)} {GUEST_ROOT}/source.tar.gz | sha256sum -c -
python3 - {GUEST_ROOT}/source.tar.gz {GUEST_ROOT}/requirements.txt <<'SG_REQUIREMENTS'
{EXTRACT_REQUIREMENTS}SG_REQUIREMENTS
cloud-init status --wait
apt-get update
apt-get install -y --no-install-recommends build-essential cmake libsqlite3-dev python3-venv python3-pip ca-certificates
id galaxy-agent >/dev/null 2>&1 || useradd --system --home-dir /var/lib/side-galaxy --shell /usr/sbin/nologin galaxy-agent
install -d -m 700 -o galaxy-agent -g galaxy-agent /var/lib/side-galaxy
install -d -m 755 /opt/side-galaxy
python3 -m venv /opt/side-galaxy/venv
/opt/side-galaxy/venv/bin/python -m pip install --require-hashes {pip_options} -r {GUEST_ROOT}/requirements.txt
/opt/side-galaxy/venv/bin/python -m pip install --no-deps {pip_options} {GUEST_ROOT}/source.tar.gz
/opt/side-galaxy/venv/bin/python -c 'from side_galaxy.native import library; library()'
printf '%s' {shlex.quote(source_hash)} > /opt/side-galaxy/source.sha256
'''
        self._remote(state, script, timeout=timeout)

    def up(self, *, image, image_sha512, source_archive, server='http://127.0.0.1:7980', token=None,
           qemu=None, qemu_img=None, firmware=None, arch=None, cpus=4, memory_mib=2048,
           ssh_port=22222, disk_gib=16, timeout=900, wheelhouse=None, accel='auto'):
        host, port = _endpoint(server)
        arch = _architecture(arch)
        for value, low, high, label in [(cpus, 2, 64, 'cpus'), (memory_mib, 512, 131072, 'memory'),
                                        (ssh_port, 1024, 65535, 'SSH port'), (disk_gib, 8, 1024, 'disk'),
                                        (timeout, 30, 7200, 'timeout')]:
            if type(value) is not int or not low <= value <= high: raise ValueError('Invalid lab ' + label)
        if not re.fullmatch('[a-fA-F0-9]{128}', image_sha512 or ''):
            raise ValueError('A SHA-512 image digest is required')
        image = Path(image).resolve(strict=True)
        source = Path(source_archive).resolve(strict=True)
        if _digest(image, 'sha512') != image_sha512.lower(): raise ValueError('Lab base image checksum mismatch')
        source_hash = _digest(source)
        qemu = _tool(qemu, 'qemu-system-' + arch)
        qemu_img = _tool(qemu_img, 'qemu-img')
        for command in ('ssh', 'scp', 'ssh-keygen'): _tool(None, command)
        settings = {'arch': arch, 'cpus': cpus, 'memory_mib': memory_mib, 'ssh_port': ssh_port,
                    'disk_gib': disk_gib, 'image_sha512': image_sha512.lower(), 'server': server.rstrip('/')}
        with self._lock():
            state = self._read()
            if state is not None and any(state.get(k) != v for k, v in settings.items()):
                raise ValueError('Lab settings differ from its saved disk; use a new state directory')
            if state is None:
                state = {**settings, 'instance_id': str(uuid.uuid4()), 'stage': 'preparing'}
                self._write('state.json', state)
            client = Client(server, token)
            try:
                client.request('GET', '/api/boards')
                self._prepare(state, image, qemu_img)
                command = self._command(state, qemu, firmware, accel)
                if not self._running(state):
                    self._run(command, timeout=30)
                state['stage'] = 'booting'
                self._write('state.json', state)
                deadline = time.monotonic() + timeout
                while True:
                    if not self._running(state): raise ValueError('Lab VM stopped during boot; inspect the private console log')
                    if self._run(self._ssh(state) + ['galaxy@127.0.0.1', 'true'], check=False, timeout=10).returncode == 0:
                        break
                    if time.monotonic() >= deadline: raise ValueError('Lab SSH readiness timed out; inspect the private console log')
                    time.sleep(2)
                self._tunnel(state, host, port)
                installed = self._remote(state, 'cat /opt/side-galaxy/source.sha256\n', check=False)
                if installed.stdout.strip() != source_hash:
                    if state.get('board_id'):
                        board = next((b for b in client.request('GET', '/api/boards') if b['id'] == state['board_id']), None)
                        if board and board.get('active_run'):
                            raise ValueError('Lab has an active experiment; finish or cancel it before updating the agent')
                    state['stage'] = 'installing'
                    self._write('state.json', state)
                    self._remote(state, 'systemctl stop side-galaxy-agent.service 2>/dev/null || true\n', timeout=75)
                    self._install(state, source, source_hash, wheelhouse, max(1, deadline - time.monotonic()))
                config_path = self.root / 'agent.json'
                if config_path.exists():
                    config = json.loads(config_path.read_text())
                else:
                    record = client.request('POST', '/api/boards', {'name': 'QEMU Linux ' + ('ARM64' if arch == 'aarch64' else 'x86_64'),
                                            'board_profile': 'qemu-virt', 'system_profile': 'linux-process'})
                    config = {**record, 'server': f'http://127.0.0.1:{GUEST_PORT}',
                              'board_profile': 'qemu-virt', 'system_profile': 'linux-process'}
                    self._write('agent.json', config)
                state.update(board_id=config['board_id'], source_sha256=source_hash, stage='starting-agent')
                self._write('state.json', state)
                self._write('agent.service', SERVICE)
                self._remote(state, f'install -d -m 700 -o galaxy -g galaxy {GUEST_ROOT}\n')
                self._copy(state, [config_path, self.root / 'agent.service'], GUEST_ROOT + '/')
                self._remote(state, f'''install -m 600 -o galaxy-agent -g galaxy-agent {GUEST_ROOT}/agent.json /var/lib/side-galaxy/agent.json
install -m 644 {GUEST_ROOT}/agent.service /etc/systemd/system/side-galaxy-agent.service
systemctl daemon-reload
systemctl enable --now side-galaxy-agent.service
rm -f {GUEST_ROOT}/agent.json
''')
                while time.monotonic() < deadline:
                    board = next((b for b in client.request('GET', '/api/boards') if b['id'] == config['board_id']), None)
                    if board and board.get('status') != 'offline' and (board.get('description') or {}).get('mode') == 'linux-process':
                        state['stage'] = 'ready'
                        self._write('state.json', state)
                        return self.status()
                    time.sleep(2)
                raise ValueError('Guest agent did not register before timeout; inspect the private bootstrap log')
            finally:
                client.http.close()

    def _prepare(self, state, image, qemu_img):
        disk = self.root / 'disk.qcow2'
        if not disk.exists():
            info = json.loads(self._run([qemu_img, 'info', '--output=json', str(image)]).stdout)
            if info.get('format') != 'qcow2' or info.get('backing-filename'):
                raise ValueError('Lab base image must be a standalone qcow2 image')
            pending = self.root / 'disk.pending.qcow2'
            self._run([qemu_img, 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(image), str(pending)])
            self._run([qemu_img, 'resize', str(pending), str(state['disk_gib']) + 'G'])
            pending.replace(disk)
            os.chmod(disk, 0o600)
        if not (self.root / 'seed.iso').exists(): self._seed(state)

    def status(self):
        state = self._read()
        if state is None: return {'status': 'absent'}
        running = self._running(state)
        return {'status': running or 'stopped', 'stage': state.get('stage'),
                **{k: state.get(k) for k in ('instance_id', 'board_id', 'arch', 'cpus', 'memory_mib', 'ssh_port', 'source_sha256', 'boot_id')},
                'execution_mode': 'linux-process', 'synthetic': False}

    def _boot_id(self, state, timeout=10):
        result = self._remote(state, 'cat /proc/sys/kernel/random/boot_id\n', timeout=timeout)
        try: return str(uuid.UUID(result.stdout.strip()))
        except ValueError: raise ValueError('Guest did not provide a valid boot identity') from None

    def restart(self, *, force=False, timeout=180, token=None):
        """The caller must hold the control plane's admission-maintenance gate."""
        if type(force) is not bool or type(timeout) is not int or not 30 <= timeout <= 900:
            raise ValueError('Restart requires a boolean force flag and timeout of 30–900 seconds')
        with self._lock():
            state = self._read()
            if not state or not state.get('board_id'): raise ValueError('Start and register this lab before restarting it')
            deadline = time.monotonic() + timeout
            def remaining(limit=30):
                value = deadline - time.monotonic()
                if value <= 0: raise ValueError('Lab restart timed out; guest readiness remains unconfirmed')
                return min(limit, value)
            try:
                if self._running(state) != 'running': raise ValueError('Lab restart requires a running managed VM')
                host, port = _endpoint(state['server'])
                # A live baseline is required even for forced reset. Cached boot IDs
                # cannot prove which guest incarnation owned interrupted work.
                before = self._boot_id(state, timeout=remaining(10))
                state.update(stage='restarting', boot_id=before)
                self._write('state.json', state)
                if force:
                    self._qmp(state, 'system_reset')
                else:
                    self._remote(state, 'systemctl stop side-galaxy-agent.service\n', timeout=remaining(75))
                    # SSH can disconnect after systemd accepts the reboot request.
                    self._remote(state, 'systemctl reboot --no-block\n', timeout=remaining(10), check=False)
                self._run(self._ssh(state) + ['-S', str(self.root / 'ssh.sock'), '-O', 'exit', 'galaxy@127.0.0.1'],
                          timeout=remaining(5), check=False)
                while True:
                    remaining()
                    if self._running(state) != 'running': raise ValueError('Lab VM stopped during restart')
                    try: after = self._boot_id(state, timeout=remaining(10))
                    except ValueError: after = None
                    if after and after != before: break
                    time.sleep(min(1, remaining()))
                self._tunnel(state, host, port, timeout=remaining())
                fresh_after = time.time()
                client = Client(state['server'], token)
                try:
                    while True:
                        remaining()
                        active = self._remote(state, 'systemctl is-active --quiet side-galaxy-agent.service\n',
                                              timeout=remaining(10), check=False)
                        client.http.timeout = remaining(10)
                        try: boards = client.request('GET', '/api/boards')
                        except ValueError: boards = []
                        board = next((b for b in boards if b['id'] == state['board_id']), None)
                        if (active.returncode == 0 and board and (board.get('seen') or 0) > fresh_after
                                and (board.get('description') or {}).get('mode') == 'linux-process'
                                and board.get('reload_ack', 0) >= board.get('reload_requested', 0)
                                and not board.get('reload_error')):
                            break
                        time.sleep(min(1, remaining()))
                finally: client.http.close()
                # Recheck identity before publishing completion evidence.
                if self._running(state) != 'running': raise ValueError('Lab VM stopped before restart verification')
                if self._boot_id(state, timeout=remaining(10)) != after:
                    raise ValueError('Guest boot identity changed again during restart verification')
                state.update(stage='ready', boot_id=after)
                self._write('state.json', state)
                return {**self.status(), 'force': force, 'boot_id_before': before, 'boot_id_after': after,
                        'boot_changed': True, 'agent_ready': True}
            except Exception as exc:
                state['stage'] = 'restart-failed'
                self._write('state.json', state)
                if isinstance(exc, ValueError): raise
                self._log('Lab restart failed: ' + type(exc).__name__ + '\n')
                raise ValueError('Lab restart failed; inspect the private bootstrap log') from None

    def down(self, timeout=30):
        with self._lock():
            state = self._read()
            if state is None: return {'status': 'absent'}
            running = self._running(state)  # Identity verification precedes even SSH commands.
            if running:
                try: self._remote(state, 'systemctl stop side-galaxy-agent.service\n', timeout=75, check=False)
                except ValueError: pass  # VM stop is still explicit; controller leases retain uncertainty.
                self._qmp(state, 'system_powerdown')
                deadline = time.monotonic() + timeout
                while self._running(state) and time.monotonic() < deadline: time.sleep(.5)
                if self._running(state): self._qmp(state, 'quit')
                deadline = time.monotonic() + 5
                while self._running(state) and time.monotonic() < deadline: time.sleep(.1)
                if self._running(state): raise ValueError('Lab VM did not stop')
            self._run(self._ssh(state) + ['-S', str(self.root / 'ssh.sock'), '-O', 'exit', 'galaxy@127.0.0.1'], check=False)
            state['stage'] = 'stopped'
            self._write('state.json', state)
            return self.status()
