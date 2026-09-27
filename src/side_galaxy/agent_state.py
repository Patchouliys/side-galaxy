"""Private durable claims and completion outbox; interrupted work is never replayed."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import time

from .models import Completion

MAX_STATE = 8 * 1024 * 1024


def boot_identity():
    try: return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError: return None


def process_identity(pid):
    """Linux start ticks disambiguate PID reuse; unavailable evidence fails closed."""
    try:
        value = Path('/proc', str(pid), 'stat').read_text()
    except FileNotFoundError:
        return None
    fields = value[value.rfind(')') + 2:].split()
    return {'pid': int(pid), 'start_ticks': int(fields[19]), 'pgid': int(fields[2]),
            'sid': int(fields[3]), 'boot_id': boot_identity()}


def group_members(pgid):
    result = []
    for item in Path('/proc').iterdir():
        if not item.name.isdecimal(): continue
        identity = process_identity(int(item.name))
        if identity is not None and identity['pgid'] == pgid: result.append(identity)
    return result


def _signal_identity(identity, signum):
    fd = os.pidfd_open(identity['pid'])
    try:
        if process_identity(identity['pid']) != identity:
            raise ValueError('Process identity changed')
        signal.pidfd_send_signal(fd, signum)
    finally: os.close(fd)


def recover_group(identity):
    evidence = {'process_identity_verified': False, 'module_group_gone': False}
    current_boot = boot_identity()
    if not identity or not identity.get('boot_id') or not current_boot: return evidence
    if current_boot != identity['boot_id']:
        return {**evidence, 'host_reboot_confirmed': True, 'module_group_gone': True}
    pid = identity['pid']
    if identity.get('pgid') != pid or identity.get('sid') != pid: return evidence
    try:
        current = process_identity(pid)
        members = group_members(pid)
        if current is None:
            # An absent leader with remaining members cannot prove ownership after PID reuse.
            evidence['module_group_gone'] = not members
            return evidence
        if current != identity: return {**evidence, 'process_identity_mismatch': True}
        evidence['process_identity_verified'] = True
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'): return evidence
        # Freeze the verified leader while selecting members, so a reused process group is never signalled.
        _signal_identity(identity, signal.SIGSTOP)
        evidence['leader_frozen'] = True
        for member in group_members(pid):
            if member['pid'] == pid: continue
            if member['sid'] != pid or member['start_ticks'] < identity['start_ticks']:
                return {**evidence, 'group_identity_mismatch': True}
            try: _signal_identity(member, signal.SIGKILL)
            except ProcessLookupError: pass
        _signal_identity(identity, signal.SIGKILL)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not group_members(pid):
                evidence['module_group_gone'] = True
                break
            time.sleep(.02)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        evidence['recovery_error'] = type(exc).__name__
    return evidence


class AgentJournal:
    def __init__(self, state_root, board_id):
        self.board_id = board_id
        digest = hashlib.sha256(board_id.encode()).hexdigest()
        lock_root = Path('/tmp') / ('side-galaxy-agent-locks-' + str(os.getuid()))
        lock_root.mkdir(mode=0o700, exist_ok=True)
        info = lock_root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Agent lock directory must be private and owned by the agent')
        self.lock_fd = os.open(lock_root / (digest + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            lock_info = os.fstat(self.lock_fd)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or lock_info.st_mode & 0o077:
                raise ValueError('Agent lock must be a private regular file')
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.root = Path(state_root) / 'recovery' / digest
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Agent recovery directory must be private')
            self.path = self.root / 'claim.json'
            self.record = self._read()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def _read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError: return None
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_STATE:
                raise ValueError('Agent claim must be a bounded private file')
            value = json.load(stream)
        if not isinstance(value, dict) or value.get('schema') != 1 or value.get('board_id') != self.board_id:
            raise ValueError('Invalid agent claim identity')
        if value.get('phase') not in ('claimed', 'launching', 'executing', 'completion'):
            raise ValueError('Invalid agent claim phase')
        return value

    def _sync_directory(self):
        fd = os.open(self.root, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def write(self, record):
        data = json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
        if len(data) > MAX_STATE: raise ValueError('Agent claim exceeds storage limit')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self._sync_directory()
            self.record = record
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)

    def claim(self, job):
        if self.record is not None: raise ValueError('Unacknowledged agent claim exists')
        self.write({'schema': 1, 'board_id': self.board_id, 'phase': 'claimed', 'run_id': job['id'],
                    'module_sha256': job['module_sha256'], 'mode': job.get('mode', 'unknown'),
                    'template': job['plan']['template'], 'cleanup_scope': job.get('cleanup_scope', 'external'),
                    'request_hash': hashlib.sha256(json.dumps(job['plan'], sort_keys=True).encode()).hexdigest()})

    def launching(self):
        self.write({**self.record, 'phase': 'launching'})

    def started(self, pid, resource_scope=None):
        identity = process_identity(pid) if Path('/proc').is_dir() else None
        self.write({**self.record, 'phase': 'executing', 'process': identity, 'resource_scope': resource_scope})

    def complete(self, run_id, completion):
        record = self.record or {'schema': 1, 'board_id': self.board_id, 'run_id': run_id}
        if record['run_id'] != run_id: raise ValueError('Completion does not match persisted claim')
        self.write({**record, 'phase': 'completion', 'completion': completion.model_dump()})

    def acknowledge(self):
        if self.record and self.record.get('completion', {}).get('cleanup_ok') is False:
            # Delivery acknowledgement is not cleanup confirmation. Keep the uncertain evidence for operators.
            self.write({**self.record, 'acknowledged_at': time.time()})
            digest = hashlib.sha256(self.record['run_id'].encode()).hexdigest()
            os.replace(self.path, self.root / ('uncertain-' + digest + '.json'))
        else:
            self.path.unlink(missing_ok=True)
        self._sync_directory()
        self.record = None

    def reconcile(self, recover_scope=None):
        record = self.record
        if record is None: return None
        if record['phase'] == 'completion':
            return record['run_id'], Completion.model_validate(record['completion'])
        evidence = {'error': 'Agent restarted during an unfinished claim', 'agent_restarted': True,
                    'previous_phase': record['phase'], 'request_hash': record.get('request_hash'),
                    'mode': record.get('mode', 'unknown'), 'synthetic': record.get('mode') == 'synthetic',
                    'live_logs_interrupted': True}
        clean = record['phase'] == 'claimed'
        if clean: evidence['code_executed'] = False
        elif recover_scope is not None and record.get('resource_scope'):
            try:
                evidence.update(recover_scope(record))
                clean = evidence.get('cleanup_ok') is True
            except Exception as exc:
                evidence['recovery_error'] = type(exc).__name__
                clean = False
        elif record.get('cleanup_scope') == 'process-group' and record.get('template') != 'workload':
            evidence.update(recover_group(record.get('process')))
            clean = evidence.get('module_group_gone') is True
        evidence['cleanup_ok'] = clean
        evidence['recovery_required'] = not clean
        completion = Completion(state='failed', result=evidence, module_sha256=record['module_sha256'], cleanup_ok=clean)
        self.complete(record['run_id'], completion)
        return record['run_id'], completion
