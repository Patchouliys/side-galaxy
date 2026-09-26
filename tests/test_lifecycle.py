from concurrent.futures import Future
from pathlib import Path
import tempfile
import time
import unittest

from side_galaxy.models import Completion, Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Agent, LocalClient, Modules
from side_galaxy.store import Conflict, Store


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'fleet.db')
        self.source = self.root / 'module.py'
        self.original = Path('src/side_galaxy/modules/simulator.py').read_text()
        self.source.write_text(self.original)
        self.modules = Modules(self.root / 'modules', 'generic', 'simulator', module_file=self.source)
        self.board = self.store.enroll(Enrollment(name='lifecycle'))['board_id']
        self.store.heartbeat(self.board, Heartbeat(description=self.modules.current[1]))
        self.agent = Agent(LocalClient(self.store), self.board, self.modules)
        self.addCleanup(self.agent.shutdown)
        self.plan = Plan(boards=[self.board], duration_seconds=10)

    def drive(self, done):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.agent.tick()
            if done(): return
            time.sleep(.02)
        self.fail('Lifecycle acknowledgement timed out')

    def acknowledged(self):
        board = self.store.boards()[0]
        return board['reload_requested'] > 0 and board['reload_ack'] == board['reload_requested']

    def test_force_reload_interrupts_real_worker_and_pins_old_result_generation(self):
        batch = self.store.submit(self.plan, 'active')
        self.agent.tick()
        self.assertIsNotNone(self.agent.execution)
        old_generation = self.modules.current[1].module_sha256
        self.source.write_text(self.original + '\n# replacement\n')
        self.store.board_action(self.board, 'force-reload')
        self.assertFalse(self.store.preflight(self.plan)['valid'])
        self.drive(self.acknowledged)
        run = self.store.batch(batch['id'])['runs'][0]
        self.assertEqual(run['state'], 'cancelled')
        self.assertEqual(run['module_sha256'], old_generation)
        self.assertNotEqual(self.modules.current[1].module_sha256, old_generation)
        self.assertTrue(self.store.preflight(self.plan)['valid'])

    def test_force_reload_discards_incomplete_staging_without_starting_code(self):
        batch = self.store.submit(self.plan, 'staging')
        job = self.store.poll(self.board)
        future = Future()
        self.assertTrue(future.set_running_or_notify_cancel())
        self.agent.staging = (self.modules.current[0], job, future)
        self.store.board_action(self.board, 'force-reload')
        self.agent.tick()
        self.assertIsNone(self.agent.staging)
        self.assertIsNone(self.agent.execution)
        self.assertFalse(future.done())
        self.assertFalse(self.agent.pending[1].result['code_executed'])
        self.drive(self.acknowledged)
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'cancelled')

    def test_invalid_force_reload_reports_attempt_but_keeps_admission_closed(self):
        batch = self.store.submit(self.plan, 'invalid-module')
        self.agent.tick()
        old = self.modules.current
        self.source.write_text('invalid python !!!')
        self.store.board_action(self.board, 'force-reload')
        self.drive(self.acknowledged)
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'cancelled')
        self.assertEqual(self.modules.current, old)
        self.assertIn('validation failed', self.store.boards()[0]['reload_error'])
        self.assertFalse(self.store.preflight(self.plan)['valid'])
        self.source.write_text(self.original + '\n# repaired\n')
        self.drive(lambda: not self.store.boards()[0]['reload_error'])
        self.assertTrue(self.store.preflight(self.plan)['valid'])

    def test_graceful_reload_finishes_already_admitted_work_before_acknowledging(self):
        plan = self.plan.model_copy(update={'duration_seconds': 1})
        batch = self.store.submit(plan, 'graceful')
        self.store.board_action(self.board, 'reload')
        self.assertFalse(self.store.preflight(plan)['valid'])
        self.drive(self.acknowledged)
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'succeeded')
        self.assertTrue(self.store.preflight(plan)['valid'])

    def test_mode_disable_preserves_real_work_and_blocks_all_synthetic_classifications(self):
        real_description = self.modules.current[1].model_copy(update={'mode': 'linux-process'})
        real = self.store.enroll(Enrollment(name='real', system_profile='linux-process'))['board_id']
        local = self.store.enroll(Enrollment(name='local', system_profile='linux-process'), local=True)['board_id']
        mode = self.store.enroll(Enrollment(name='mode', system_profile='custom-runtime'))['board_id']
        for board, description in [(real, real_description), (local, real_description), (mode, self.modules.current[1])]:
            self.store.heartbeat(board, Heartbeat(description=description))
        real_plan = self.plan.model_copy(update={'boards': [real]})
        synthetic_batch = self.store.submit(self.plan, 'synthetic')
        real_batch = self.store.submit(real_plan, 'real')
        job = self.store.poll(self.board)
        self.store.set_workspace_mode(False)
        self.assertEqual(Store(self.root / 'fleet.db').workspace_mode(), {'demo': False})
        self.assertEqual(self.store.poll(self.board)['state'], 'cancelling')
        self.assertTrue(self.store.poll(real)['claimed'])
        for board in (self.board, local, mode):
            self.assertFalse(self.store.preflight(self.plan.model_copy(update={'boards': [board]}))['valid'])
        self.store.finish(self.board, job['id'], Completion(state='cancelled', result={}, module_sha256=job['module_sha256']))
        self.assertEqual(self.store.batch(synthetic_batch['id'])['runs'][0]['state'], 'cancelled')
        self.assertEqual(self.store.batch(real_batch['id'])['runs'][0]['state'], 'running')

    def test_restart_reconciles_only_its_runs_and_preserves_failed_history(self):
        description = self.modules.current[1].model_copy(update={'mode': 'linux-process', 'cleanup_scope': 'process-group'})
        self.store.heartbeat(self.board, Heartbeat(description=description))
        batch = self.store.submit(self.plan, 'reboot')
        self.store.poll(self.board)
        operation = self.store.board_action(self.board, 'restart')
        self.assertEqual(self.store.board_action(self.board, 'restart')['restart_id'], operation['restart_id'])
        with self.assertRaises(Conflict): self.store.board_action(self.board, 'recover')
        with self.store.tx() as database:
            database.execute('UPDATE boards SET seen=0 WHERE id=?', (self.board,))
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'lost')
        self.store.heartbeat(self.board, Heartbeat(description=description))
        evidence = {'restart_id': operation['restart_id'], 'instance_id': 'test-instance',
                    'boot_id_before': 'old-boot', 'boot_id_after': 'new-boot', 'agent_ready': True}
        with self.assertRaises(Conflict):
            self.store.board_action(self.board, 'restart-complete', **{**evidence, 'agent_ready': False})
        self.store.board_action(self.board, 'restart-complete', **evidence)
        run = self.store.batch(batch['id'])['runs'][0]
        self.assertEqual(run['state'], 'lost')
        self.assertIn('expired', run['result']['error'])
        self.assertTrue(run['result']['restart_cleanup']['cleanup_ok'])
        self.assertTrue(self.store.preflight(self.plan)['valid'])

    def test_restart_cannot_confirm_external_resource_cleanup(self):
        operation = self.store.board_action(self.board, 'restart')
        evidence = {'restart_id': operation['restart_id'], 'instance_id': 'test-instance',
                    'boot_id_before': 'old-boot', 'boot_id_after': 'new-boot', 'agent_ready': True}
        with self.assertRaises(Conflict): self.store.board_action(self.board, 'restart-complete', **evidence)
        self.assertEqual(self.store.boards()[0]['status'], 'maintenance')

    def test_real_history_is_filtered_before_the_recent_hundred_limit(self):
        real = self.store.enroll(Enrollment(name='real', system_profile='linux-process'))['board_id']
        description = self.modules.current[1].model_copy(update={'mode': 'linux-process'})
        self.store.heartbeat(real, Heartbeat(description=description))
        retained = []
        for key, boards in [('old-real', [real]), ('old-mixed', [real, self.board])]:
            batch = self.store.submit(self.plan.model_copy(update={'boards': boards}), key)
            retained.append(batch['id'])
            self.store.cancel(batch['id'])
        for index in range(101):
            batch = self.store.submit(self.plan, 'sample-' + str(index))
            self.store.cancel(batch['id'])
        self.assertEqual(len(self.store.batches()), 100)
        self.assertFalse(set(retained) & {batch['id'] for batch in self.store.batches()})
        self.assertEqual({batch['id'] for batch in self.store.batches(real_only=True)}, set(retained))
        self.assertEqual(len(self.store.batch(retained[1])['runs']), 2)


if __name__ == '__main__': unittest.main()
