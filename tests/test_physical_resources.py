import sqlite3
import tempfile
import unittest
from pathlib import Path

from side_galaxy.models import Completion, Description, Enrollment, Heartbeat, Plan
from side_galaxy.store import Conflict, Store


class PhysicalResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'fleet.db')
        self.description = Description(name='Physical resource test', mode='linux-process',
            cpus=[0, 1, 2, 3], reserved_cpus=[0], memory_mib=1024,
            capabilities=['cpu-affinity', 'memory-limit', 'interference', 'environment-bundle'],
            templates=['cpu-contention', 'workload'], module_sha256='a' * 64,
            environment_architectures=['aarch64'])
        for name, identity in [('alpha', 'a'), ('alias', 'a'), ('beta', 'b'), ('legacy', None)]:
            self.store.enroll(Enrollment(name=name), board_id=name)
            self.heartbeat(name, identity)

    def heartbeat(self, board, identity=None, **fields):
        return self.store.heartbeat(board, Heartbeat(description=self.description,
            physical_host_id=identity * 64 if identity else None, **fields))

    def plan(self, *boards):
        return Plan(boards=list(boards), duration_seconds=5)

    def finish(self, board, clean=True):
        job = self.store.poll(board)
        self.assertIsNotNone(job)
        return self.store.finish(board, job['id'], Completion(state='succeeded', result={},
            module_sha256=job['module_sha256'], cleanup_ok=clean))

    def board(self, identity):
        return next(b for b in self.store.boards() if b['id'] == identity)

    def test_alias_batch_rejected_atomically_and_independent_hosts_admitted(self):
        for enqueue in (False, True):
            with self.assertRaisesRegex(Conflict, 'same physical host'):
                self.store.submit(self.plan('alpha', 'alias', 'beta'), f'invalid-{enqueue}', enqueue=enqueue)
        self.assertEqual(self.store.batches(), [])
        active = self.store.submit(self.plan('alpha', 'beta', 'legacy'), 'independent')
        self.assertEqual({r['physical_host_key'] for r in active['runs']}, {'host:' + 'a' * 64, 'host:' + 'b' * 64, 'board:legacy'})
        alias = self.board('alias')
        self.assertEqual(alias['host_active_board_id'], 'alpha')
        self.assertIsNone(alias['active_run'])
        self.assertEqual(alias['status'], 'busy')
        self.assertFalse(self.board('legacy')['physical_host_identity_known'])
        with self.assertRaisesRegex(Conflict, 'lease occupied'):
            self.store.submit(self.plan('alias'), 'occupied')

    def test_fifo_alias_conflicts_atomic_admission_and_disjoint_progress(self):
        self.store.submit(self.plan('alpha'), 'active')
        first = self.store.submit(self.plan('alias', 'beta'), 'first', enqueue=True)
        second = self.store.submit(self.plan('alpha'), 'second', enqueue=True)
        independent = self.store.submit(self.plan('legacy'), 'disjoint', enqueue=True)
        self.assertTrue(all(r['physical_host_key'] is None for r in first['runs']))
        self.assertEqual(independent['runs'][0]['state'], 'queued')
        self.assertIsNone(self.store.poll('beta'))
        with self.assertRaises(Conflict): self.store.submit(self.plan('beta'), 'jump')
        self.finish('alpha')
        self.assertTrue(all(r['state'] == 'queued' for r in self.store.batch(first['id'])['runs']))
        self.assertEqual(self.store.batch(second['id'])['runs'][0]['state'], 'waiting')
        self.finish('alias')
        self.assertEqual(self.store.batch(second['id'])['runs'][0]['state'], 'queued')

    def test_quarantine_is_aggregated_recovery_is_target_specific(self):
        self.store.submit(self.plan('alpha'), 'unclean')
        self.finish('alpha', clean=False)
        queued = self.store.submit(self.plan('alias'), 'waiting', enqueue=True)
        self.assertEqual(self.board('alias')['host_quarantine_sources'], ['alpha'])
        self.store.board_action('alias', 'recover')
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['state'], 'waiting')
        self.assertTrue(self.board('alias')['host_quarantined'])
        self.store.board_action('alpha', 'recover')
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['state'], 'queued')
        with self.assertRaises(Conflict): self.store.board_action('alpha', 'recover')

    def test_expiry_and_late_completion_do_not_release_sibling(self):
        batch = self.store.submit(self.plan('alpha'), 'lost')
        job = self.store.poll('alpha')
        with self.store.tx() as db: db.execute("UPDATE boards SET seen=0 WHERE id='alpha'")
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'lost')
        self.heartbeat('alpha')
        self.store.finish('alpha', job['id'], Completion(state='succeeded', result={}, module_sha256='a' * 64))
        self.assertFalse(self.store.preflight(self.plan('alias'))['valid'])
        self.assertTrue(self.board('alias')['host_quarantined'])

    def test_forced_reload_cancels_sibling_without_early_release(self):
        self.store.submit(self.plan('alpha'), 'active')
        job = self.store.poll('alpha')
        self.store.board_action('alias', 'force-reload')
        self.assertEqual(self.store.poll('alpha')['state'], 'cancelling')
        self.heartbeat('alias', reload_ack=1)
        self.assertFalse(self.store.preflight(self.plan('alias'))['valid'])
        self.store.finish('alpha', job['id'], Completion(state='cancelled', result={}, module_sha256='a' * 64))
        self.assertTrue(self.store.preflight(self.plan('alias'))['valid'])
        self.store.board_action('alpha', 'reload')
        self.assertFalse(self.store.preflight(self.plan('alias'))['valid'])
        self.heartbeat('alpha', reload_ack=1, reload_error='reload failed')
        self.assertFalse(self.store.preflight(self.plan('alias'))['valid'])
        self.heartbeat('alpha', reload_ack=1)
        self.assertTrue(self.store.preflight(self.plan('alias'))['valid'])

    def test_identity_preservation_rebinding_guard_and_pinned_history(self):
        self.heartbeat('alpha')
        self.assertEqual(self.board('alpha')['physical_host_id'], 'a' * 64)
        active = self.store.submit(self.plan('alpha'), 'active')
        for board in ('alpha', 'alias'):
            with self.assertRaisesRegex(Conflict, 'identity cannot change'): self.heartbeat(board, 'c')
        self.store.submit(self.plan('legacy'), 'old-agent')
        with self.assertRaises(Conflict): self.heartbeat('legacy', 'c')
        self.finish('alpha')
        self.heartbeat('alias', 'c')
        Store(self.store.path)
        self.assertEqual(self.store.batch(active['id'])['runs'][0]['physical_host_key'], 'host:' + 'a' * 64)
        with self.store.tx() as db: db.execute("UPDATE boards SET quarantined=1 WHERE id='alpha'")
        with self.assertRaises(Conflict): self.heartbeat('alpha', 'd')
        self.assertEqual(self.board('alias')['physical_host_key'], 'host:' + 'c' * 64)

    def test_guest_restart_cannot_attest_sibling_cleanup_and_blocks_group(self):
        active = self.store.submit(self.plan('alpha'), 'active')
        with self.assertRaisesRegex(Conflict, 'Sibling target'):
            self.store.board_action('alias', 'restart', restart_id='restart-1')
        self.assertIsNone(self.board('alias')['maintenance'])
        self.store.cancel(active['id'])
        self.store.board_action('alpha', 'restart', restart_id='restart-2')
        self.assertFalse(self.store.preflight(self.plan('alias'))['valid'])
        with self.assertRaises(Conflict): self.store.board_action('alias', 'recover')
        with self.assertRaises(Conflict): self.heartbeat('alias', 'c')

    def test_waiting_targets_rebind_before_admission_and_revalidate_duplicates(self):
        with self.store.tx() as db: db.execute("UPDATE boards SET seen=0 WHERE id='beta'")
        queued = self.store.submit(self.plan('beta', 'legacy'), 'pending', enqueue=True)
        self.assertTrue(all(r['state'] == 'waiting' for r in queued['runs']))
        self.heartbeat('legacy', 'b')
        failed = self.store.batch(queued['id'])
        self.assertTrue(all(r['state'] == 'failed' for r in failed['runs']))
        self.assertTrue(all(r['physical_host_key'] is None for r in failed['runs']))
        self.assertTrue(all(r['result']['code_executed'] is False for r in failed['runs']))

    def test_legacy_active_lease_migrates_without_changing_completed_binding(self):
        batch = self.store.submit(self.plan('legacy'), 'legacy-active')
        # A pre-grouping database has admitted generations but no host key column.
        with self.store.tx() as db:
            db.execute('DROP INDEX physical_host_lease')
            db.execute('ALTER TABLE runs DROP COLUMN physical_host_key')
        restored = Store(self.store.path)
        self.assertEqual(restored.batch(batch['id'])['runs'][0]['physical_host_key'], 'board:legacy')
        with self.assertRaises(Conflict): self.heartbeat('legacy', 'c')
        self.finish('legacy')
        self.heartbeat('legacy', 'c')
        Store(self.store.path)
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['physical_host_key'], 'board:legacy')

    def test_database_constraint_protects_host_even_without_preflight(self):
        active = self.store.submit(self.plan('alpha'), 'active')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.tx() as db:
                db.execute("INSERT INTO runs(id,batch_id,board_id,state,created,module_sha256,physical_host_key) VALUES('duplicate',?,'alias','queued',0,?,?)",
                    (active['id'], 'a' * 64, 'host:' + 'a' * 64))

    def test_environment_host_memory_overhead_and_explicit_resource_policy(self):
        self.description = self.description.model_copy(update={'memory_overhead_mib': 256})
        self.heartbeat('alpha')
        plan = Plan(boards=['alpha'], template='workload', artifact_sha256='b' * 64,
                    environment_sha256='c' * 64, interference_cpus=[], memory_mib=896)
        payload = self.store._plan(plan)
        payload.update(artifact_available=True, environment_available=True, environment_architecture='aarch64')
        checked = self.store._call('preflight', **payload, enqueue=True)
        self.assertIn('host overhead', str(checked['errors']))
        payload['plan']['memory_mib'] = 768
        self.assertTrue(self.store._call('preflight', **payload)['valid'])
        payload['plan']['resource_policy'] = 'cgroup'
        self.assertFalse(self.store._call('preflight', **payload)['valid'])
        self.description = self.description.model_copy(update={'capabilities': self.description.capabilities + ['process-tree-limits']})
        self.heartbeat('alpha')
        self.assertTrue(self.store._call('preflight', **payload)['valid'])
        payload['plan']['memory_mib'] = None
        self.assertFalse(self.store._call('preflight', **payload, enqueue=True)['valid'])


if __name__ == '__main__': unittest.main()
