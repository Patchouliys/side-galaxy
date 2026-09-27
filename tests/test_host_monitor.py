"""Trusted-module resource contracts; mocked scopes do not attest kernel enforcement."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from side_galaxy.host import HostMonitor
from side_galaxy.models import Description
from side_galaxy.modules import kvm, linux_process, qemu_environment


class HostMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.monitor = HostMonitor(self.temp.name, enabled=False)
        self.monitor.resource_root = Path(self.temp.name) / 'delegated'
        self.description = Description(name='External runtime', mode='kvm', cpus=[0, 1, 2], memory_mib=4096,
            capabilities=['cpu-affinity', 'memory-limit', 'process-tree-limits'], templates=['workload'],
            module_sha256='a' * 64)
        self.job = {'id': str(uuid.uuid4()), 'process_tree_execution': True, 'memory_overhead_mib': 384,
            'plan': {'cpus': [1], 'interference_cpus': [2], 'memory_mib': 512, 'resource_policy': 'auto',
                     'environment_sha256': 'b' * 64}}

    def test_external_vm_is_never_advertised_or_placed_as_contained(self):
        described = self.monitor.describe(self.description)
        self.assertNotIn('process-tree-limits', described.capabilities)
        self.job.pop('process_tree_execution')
        # A submitted plan cannot override the trusted local module declaration.
        self.job['plan']['process_tree_execution'] = True
        with patch('side_galaxy.host.host_call') as native:
            evidence = self.monitor.place(123, self.job)
            self.assertFalse(evidence['process_tree_limited'])
            self.assertEqual(evidence['enforcement'], 'module')
            self.job['plan']['resource_policy'] = 'cgroup'
            with self.assertRaisesRegex(ValueError, 'execution module'): self.monitor.place(123, self.job)
            native.assert_not_called()

    def test_declaration_requires_delegation_and_preserves_module_overhead(self):
        declared = self.description.model_copy(update={'process_tree_execution': True, 'memory_overhead_mib': 384})
        described = self.monitor.describe(declared)
        self.assertIn('process-tree-limits', described.capabilities)
        self.assertEqual(described.memory_overhead_mib, 384)
        self.monitor.resource_root = None
        self.assertNotIn('process-tree-limits', self.monitor.describe(declared).capabilities)
        with patch('side_galaxy.host.host_call') as native:
            self.assertFalse(self.monitor.place(123, self.job)['process_tree_limited'])
            self.job['plan']['resource_policy'] = 'cgroup'
            with self.assertRaises(ValueError): self.monitor.place(123, self.job)
            native.assert_not_called()

    def test_scope_budget_uses_pinned_module_overhead_only_for_guest_environment(self):
        receipt = {'name': 'sg-' + self.job['id'], 'inode': 42, 'enforcement': 'cgroup-v2'}
        with patch('side_galaxy.host.host_call', return_value=receipt) as native:
            evidence = self.monitor.place(123, self.job)
            self.assertEqual(native.call_args.args[1]['memory_bytes'], (512 + 384) * 1024 * 1024)
            self.assertEqual(native.call_args.args[1]['cpus'], [1, 2])
            self.assertEqual(evidence['host_overhead_mib'], 384)
            self.assertEqual(evidence['guest_memory_mib'], 512)
            self.job['plan'].pop('environment_sha256')
            evidence = self.monitor.place(123, self.job)
            self.assertEqual(native.call_args.args[1]['memory_bytes'], 512 * 1024 * 1024)
            self.assertEqual(evidence['host_overhead_mib'], 0)
            self.assertIsNone(evidence['guest_memory_mib'])

    def test_missing_budget_and_invalid_module_overhead_fail_before_placement(self):
        with patch('side_galaxy.host.host_call') as native:
            self.job['memory_overhead_mib'] = -1
            with self.assertRaises(ValueError): self.monitor.place(123, self.job)
            self.job['memory_overhead_mib'] = 384
            self.job['plan']['memory_mib'] = None
            self.assertFalse(self.monitor.place(123, self.job)['process_tree_limited'])
            self.job['plan']['resource_policy'] = 'cgroup'
            with self.assertRaises(ValueError): self.monitor.place(123, self.job)
            native.assert_not_called()

    def test_cleanup_failure_retains_uncertainty_and_scope_identity(self):
        scope = {'enforcement': 'cgroup-v2', 'name': 'sg-' + self.job['id'], 'inode': 42}
        with patch('side_galaxy.host.host_call', side_effect=ValueError('scope not verified')) as native:
            result = self.monitor.finish(scope)
            self.assertFalse(result['empty'])
            self.assertFalse(result['removed'])
            self.assertEqual(native.call_args.args[1]['inode'], 42)
        self.assertIsNone(self.monitor.finish({'enforcement': 'module'}))

    def test_builtin_module_declarations_distinguish_external_and_owned_execution(self):
        with patch.object(linux_process.platform, 'system', return_value='Linux'), \
             patch.object(linux_process.os, 'sched_setaffinity', create=True), \
             patch.object(linux_process.os, 'sched_getaffinity', return_value={0, 1}, create=True), \
             patch.object(linux_process.Path, 'read_text', return_value='MemAvailable: 2097152 kB\n'), \
             patch.object(linux_process, 'execution_environment', return_value=None):
            linux = Description(**linux_process.describe(), module_sha256='a' * 64)
        with patch.object(qemu_environment, 'architecture', return_value='aarch64'), \
             patch.object(qemu_environment, 'accelerator', return_value='tcg'), \
             patch.object(qemu_environment.shutil, 'which', return_value='/fixture/qemu'), \
             patch.object(qemu_environment.os, 'sysconf', side_effect=[4096, 1048576]):
            qemu = Description(**qemu_environment.describe(), module_sha256='a' * 64)
        with patch.object(kvm, 'domain', return_value='fixture-domain'), \
             patch.object(kvm, 'virsh', return_value='running'), \
             patch.object(kvm, 'guest_available', return_value=False), \
             patch.object(kvm.os, 'sched_getaffinity', return_value={0, 1}, create=True):
            external = Description(**kvm.describe(), module_sha256='a' * 64)
        self.assertTrue(linux.process_tree_execution)
        self.assertTrue(qemu.process_tree_execution)
        self.assertEqual(qemu.memory_overhead_mib, 256)
        self.assertFalse(external.process_tree_execution)
        self.assertNotIn('process-tree-limits', self.monitor.describe(external).capabilities)


if __name__ == '__main__': unittest.main()
