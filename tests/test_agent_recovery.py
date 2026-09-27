"""Crash/restart protocol tests; mocked process identities are not hardware evidence."""
import json
import os
from pathlib import Path
import tempfile
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from side_galaxy.agent_state import AgentJournal, recover_group
from side_galaxy.models import Completion, Description
from side_galaxy.runtime import Agent, Execution


class Client:
    def __init__(self):
        self.finished, self.polls, self.fail = [], 0, False

    def heartbeat(self, board, data): return {'reload_requested': 0}

    def poll(self, board):
        self.polls += 1
        return None

    def finish(self, board, run, completion):
        self.finished.append((run, completion.model_dump()))
        if self.fail: raise ValueError('Acknowledgement lost')
        return {'state': completion.state}


class AgentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.board, self.run = str(uuid.uuid4()), str(uuid.uuid4())
        self.description = Description(name='recovery-test', mode='synthetic', cpus=[0, 1], memory_mib=512,
            capabilities=['cpu-affinity'], templates=['cpu-contention'], module_sha256='a' * 64,
            cleanup_scope='process-group')
        self.modules = SimpleNamespace(root=self.root, current=(self.root / 'module.py', self.description),
                                       reload=lambda **kwargs: None, error=None)
        self.job = {'id': self.run, 'module_sha256': 'a' * 64, 'mode': 'synthetic', 'cleanup_scope': 'process-group',
                    'plan': {'template': 'cpu-contention', 'duration_seconds': 1, 'environment': {'PRIVATE': 'secret'}}}

    def abandon(self, agent):
        agent.downloads.shutdown(wait=False, cancel_futures=True)
        agent.log_uploads.shutdown(wait=False, cancel_futures=True)
        agent.journal.close()

    def test_completion_ack_loss_replays_exact_outbox_without_execution(self):
        client = Client()
        agent = Agent(client, self.board, self.modules)
        completion = Completion(state='succeeded', result={'stdout': 'original result', 'cleanup_ok': True},
                                module_sha256='a' * 64)
        agent.journal.claim(self.job)
        raw = agent.journal.path.read_text()
        self.assertNotIn('secret', raw)
        agent.pending = (self.run, completion)
        client.fail = True
        with self.assertRaises(ValueError): agent.tick()
        self.assertTrue(agent.journal.path.exists())
        self.abandon(agent)
        client.fail = False
        restarted = Agent(client, self.board, self.modules)
        try:
            with patch('side_galaxy.runtime.Execution', side_effect=AssertionError('duplicate execution')):
                restarted.tick()
            self.assertEqual(client.finished[0], client.finished[1])
            self.assertEqual(client.polls, 0)
            self.assertFalse(restarted.journal.path.exists())
        finally: restarted.shutdown()

    def test_restart_during_staging_can_confirm_no_code_started(self):
        journal = AgentJournal(self.root, self.board)
        journal.claim(self.job)
        journal.close()
        client = Client()
        agent = Agent(client, self.board, self.modules)
        try:
            agent.tick()
            result = client.finished[0][1]
            self.assertEqual(result['state'], 'failed')
            self.assertTrue(result['cleanup_ok'])
            self.assertFalse(result['result']['code_executed'])
            self.assertEqual(client.polls, 0)
        finally: agent.shutdown()

    def test_failed_completion_checkpoint_retains_memory_and_blocks_delivery(self):
        client = Client()
        agent = Agent(client, self.board, self.modules)
        agent.journal.claim(self.job)
        agent.journal.launching()
        completion = Completion(state='succeeded', result={'stdout': 'preserved terminal output', 'cleanup_ok': True},
                                module_sha256='a' * 64)
        polls = []
        def terminal_poll():
            polls.append(1)
            return completion
        agent.execution = SimpleNamespace(job=self.job, stop=lambda **kwargs: None,
                                          poll=terminal_poll, logs_truncated=False)
        try:
            with patch.object(agent.journal, 'complete', side_effect=OSError('Disk unavailable')):
                agent.tick()
                self.assertIs(agent.pending[1], completion)
                self.assertIsNone(agent.execution)
                with self.assertRaises(OSError): agent.tick()
                self.assertEqual(client.finished, [])
                self.assertEqual(client.polls, 1)
                self.assertEqual(len(polls), 1)
            agent.tick()
            self.assertEqual(client.finished[0][1]['result']['stdout'], 'preserved terminal output')
            self.assertEqual(client.polls, 1)
            self.assertIsNone(agent.pending)
        finally: agent.shutdown()

    def test_external_and_workload_crashes_never_infer_cleanup_or_relaunch(self):
        for scope, template in [('external', 'workload'), ('process-group', 'workload')]:
            board = str(uuid.uuid4())
            journal = AgentJournal(self.root, board)
            journal.claim({**self.job, 'cleanup_scope': scope, 'plan': {**self.job['plan'], 'template': template}})
            journal.launching()
            journal.close()
            with patch('side_galaxy.agent_state.recover_group', side_effect=AssertionError('unsafe inference')):
                agent = Agent(Client(), board, self.modules)
            try:
                self.assertFalse(agent.pending[1].cleanup_ok)
                self.assertTrue(agent.pending[1].result['recovery_required'])
                self.assertIsNone(agent.execution)
            finally: agent.shutdown()

    def test_unsafe_completion_ack_archives_evidence_without_local_hidden_hold(self):
        agent = Agent(Client(), self.board, self.modules)
        try:
            agent.journal.claim(self.job)
            completion = Completion(state='failed', result={'recovery_required': True},
                                    module_sha256='a' * 64, cleanup_ok=False)
            agent.pending = (self.run, completion)
            agent.tick()
            self.assertIsNone(agent.pending)
            self.assertIsNone(agent.journal.record)
            archived = list(agent.journal.root.glob('uncertain-*.json'))
            self.assertEqual(len(archived), 1)
            evidence = json.loads(archived[0].read_text())
            self.assertEqual(evidence['completion'], completion.model_dump())
            self.assertIn('acknowledged_at', evidence)
        finally: agent.shutdown()

    def test_failed_identity_checkpoint_never_opens_execution_gate(self):
        marker = self.root / 'executed'
        source = self.root / 'module.py'
        source.write_text('import json,sys,pathlib\njson.load(sys.stdin)\npathlib.Path(' + repr(str(marker)) + ').write_text("ran")\n')
        journal = AgentJournal(self.root, self.board)
        journal.claim(self.job)
        try:
            with patch.object(journal, 'started', side_effect=OSError('Persistence unavailable')):
                with self.assertRaises(OSError): Execution(source, self.job, journal=journal)
            self.assertFalse(marker.exists())
            self.assertEqual(journal.record['phase'], 'launching')
        finally: journal.close()

    def test_duplicate_agent_lock_covers_different_state_directories(self):
        first = AgentJournal(self.root / 'first', self.board)
        try:
            with self.assertRaises(BlockingIOError): AgentJournal(self.root / 'second', self.board)
        finally: first.close()
        second = AgentJournal(self.root / 'second', self.board)
        second.close()

    def test_pid_reuse_and_missing_scope_evidence_do_not_signal(self):
        identity = {'pid': 42, 'pgid': 42, 'sid': 42, 'boot_id': 'old-boot', 'start_ticks': 100}
        with patch('side_galaxy.agent_state.boot_identity', return_value='old-boot'), \
                patch('side_galaxy.agent_state.process_identity', return_value={**identity, 'start_ticks': 200}), \
                patch('side_galaxy.agent_state.group_members', return_value=[]), \
                patch('side_galaxy.agent_state._signal_identity') as send:
            self.assertFalse(recover_group(identity)['module_group_gone'])
            send.assert_not_called()
        with patch('side_galaxy.agent_state.boot_identity', return_value='old-boot'), \
                patch('side_galaxy.agent_state.process_identity', return_value=None), \
                patch('side_galaxy.agent_state.group_members', return_value=[identity]), \
                patch('side_galaxy.agent_state._signal_identity') as send:
            self.assertFalse(recover_group(identity)['module_group_gone'])
            send.assert_not_called()

    def test_spawn_gate_persists_identity_before_module_receives_request(self):
        source = self.root / 'module.py'
        source.write_text('import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({"cleanup_ok":True}))\n')
        journal = AgentJournal(self.root, self.board)
        journal.claim(self.job)
        checkpoints = []
        original = journal.started
        def started(pid, scope):
            original(pid, scope)
            checkpoints.append(json.loads(journal.path.read_text())['phase'])
        with patch.object(journal, 'started', side_effect=started):
            execution = Execution(source, self.job, journal=journal)
        try:
            self.assertEqual(checkpoints, ['executing'])
            self.assertEqual(journal.record['phase'], 'executing')
            execution.process.wait(timeout=3)
            result = execution.poll()
            self.assertIsNotNone(result)
            self.assertIs(execution.poll(), result, 'Consumed terminal evidence must remain available for journal retry')
        finally:
            if execution.process.poll() is None: execution.process.kill()
            journal.close()

    @unittest.skipUnless(Path('/proc/self/stat').is_file() and hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'),
                         'Requires Linux pidfd process identity')
    def test_real_linux_scope_is_signalled_by_identity_and_reaped(self):
        from side_galaxy.agent_state import process_identity
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        reaper = threading.Thread(target=process.wait)
        reaper.start()
        try:
            identity = process_identity(process.pid)
            evidence = recover_group(identity)
            self.assertTrue(evidence['process_identity_verified'])
            self.assertTrue(evidence['module_group_gone'])
        finally:
            if process.poll() is None: process.kill()
            reaper.join(timeout=3)

    def test_invalid_private_state_fails_closed_and_releases_lock(self):
        journal = AgentJournal(self.root, self.board)
        path = journal.path
        journal.close()
        path.write_text('{"schema":1,"board_id":"wrong","phase":"claimed"}')
        path.chmod(0o600)
        with self.assertRaises(ValueError): AgentJournal(self.root, self.board)
        path.unlink()
        recovered = AgentJournal(self.root, self.board)
        recovered.close()


if __name__ == '__main__': unittest.main()
