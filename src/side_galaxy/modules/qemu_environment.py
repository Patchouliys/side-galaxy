"""Boot one offline guest per experiment; destroy its writable layer after exit."""
import base64
import collections
import codecs
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid


def helper(name):
    path = Path(__file__).with_suffix('.' + name + '.py')
    if not path.is_file() and Path(__file__).stem == 'qemu_environment':
        path = Path(__file__).with_name('kvm.py') if name == 'kvm' else Path(__file__).parents[1] / 'environments.py'
    spec = importlib.util.spec_from_file_location('sg_environment_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accelerator():
    system = platform.system()
    value = os.environ.get('SG_QEMU_ACCEL', 'kvm' if system == 'Linux' else 'hvf')
    if value not in ('kvm', 'hvf', 'tcg'): raise ValueError('Unsupported QEMU accelerator')
    if value == 'kvm':
        if system != 'Linux': raise ValueError('KVM requires Linux')
        import fcntl
        with open('/dev/kvm', 'rb', buffering=0) as device:
            if fcntl.ioctl(device, 0xAE00, 0) != 12: raise ValueError('Unsupported KVM API')
    elif value == 'hvf' and system != 'Darwin':
        raise ValueError('HVF requires macOS')
    return value


def architecture():
    return {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(platform.machine().lower(), platform.machine().lower())


def describe():
    arch, accel = architecture(), accelerator()
    if arch not in ('aarch64', 'x86_64'): raise ValueError('Unsupported host architecture')
    if not shutil.which('qemu-system-' + arch) or not shutil.which('qemu-img'):
        raise ValueError('Install QEMU and qemu-img before enrolling this module')
    cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else list(range(os.cpu_count() or 1))
    memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') // 1024**2
    return {'protocol': 1, 'name': 'Offline QEMU environments', 'mode': 'qemu-' + accel,
            'cpus': cpus, 'reserved_cpus': [0], 'memory_mib': max(128, memory - 512),
            'memory_limit_required': True, 'environment_required': True,
            'process_tree_execution': True, 'memory_overhead_mib': 256, 'capabilities': ['workload-bundle', 'environment-bundle', 'guest-agent', 'memory-limit'] +
            (['cpu-affinity'] if hasattr(os, 'sched_setaffinity') else []),
            'templates': ['workload'], 'execution_environment': None, 'environment_architectures': [arch], 'cleanup_scope': 'external'}


class Channel:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        try: self.socket.connect(str(path))
        except BaseException:
            self.socket.close()
            raise
        self.stream = self.socket.makefile('rb')

    def close(self):
        self.stream.close()
        self.socket.close()

    def read(self):
        line = self.stream.readline(4 * 1024 * 1024 + 1)
        if not line or len(line) > 4 * 1024 * 1024: raise RuntimeError('Invalid QEMU protocol reply')
        return json.loads(line.lstrip(b'\xff'))

    def write(self, value):
        self.socket.sendall(json.dumps(value).encode() + b'\n')

    def command(self, name, arguments=None):
        token = str(uuid.uuid4())
        self.write({'execute': name, 'arguments': arguments or {}, 'id': token})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = self.read()
            if response.get('id') != token: continue
            if 'error' in response or 'return' not in response: raise RuntimeError('QEMU command failed: ' + name)
            return response['return']
        raise TimeoutError('QEMU command response timed out')


def qga(socket_path, command, **arguments):
    channel = Channel(socket_path)
    try:
        # Discard a partial previous request; sync prevents a delayed reply being mistaken for ours.
        channel.socket.sendall(b'\xff')
        token = time.monotonic_ns()
        channel.write({'execute': 'guest-sync', 'arguments': {'id': token}})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = channel.read()
            if response.get('return') == token: break
        else: raise TimeoutError('Guest agent sync timed out')
        channel.write({'execute': command, 'arguments': arguments})
        response = channel.read()
        if 'error' in response or 'return' not in response: raise RuntimeError('Guest agent command failed: ' + command)
        return response['return']
    finally: channel.close()


class GuestEvents:
    """Tail a bounded guest event file between status polls, using one QGA client at a time."""
    def __init__(self, socket_path, path, emit):
        self.socket_path, self.path, self.emit = socket_path, path, emit
        self.offset, self.pending, self.truncated, self.seen = 0, b'', False, False

    def poll(self, drain=False):
        handle = None
        try:
            handle = qga(self.socket_path, 'guest-file-open', path=self.path, mode='rb')
            self.seen = True
            qga(self.socket_path, 'guest-file-seek', handle=handle, offset=self.offset, whence=0)
            for _ in range(65 if drain else 1):
                reply = qga(self.socket_path, 'guest-file-read', handle=handle, count=16384)
                encoded = reply.get('buf-b64', '')
                if not isinstance(encoded, str) or len(encoded) > 22000: raise ValueError('Oversized guest log reply')
                chunk = base64.b64decode(encoded, validate=True)
                if len(chunk) > 16384 or reply.get('count') != len(chunk): raise ValueError('Invalid guest log reply')
                self.offset += len(chunk)
                if self.offset > 1024 * 1024: raise ValueError('Guest event file exceeds limit')
                self.pending += chunk
                while b'\n' in self.pending:
                    line, self.pending = self.pending.split(b'\n', 1)
                    if len(line) > 4096: raise ValueError('Oversized guest event')
                    event = json.loads(line)
                    if (not isinstance(event, dict) or event.get('stream') not in ('stdout', 'stderr')
                            or not isinstance(event.get('text'), str) or len(event['text']) > 256):
                        raise ValueError('Invalid guest event')
                    self.truncated |= bool(event.get('truncated'))
                    self.emit(event)
                if len(self.pending) > 4096: raise ValueError('Oversized guest event')
                if reply.get('eof') or not chunk:
                    if drain and self.pending: self.truncated = True
                    break
        except Exception:
            # The file does not exist until the first output chunk; that is not log loss.
            if self.seen: self.truncated = True
        finally:
            if handle is not None:
                try: qga(self.socket_path, 'guest-file-close', handle=handle)
                except Exception: self.truncated = True

    def wait(self, guest, dom, pid, deadline, cancelled=lambda: False):
        while True:
            if cancelled(): raise InterruptedError('Experiment cancelled')
            if time.monotonic() >= deadline: raise TimeoutError('Guest execution timed out')
            status = guest.qga(dom, 'guest-exec-status', pid=pid)
            self.poll(drain=bool(status.get('exited')))
            if status.get('exited'): return status
            time.sleep(.15)


def stop_vm(process, qmp_path, instance):
    evidence = {'qmp_identity_verified': False, 'vm_stopped': False}
    if process.poll() is None:
        try:
            channel = Channel(qmp_path)
            try:
                greeting = channel.read()
                if 'QMP' not in greeting: raise ValueError('Missing QMP greeting')
                channel.command('qmp_capabilities')
                if channel.command('query-uuid').get('UUID') != instance: raise ValueError('QMP instance identity mismatch')
                evidence['qmp_identity_verified'] = True
                channel.command('quit')
            finally: channel.close()
        except (OSError, ValueError, RuntimeError, TimeoutError):
            pass
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    evidence['vm_stopped'] = process.poll() is not None
    evidence['qemu_exit_code'] = process.returncode
    return evidence


def command_for(manifest, base, work, plan, accel, instance):
    arch = manifest['architecture']
    command = ['qemu-system-' + arch, '-machine', 'virt' if arch == 'aarch64' else 'q35',
               '-accel', accel, '-cpu', ('max' if arch == 'aarch64' else 'qemu64') if accel == 'tcg' else 'host',
               '-m', str(plan['memory_mib']), '-smp', str(len(plan['cpus'])), '-uuid', instance,
               '-nodefaults', '-no-user-config', '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
               '-qmp', 'unix:' + str(work / 'qmp.sock') + ',server=on,wait=off',
               '-drive', 'file=' + str(work / 'overlay.qcow2') + ',format=qcow2,if=virtio,cache=none',
               '-device', 'virtio-serial-pci', '-chardev', 'socket,path=' + str(work / 'qga.sock') + ',server=on,wait=off,id=qga',
               '-device', 'virtserialport,chardev=qga,name=org.qemu.guest_agent.0', '-nic', 'none']
    boot = manifest['boot']
    if 'kernel' in boot:
        command.extend(['-kernel', str(base / 'kernel'), '-append', boot['cmdline']])
        if 'initrd' in boot: command.extend(['-initrd', str(base / 'initrd')])
    else: command.extend(['-bios', str(base / 'firmware.fd')])
    return command


def run(plan, request=None):
    request = request or {}
    desc = describe()
    if (plan['template'] != 'workload' or not plan.get('environment_sha256') or not plan.get('artifact_sha256')
            or not plan['cpus'] or not set(plan['cpus']) <= set(desc['cpus']) or 0 in plan['cpus']
            or len(set(plan['cpus'])) != len(plan['cpus']) or plan.get('interference_cpus')
            or plan.get('bandwidth_percent') is not None or type(plan.get('memory_mib')) is not int
            or not 128 <= plan['memory_mib'] <= desc['memory_mib'] or not 1 <= plan['duration_seconds'] <= 86400):
        raise ValueError('Unsupported offline environment resource plan')
    environment = helper('environments')
    source = Path(request['environment_path'])
    if not source.is_absolute(): raise ValueError('Environment path must be absolute')
    digest = plan['environment_sha256']
    cache = environment.EnvironmentStore(source.parent)
    if not isinstance(digest, str) or not environment.DIGEST.fullmatch(digest) or source.name != digest + '.zip':
        raise ValueError('Environment cache path mismatch')
    base = cache.unpack(digest)
    manifest = environment.read_manifest(base)
    if manifest['architecture'] != architecture(): raise ValueError('Guest and host architectures must match')
    instance = str(uuid.UUID(request['run_id']))
    work = Path(tempfile.mkdtemp(prefix='sg-vm-'))
    result = {'mode': desc['mode'], 'synthetic': False, 'environment_sha256': digest, 'instance_uuid': instance,
              'architecture': manifest['architecture'], 'accelerator': desc['mode'][5:], 'cleanup_ok': False,
              'writable_layer': 'fresh', 'guest_network': 'disabled', 'stage': 'environment-prepare'}
    process, cancelled, guest_events = None, False, None
    lines, buffered, console_bytes, dropped_events = collections.deque(), 0, 0, 0
    reader = None
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    def emit_event(event):
        nonlocal dropped_events
        if 'SG_EVENT_FD' not in os.environ: return
        try:
            descriptor = int(os.environ['SG_EVENT_FD'])
            line = json.dumps(event, ensure_ascii=True).encode() + b'\n'
            if len(line) > 4096: raise ValueError('Oversized event')
            os.set_blocking(descriptor, False)
            if os.write(descriptor, line) != len(line): dropped_events += 1
        except (OSError, ValueError): dropped_events += 1

    def capture():
        nonlocal buffered, console_bytes
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        pending, finished, last_flush = '', False, time.monotonic()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while not finished:
                ready = selector.select(.05)
                if ready:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    finished = not chunk
                    pending += decoder.decode(chunk, final=finished)
                    if chunk:
                        console_bytes += len(chunk)
                        lines.append(chunk)
                        buffered += len(chunk)
                        while buffered > 128 * 1024 and lines: buffered -= len(lines.popleft())
                if finished or len(pending) >= 256 or time.monotonic() - last_flush >= .05:
                    for offset in range(0, len(pending), 256):
                        emit_event({'stream': 'console', 'text': pending[offset:offset + 256]})
                    pending, last_flush = '', time.monotonic()
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        if cancelled: raise InterruptedError('Experiment cancelled')
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'raw', '-b', str(base / 'rootfs.raw'),
                        str(work / 'overlay.qcow2')], check=True, capture_output=True, timeout=15)
        result['stage'] = 'guest-boot'
        affinity = (lambda: os.sched_setaffinity(0, plan['cpus'])) if hasattr(os, 'sched_setaffinity') else None
        process = subprocess.Popen(command_for(manifest, base, work, plan, result['accelerator'], instance),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   preexec_fn=affinity)
        if hasattr(os, 'sched_getaffinity'):
            result['affinity_applied'] = sorted(os.sched_getaffinity(process.pid))
        reader = threading.Thread(target=capture, daemon=True)
        reader.start()
        guest = helper('kvm')
        # Resolve the generation-pinned runner next to the main module snapshot.
        guest.__file__ = __file__
        guest.qga = qga
        deadline = time.monotonic() + 90
        while True:
            if cancelled: raise InterruptedError('Experiment cancelled')
            if process.poll() is not None: raise RuntimeError('Guest exited before agent readiness')
            if time.monotonic() >= deadline: raise TimeoutError('Guest agent did not become ready')
            if guest.guest_available(work / 'qga.sock'): break
            time.sleep(.25)
        result['guest_ready'] = True
        result['execution_environment'] = guest.guest_environment(work / 'qga.sock')
        actual = result['execution_environment']
        contract = manifest.get('runtime', {})
        if actual.get('architecture') != manifest['architecture'] or (contract and actual.get('os') != contract['os']):
            raise ValueError('Guest runtime differs from environment contract')
        if not set(contract.get('commands', [])) <= set(actual.get('commands', [])):
            raise ValueError('Guest is missing declared environment commands')
        result['stage'] = 'guest-run'
        guest_events = GuestEvents(work / 'qga.sock', '/tmp/side-galaxy/' + instance + '/events.jsonl', emit_event)
        guest.START_RUNNER = ("import os,sys\nos.environ['SG_EVENT_FILE']=os.path.join(os.path.dirname(sys.argv[1]),'events.jsonl')\n" + guest.START_RUNNER)
        original_start, original_wait, logged_pids = guest.guest_start, guest.guest_wait, set()
        def start_logged(dom, argv):
            pid = original_start(dom, argv)
            if len(argv) > 1 and argv[1] == guest.START_RUNNER: logged_pids.add(pid)
            return pid
        guest.guest_start = start_logged
        guest.guest_wait = lambda dom, pid, deadline, cancelled=lambda: False: (
            guest_events.wait(guest, dom, pid, deadline, cancelled) if pid in logged_pids
            else original_wait(dom, pid, deadline, cancelled))
        result.update(guest.workload(work / 'qga.sock', plan, request, lambda: cancelled))
        if cancelled: result.setdefault('error', 'InterruptedError')
    except (Exception, KeyboardInterrupt) as exc:
        result['error'] = type(exc).__name__
    finally:
        stopped = process is None
        if process is not None:
            try:
                result.update(stop_vm(process, work / 'qmp.sock', instance))
                stopped = result['vm_stopped']
            except Exception as exc:
                result['cleanup_error'] = type(exc).__name__
            if reader: reader.join(timeout=1)
        result['console_log'] = b''.join(lines).decode(errors='replace')[-65536:]
        result['console_bytes'] = console_bytes
        result['console_truncated'] = console_bytes > len(result['console_log'].encode())
        result['log_events_dropped'] = dropped_events
        result['console_events_truncated'] = dropped_events > 0
        result['guest_events_truncated'] = bool(guest_events and guest_events.truncated)
        if result['guest_events_truncated'] or dropped_events:
            emit_event({'stream': 'console', 'text': '', 'truncated': True})
        result['cleanup_ok'] = False
        if stopped:
            try:
                shutil.rmtree(work)
                result['writable_layer_removed'] = True
                result['cleanup_ok'] = True
            except OSError as exc: result['cleanup_error'] = type(exc).__name__
        for sig, handler in previous.items(): signal.signal(sig, handler)
    return result


if __name__ == '__main__':
    request = json.load(sys.stdin)
    print(json.dumps(describe() if request['op'] == 'describe' else run(request['plan'], request)))
