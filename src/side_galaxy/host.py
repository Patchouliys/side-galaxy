"""Local native host sampling and delegated experiment resource scopes."""
import hashlib
import os
from pathlib import Path
import sys
import time

from .models import HostSample
from .native import host_call


def physical_identity():
    if sys.platform != 'linux': return None
    supplied = os.environ.get('SG_PHYSICAL_HOST_ID')
    if supplied:
        if len(supplied) != 64 or any(c not in '0123456789abcdef' for c in supplied):
            raise ValueError('SG_PHYSICAL_HOST_ID must be a lowercase SHA-256 identifier')
        return supplied
    for name in ('/etc/machine-id', '/sys/class/dmi/id/product_uuid'):
        try: value = Path(name).read_text().strip()
        except OSError: continue
        if value: return hashlib.sha256(('side-galaxy:host:' + value).encode()).hexdigest()
    return None


class HostMonitor:
    def __init__(self, state_dir, enabled=True):
        self.state_dir = Path(state_dir)
        self.identity = physical_identity() if enabled else None
        self.enabled, self.next_sample, self.latest = enabled, 0, None
        self.resource_root = None
        if enabled and sys.platform == 'linux' and os.environ.get('SG_CGROUP_DELEGATED') == '1':
            try:
                group = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::/'))
                root = Path('/sys/fs/cgroup') / group.lstrip('/')
                if root.name == 'manager': root = root.parent
                host_call('prepare', {'root': str(root)})
                self.resource_root = root
            except (OSError, ValueError, StopIteration): pass

    def sample(self):
        if time.monotonic() < self.next_sample: return self.latest
        self.next_sample = time.monotonic() + 5
        try:
            value = host_call('sample', {'disk_path': str(self.state_dir)}) if self.enabled else {'source': 'unavailable', 'sampled_at': time.time()}
            value['cgroup_available'] = self.resource_root is not None
            self.latest = HostSample.model_validate(value)
        except (OSError, ValueError):
            self.latest = HostSample(source='unavailable', sampled_at=time.time())
        return self.latest

    def describe(self, description):
        capabilities = set(description.capabilities)
        capabilities.discard('process-tree-limits')
        if self.resource_root and description.process_tree_execution: capabilities.add('process-tree-limits')
        return description.model_copy(update={'capabilities': sorted(capabilities)})

    def place(self, pid, job):
        plan = job['plan']
        # These fields are copied from the pinned administrator-installed module
        # description by Agent; the plan cannot claim containment of external VMs.
        if not self.resource_root or job.get('process_tree_execution') is not True:
            if plan.get('resource_policy') == 'cgroup': raise ValueError('Process-tree controls unavailable for this execution module')
            return {'enforcement': 'module', 'process_tree_limited': False}
        if plan.get('memory_mib') is None:
            if plan.get('resource_policy') == 'cgroup': raise ValueError('Process-tree memory budget required')
            return {'enforcement': 'module', 'process_tree_limited': False}
        overhead = job.get('memory_overhead_mib', 0) if plan.get('environment_sha256') else 0
        if type(overhead) is not int or not 0 <= overhead <= 65536:
            raise ValueError('Invalid module host memory overhead')
        memory = plan['memory_mib'] + overhead
        scope = host_call('create', {'root': str(self.resource_root), 'name': 'sg-' + job['id'], 'pid': pid,
                                    'cpus': sorted(set(plan['cpus'] + plan.get('interference_cpus', []))), 'memory_bytes': memory * 1024 * 1024})
        return {**scope, 'process_tree_limited': True, 'guest_memory_mib': plan['memory_mib'] if plan.get('environment_sha256') else None,
                'host_overhead_mib': overhead}

    def finish(self, scope):
        if scope.get('enforcement') != 'cgroup-v2': return None
        if self.resource_root is None: return {'empty': False, 'removed': False, 'error': 'Delegation unavailable'}
        try: return host_call('finish', {'root': str(self.resource_root), 'name': scope['name'], 'inode': scope['inode']})
        except (OSError, ValueError): return {'empty': False, 'removed': False, 'error': 'Resource cleanup unconfirmed'}
