import base64
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from side_galaxy.models import Completion, Description, Enrollment, Heartbeat, Plan
from side_galaxy.store import Conflict, Store, canonical, digest


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / 'fleet.db')
        self.description = Description(name='Queue test runtime', mode='linux-process',
            cpus=[0, 1, 2, 3], reserved_cpus=[0], memory_mib=1024,
            capabilities=['cpu-affinity', 'memory-limit', 'interference', 'workload-bundle'],
            templates=['cpu-contention', 'workload'], module_sha256='a' * 64,
            execution_environment={'architecture': 'aarch64', 'os': 'linux', 'commands': ['cc'], 'commands_complete': True})
        for name in ('alpha', 'beta', 'gamma'):
            self.store.enroll(Enrollment(name=name), board_id=name)
            self.heartbeat(name)

    def heartbeat(self, board, generation='a', reload_ack=0):
        self.store.heartbeat(board, Heartbeat(description=self.description.model_copy(
            update={'module_sha256': generation * 64}), reload_ack=reload_ack))

    def plan(self, *boards):
        return Plan(boards=list(boards), duration_seconds=5)

    def finish(self, board, clean=True):
        job = self.store.poll(board)
        self.assertIsNotNone(job)
        return self.store.finish(board, job['id'], Completion(state='succeeded', result={'cleanup_ok': clean},
            module_sha256=job['module_sha256'], cleanup_ok=clean))

    def test_fifo_atomic_batch_and_disjoint_progress(self):
        active = self.store.submit(self.plan('alpha'), 'active')
        first = self.store.submit(self.plan('alpha', 'beta'), 'first', enqueue=True)
        second = self.store.submit(self.plan('beta'), 'second', enqueue=True)
        independent = self.store.submit(self.plan('gamma'), 'independent', enqueue=True)
        self.assertEqual([r['state'] for r in first['runs']], ['waiting', 'waiting'])
        self.assertTrue(all(r['module_sha256'] is None for r in first['runs']))
        self.assertEqual(first['queue_position'], 1)
        self.assertEqual(second['queue_position'], 2)
        self.assertEqual(independent['runs'][0]['state'], 'queued')
        self.assertIsNone(self.store.poll('beta'))
        with self.assertRaises(Conflict): self.store.submit(self.plan('beta'), 'jump-queue')
        self.heartbeat('beta', generation='b')
        self.finish('alpha')
        admitted = self.store.batch(first['id'])
        self.assertTrue(all(r['state'] == 'queued' for r in admitted['runs']))
        self.assertIsNone(admitted['queue_position'])
        pinned = {r['board_id']: r['module_sha256'] for r in admitted['runs']}
        self.assertEqual(pinned, {'alpha': 'a' * 64, 'beta': 'b' * 64})
        self.assertEqual(self.store.batch(second['id'])['runs'][0]['state'], 'waiting')
        self.finish('alpha')
        self.finish('beta')
        self.assertEqual(self.store.batch(second['id'])['runs'][0]['state'], 'queued')
        self.assertEqual(self.store.batch(active['id'])['runs'][0]['state'], 'succeeded')

    def test_idempotency_queue_intent_cancel_and_invalid_submission(self):
        self.store.submit(self.plan('alpha'), 'active')
        queued = self.store.submit(self.plan('alpha'), 'waiting', enqueue=True)
        self.assertEqual(self.store.submit(self.plan('alpha'), 'waiting', enqueue=True)['id'], queued['id'])
        with self.assertRaises(Conflict): self.store.submit(self.plan('alpha'), 'waiting')
        with self.assertRaises(Conflict): self.store.submit(self.plan('missing'), 'missing', enqueue=True)
        with self.assertRaises(Conflict):
            self.store.submit(self.plan('alpha').model_copy(update={'cpus': [0]}), 'reserved', enqueue=True)
        cancelled = self.store.cancel(queued['id'])
        self.assertEqual(cancelled['runs'][0]['state'], 'cancelled')
        self.assertFalse(cancelled['runs'][0]['result']['code_executed'])
        self.assertIsNone(cancelled['queue_position'])
        self.assertIsNone(cancelled['runs'][0]['module_sha256'])
        self.assertEqual(len(self.store.batches()), 2)

    def test_offline_reload_and_quarantine_wait_without_expiry(self):
        with self.store.tx() as db: db.execute("UPDATE boards SET seen=0 WHERE id='alpha'")
        checked = self.store.preflight(self.plan('alpha'), enqueue=True)
        self.assertTrue(checked['valid'])
        self.assertTrue(checked['queueable'])
        self.assertIn('offline', checked['waiting_reason'])
        queued = self.store.submit(self.plan('alpha'), 'offline', enqueue=True)
        with self.store.tx() as db:
            db.execute("UPDATE runs SET created=0 WHERE batch_id=?", (queued['id'],))
            db.execute("UPDATE boards SET quarantined=1 WHERE id='alpha'")
        self.heartbeat('alpha')
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['state'], 'waiting')
        self.assertIn('quarantined', self.store.batch(queued['id'])['waiting_reason'])
        self.store.board_action('alpha', 'reload')
        self.store.board_action('alpha', 'recover')
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['state'], 'waiting')
        self.heartbeat('alpha', generation='b', reload_ack=1)
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['module_sha256'], 'b' * 64)

    def test_concurrent_enqueue_has_one_lease_and_bounded_queue(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            batches = list(workers.map(lambda n: self.store.submit(self.plan('alpha'), f'parallel-{n}', enqueue=True), range(8)))
        with self.store.tx() as db:
            counts = dict(db.execute('SELECT state,COUNT(*) FROM runs GROUP BY state').fetchall())
        self.assertEqual(counts, {'queued': 1, 'waiting': 7})
        # Exercise the native bound without spending test time on 249 complete adapter calls.
        with self.store.tx() as db:
            contract = db.execute('SELECT admission_contract FROM batches LIMIT 1').fetchone()[0]
            for n in range(249):
                batch = f'bound-{n}'
                db.execute('INSERT INTO batches(id,key,plan,sha256,created,enqueue,admission_contract) VALUES(?,?,?,?,0,1,?)',
                           (batch, batch, '{}', 'c' * 64, contract))
                db.execute("INSERT INTO runs(id,batch_id,board_id,state,created) VALUES(?,?,?,'waiting',0)", (batch, batch, 'alpha'))
        with self.assertRaisesRegex(Conflict, 'queue is full'):
            self.store.submit(self.plan('alpha'), 'overflow', enqueue=True)
        # A retry is still valid when the queue is full.
        self.assertEqual(self.store.submit(self.plan('alpha'), 'parallel-0', enqueue=True)['id'], batches[0]['id'])

    def test_lost_completion_keeps_evidence_and_quarantine(self):
        batch = self.store.submit(self.plan('alpha'), 'lost')
        job = self.store.poll('alpha')
        queued = self.store.submit(self.plan('alpha'), 'next', enqueue=True)
        with self.store.tx() as db: db.execute("UPDATE boards SET seen=0 WHERE id='alpha'")
        self.assertEqual(self.store.batch(batch['id'])['runs'][0]['state'], 'lost')
        data = b'recovered evidence'
        output = {'path': 'result.txt', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                  'data_base64': base64.b64encode(data).decode()}
        completion = Completion(state='failed', result={'cleanup_ok': True, 'outputs': [output]},
                                module_sha256=job['module_sha256'], cleanup_ok=True)
        finished = self.store.finish('alpha', job['id'], completion)
        self.assertEqual(finished['state'], 'lost')
        self.assertTrue(finished['result']['late_completion']['cleanup_ok'])
        self.assertNotIn('data_base64', finished['result']['late_completion']['result']['outputs'][0])
        self.assertEqual(self.store.output_file(job['id'], 0)[1], data)
        self.heartbeat('alpha')
        self.assertEqual(self.store.batch(queued['id'])['runs'][0]['state'], 'waiting')
        self.assertEqual(next(b for b in self.store.boards() if b['id'] == 'alpha')['quarantined'], 1)

    def test_saved_requirements_revalidated_at_dispatch(self):
        self.store.submit(self.plan('alpha'), 'active')
        plan = self.plan('alpha').model_copy(update={'template': 'workload', 'artifact_sha256': 'c' * 64, 'interference_cpus': []})
        payload = self.store._plan(plan)
        payload.update(artifact_available=True, artifact_requirements={'commands': ['cc']})
        queued = self.store._call('submit', **payload, enqueue=True, key='requirements', batch_id='requirements', run_ids=['required-run'])
        self.description = self.description.model_copy(update={'execution_environment':
            self.description.execution_environment.model_copy(update={'commands': []})})
        self.heartbeat('alpha')
        failed = self.store.batch(queued['id'])['runs'][0]
        self.assertEqual(failed['state'], 'failed')
        self.assertIn('command missing', failed['result']['error'])
        self.assertFalse(failed['result']['code_executed'])

    def test_waiting_survives_store_reopen_and_maintenance(self):
        self.store.board_action('alpha', 'restart')
        queued = self.store.submit(self.plan('alpha', 'beta'), 'maintenance', enqueue=True)
        reopened = Store(self.store.path)
        pending = reopened.batch(queued['id'])
        self.assertTrue(all(r['state'] == 'waiting' for r in pending['runs']))
        self.assertIn('maintenance', pending['waiting_reason'])
        self.assertIsNone(reopened.poll('beta'))
        self.assertEqual(reopened.submit(self.plan('alpha', 'beta'), 'maintenance', enqueue=True)['id'], queued['id'])
        self.assertTrue(all(r['state'] == 'cancelled' for r in reopened.cancel(queued['id'])['runs']))

    def test_environment_contract_requires_capability_architecture_and_runtime(self):
        plan = self.plan('alpha').model_dump()
        plan.update(template='workload', artifact_sha256='c' * 64, environment_sha256='d' * 64, interference_cpus=[])
        payload = {'plan': plan, 'plan_sha256': 'e' * 64, 'artifact_available': True,
                   'artifact_requirements': {'commands': ['cc'], 'os': 'linux', 'architectures': ['aarch64']},
                   'environment_available': True, 'environment_architecture': 'aarch64',
                   'environment_runtime': {'architecture': 'aarch64', 'os': 'linux', 'commands': ['cc'], 'commands_complete': True}}
        self.assertFalse(self.store._call('preflight', **payload, enqueue=True)['valid'])
        description = self.description.model_dump()
        description['capabilities'].append('environment-bundle')
        description['environment_architectures'] = ['aarch64']
        description['execution_environment'] = None
        self.store._call('heartbeat', board_id='alpha', heartbeat={'description': description})
        self.assertTrue(self.store._call('preflight', **payload, enqueue=True)['valid'])
        self.assertFalse(self.store._call('preflight', **dict(payload, environment_available=False), enqueue=True)['valid'])
        self.assertFalse(self.store._call('preflight', **dict(payload, environment_architecture='x86_64'), enqueue=True)['valid'])
        runtime = dict(payload['environment_runtime'], commands=[])
        self.assertFalse(self.store._call('preflight', **dict(payload, environment_runtime=runtime), enqueue=True)['valid'])

    def test_environment_staging_budget_preserves_independent_heartbeat_expiry(self):
        description = self.description.model_dump()
        description['capabilities'].append('environment-bundle')
        description['environment_architectures'] = ['aarch64']
        for board in ('alpha', 'beta'):
            self.store._call('heartbeat', board_id=board, heartbeat={'description': description})
            plan = self.plan(board).model_dump()
            plan.update(template='workload', artifact_sha256='c' * 64, environment_sha256='d' * 64, interference_cpus=[])
            payload = {'plan': plan, 'plan_sha256': 'e' * 64, 'artifact_available': True,
                       'environment_available': True, 'environment_architecture': 'aarch64'}
            self.store._call('submit', **payload, key=board, batch_id=board, run_ids=[board])
            self.store.poll(board)
        with self.store.tx() as db:
            db.execute('UPDATE runs SET started=?', (time.time() - 300,))
        self.assertEqual(self.store.batch('alpha')['runs'][0]['state'], 'running')
        with self.store.tx() as db:
            db.execute("UPDATE runs SET started=? WHERE board_id='alpha'", (time.time() - 1810,))
            db.execute("UPDATE boards SET seen=? WHERE id='beta'", (time.time() - 31,))
        self.assertEqual(self.store.batch('alpha')['runs'][0]['state'], 'lost')
        self.assertEqual(self.store.batch('beta')['runs'][0]['state'], 'lost')
        self.assertTrue(all(b['quarantined'] for b in self.store.boards() if b['id'] in ('alpha', 'beta')))

    def test_required_environment_rejected_before_lease_or_quarantine(self):
        required = self.description.model_copy(update={'environment_required': True})
        self.store.heartbeat('alpha', Heartbeat(description=required))
        plan = self.plan('alpha').model_dump()
        plan.update(template='workload', artifact_sha256='c' * 64, interference_cpus=[])
        payload = {'plan': plan, 'plan_sha256': 'e' * 64, 'artifact_available': True}
        for enqueue in (False, True):
            checked = self.store._call('preflight', **payload, enqueue=enqueue)
            self.assertFalse(checked['valid'])
            self.assertIn('module requires an environment bundle', checked['errors'][0]['reasons'])
            with self.assertRaisesRegex(Conflict, 'requires an environment bundle'):
                self.store._call('submit', **payload, enqueue=enqueue, key='required', batch_id='required', run_ids=['required'])
        self.assertEqual(self.store.batches(), [])
        self.assertIsNone(self.store.poll('alpha'))
        target = next(b for b in self.store.boards() if b['id'] == 'alpha')
        self.assertEqual(target['status'], 'ready')
        self.assertFalse(target['quarantined'])
        self.assertFalse(self.description.environment_required)

    def test_legacy_idempotency_hash_survives_nullable_environment_field(self):
        plan = self.plan('alpha')
        legacy_body = plan.model_dump()
        legacy_body.pop('environment_sha256')
        legacy_body.pop('resource_policy')
        legacy_hash = digest(canonical(legacy_body))
        previous = self.store._call('submit', key='legacy-retry', batch_id='legacy', run_ids=['legacy-run'],
            plan=legacy_body, plan_sha256=legacy_hash, artifact_available=True)
        self.assertEqual(self.store._plan(plan)['plan_sha256'], legacy_hash)
        self.assertEqual(self.store.submit(plan, 'legacy-retry')['id'], previous['id'])
        with self.assertRaises(Conflict): self.store.submit(plan, 'legacy-retry', enqueue=True)
        with self.assertRaises(Conflict):
            self.store.submit(plan.model_copy(update={'duration_seconds': 6}), 'legacy-retry')
        environment = plan.model_copy(update={'template': 'workload', 'artifact_sha256': 'a' * 64,
            'environment_sha256': 'b' * 64, 'interference_cpus': []})
        environment_body = environment.model_dump()
        environment_body.pop('resource_policy')
        self.assertEqual(self.store._plan(environment)['plan_sha256'], digest(canonical(environment_body)))
        explicit = environment.model_copy(update={'resource_policy': 'cgroup'})
        self.assertEqual(self.store._plan(explicit)['plan_sha256'], digest(canonical(explicit.model_dump())))
        with self.assertRaises(Conflict): self.store.submit(environment, 'legacy-retry')


if __name__ == '__main__':
    unittest.main()
