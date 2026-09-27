"""Real local child execution with mocked resource receipts, not kernel cgroup acceptance."""
import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from side_galaxy.agent_state import AgentJournal
from side_galaxy.models import Description, Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Agent, Execution
from side_galaxy.store import Store


class ExecutionResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'module.py'
        self.source.write_text('import json,sys\njson.load(sys.stdin)\nprint(json.dumps({"cleanup_ok":True}))\n')
        self.job = {'id': str(uuid.uuid4()), 'module_sha256': 'a' * 64, 'mode': 'linux-process',
                    'cleanup_scope': 'process-group', 'process_tree_execution': True, 'memory_overhead_mib': 0,
                    'plan': Plan(boards=['alpha'], duration_seconds=1, resource_policy='cgroup').model_dump()}
        self.receipt = {'enforcement': 'cgroup-v2', 'name': 'sg-' + self.job['id'], 'inode': 42, 'process_tree_limited': True}

    def completion(self, finish_guard, job=None, journal=None):
        execution = Execution(self.source, job or self.job, journal=journal,
            spawn_guard=lambda pid, job: self.receipt.copy(), finish_guard=finish_guard)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = execution.poll()
            if result is not None: return result
            time.sleep(.01)
        execution.stop(cancelled=True)
        self.fail('Local test child did not complete')

    def test_missing_malformed_or_exceptional_cleanup_never_releases_host(self):
        guards = [None, lambda scope: None, lambda scope: [], lambda scope: {'empty': True, 'removed': False},
                  lambda scope: {'empty': 1, 'removed': 1}, Mock(side_effect=OSError('cleanup failed'))]
        for guard in guards:
            with self.subTest(guard=type(guard).__name__):
                result = self.completion(guard)
                self.assertFalse(result.cleanup_ok)
                self.assertFalse(result.result['cleanup_ok'])
                self.assertTrue(result.result['module_cleanup_ok'])
                self.assertEqual(result.state, 'failed')
                self.assertEqual(result.result['resource_scope'], self.receipt)
                self.assertIn('resource_cleanup', result.result)
        # The completion must reach the native scheduler as uncertain cleanup.
        store = Store(self.root / 'fleet.db')
        description = Description(name='resource-test', mode='linux-process', cpus=[0, 1, 2], memory_mib=1024,
            capabilities=['cpu-affinity', 'memory-limit', 'interference'], templates=['cpu-contention'], module_sha256='a' * 64)
        for board in ('alpha', 'sibling'):
            store.enroll(Enrollment(name=board), board_id=board)
            store.heartbeat(board, Heartbeat(description=description, physical_host_id='b' * 64))
        store.submit(Plan(boards=['alpha']), 'uncertain')
        claimed = store.poll('alpha')
        store.finish('alpha', claimed['id'], result)
        self.assertTrue(all(board['host_quarantined'] for board in store.boards()))

    def test_verified_scope_receipt_persists_before_start_and_reports_cleanup(self):
        journal = AgentJournal(self.root / 'journal', str(uuid.uuid4()))
        try:
            journal.claim(self.job)
            finish = Mock(return_value={'empty': True, 'removed': True, 'memory_peak_bytes': 4096})
            result = self.completion(finish, journal=journal)
            self.assertTrue(result.cleanup_ok)
            self.assertEqual(result.state, 'succeeded')
            self.assertEqual(journal.record['resource_scope'], self.receipt)
            self.assertEqual(journal.record['phase'], 'executing')
            finish.assert_called_once_with(self.receipt)
            self.assertEqual(result.result['resource_cleanup']['memory_peak_bytes'], 4096)
        finally: journal.close()

    def test_explicit_policy_without_receipt_never_opens_module_input_gate(self):
        marker = self.root / 'ran'
        self.source.write_text('import json,sys,pathlib\njson.load(sys.stdin)\npathlib.Path(' + repr(str(marker)) + ').touch()\n')
        for receipt in (None, {'enforcement': 'module', 'process_tree_limited': False}):
            with self.assertRaisesRegex(ValueError, 'placement receipt'):
                Execution(self.source, self.job, spawn_guard=lambda pid, job: receipt)
            self.assertFalse(marker.exists())
        with self.assertRaisesRegex(ValueError, 'does not declare'):
            Execution(self.source, {**self.job, 'process_tree_execution': False},
                spawn_guard=lambda pid, job: self.receipt.copy(), finish_guard=lambda scope: None)
        self.assertFalse(marker.exists())

    def test_launch_checkpoint_failure_closes_descriptors_even_when_scope_cleanup_raises(self):
        journal = AgentJournal(self.root / 'journal', str(uuid.uuid4()))
        journal.claim(self.job)
        execution = Execution.__new__(Execution)
        finish = Mock(side_effect=RuntimeError('cleanup unavailable'))
        try:
            with patch.object(journal, 'started', side_effect=OSError('checkpoint failed')):
                with self.assertRaisesRegex(OSError, 'checkpoint failed'):
                    execution.__init__(self.source, self.job, journal=journal,
                        spawn_guard=lambda pid, job: self.receipt.copy(), finish_guard=finish)
            self.assertTrue(execution.output.closed)
            self.assertIsNone(execution.event_fd)
            self.assertIsNotNone(execution.process.poll())
            finish.assert_called_once_with(self.receipt)
        finally: journal.close()

    def test_agent_overwrites_remote_resource_fields_from_pinned_description(self):
        for contained, overhead in ((False, 0), (True, 384)):
            with self.subTest(contained=contained):
                description = Description(name='trusted-module', mode='synthetic', cpus=[0, 1], memory_mib=1024,
                    capabilities=['cpu-affinity'], templates=['cpu-contention'], module_sha256='a' * 64,
                    process_tree_execution=contained, memory_overhead_mib=overhead)
                modules = SimpleNamespace(root=self.root / str(uuid.uuid4()), current=(self.source, description),
                    reload=lambda **kwargs: None, error=None)
                remote_job = copy.deepcopy(self.job)
                remote_job.update(claimed=True, state='running', process_tree_execution=not contained, memory_overhead_mib=65536)
                remote_job['plan']['resource_policy'] = 'auto'
                client = SimpleNamespace(heartbeat=lambda *args: {'reload_requested': 0}, poll=lambda *args: remote_job)
                agent = Agent(client, str(uuid.uuid4()), modules)
                try:
                    with patch.object(agent, '_launch') as launch:
                        agent.tick()
                        job = launch.call_args.args[1]
                        self.assertEqual(job['process_tree_execution'], contained)
                        self.assertEqual(job['memory_overhead_mib'], overhead)
                        self.assertEqual(job['module_sha256'], description.module_sha256)
                finally: agent.shutdown()


if __name__ == '__main__': unittest.main()
