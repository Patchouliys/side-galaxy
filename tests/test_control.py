import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from side_galaxy.api import create_app
from side_galaxy.models import Completion, Description, Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Agent, LocalClient, Modules
from side_galaxy.store import Conflict, Store


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'fleet.db'
        self.store = Store(self.db)
        self.modules = Modules(Path(self.tmp.name) / 'modules', 'pi4', 'simulator')
        self.ids = []
        self.tokens = []
        for name in ('alpha', 'beta'):
            data = self.store.enroll(Enrollment(name=name))
            self.ids.append(data['board_id'])
            self.tokens.append(data['agent_token'])
            self.store.heartbeat(data['board_id'], Heartbeat(description=self.modules.current[1]))
        self.plan = Plan(boards=self.ids, duration_seconds=1)

    def test_atomic_admission_and_idempotency(self):
        batch = self.store.submit(self.plan, 'first')
        self.assertEqual(batch['id'], self.store.submit(self.plan, 'first')['id'])
        with self.assertRaises(Conflict): self.store.submit(self.plan.model_copy(update={'duration_seconds': 2}), 'first')
        with self.assertRaises(Conflict): self.store.submit(self.plan, 'second')
        self.assertEqual(len(self.store.batches()), 1)
        self.store.cancel(batch['id'])
        self.assertTrue(self.store.preflight(self.plan)['valid'])
        invalid = Plan(boards=[self.ids[0], 'missing'])
        with self.assertRaises(Conflict): self.store.submit(invalid, 'invalid')
        self.assertEqual(len(self.store.batches()), 1)

    def test_concurrent_claims_have_one_winner(self):
        def submit(key):
            try: return self.store.submit(self.plan, key)['id']
            except Conflict: return None
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(submit, ['a', 'b', 'c', 'd']))
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_reserved_cores_and_unsupported_bandwidth(self):
        self.assertFalse(self.store.preflight(Plan(boards=self.ids, cpus=[0]))['valid'])
        self.assertFalse(self.store.preflight(Plan(boards=self.ids, bandwidth_percent=50))['valid'])
        with self.assertRaises(ValueError): Plan(boards=self.ids, cpus=[1], interference_cpus=[1])

    def test_cancel_ack_and_quarantine(self):
        batch = self.store.submit(self.plan, 'c')
        job = self.store.poll(self.ids[0])
        self.assertTrue(job['claimed'])
        self.assertFalse(self.store.poll(self.ids[0])['claimed'])
        cancelled = self.store.cancel(batch['id'])
        self.assertIn('cancelling', [r['state'] for r in cancelled['runs']])
        self.assertFalse(self.store.preflight(self.plan)['valid'])
        self.store.finish(self.ids[0], job['id'], Completion(state='cancelled', result={}, module_sha256=job['module_sha256']))
        self.assertTrue(self.store.preflight(self.plan)['valid'])
        batch = self.store.submit(self.plan, 'd')
        job = self.store.poll(self.ids[0])
        self.store.finish(self.ids[0], job['id'], Completion(state='failed', result={}, module_sha256=job['module_sha256'], cleanup_ok=False))
        self.assertTrue(self.store.boards()[0]['quarantined'])

    def test_lost_agent_does_not_release_to_new_experiment(self):
        batch = self.store.submit(self.plan, 'lost')
        self.store.poll(self.ids[0])
        with self.store.tx() as db: db.execute('UPDATE boards SET seen=0 WHERE id=?', (self.ids[0],))
        states = {r['board_id']: r['state'] for r in self.store.batch(batch['id'])['runs']}
        self.assertEqual(states[self.ids[0]], 'lost')
        self.store.heartbeat(self.ids[0], Heartbeat(description=self.modules.current[1]))
        self.assertFalse(self.store.preflight(self.plan)['valid'])
        restored = Store(self.db)
        self.assertEqual(restored.batch(batch['id'])['id'], batch['id'])

    def test_authentication_scope_and_cross_origin(self):
        app = create_app(self.db, token='operator-token-is-long-enough', read_token='read-token-is-long-enough', background=False)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/boards').status_code, 401)
            read = {'Authorization':'Bearer read-token-is-long-enough'}
            self.assertEqual(client.get('/api/boards', headers=read).status_code, 200)
            self.assertEqual(client.post('/api/batches', json=self.plan.model_dump(), headers={**read,'Idempotency-Key':'auth'}).status_code, 403)
            self.assertEqual(client.post(f'/api/agent/{self.ids[1]}/poll', headers={'Authorization':'Bearer '+self.tokens[0]}).status_code, 403)
            self.assertEqual(client.get('/api/boards', headers={**read,'Origin':'https://untrusted.invalid'}).status_code, 403)
            self.assertNotIn('token_hash', client.get('/api/boards', headers=read).text)
            self.assertEqual(client.post('/api/preflight', json={**self.plan.model_dump(),'shell':'echo hi'}, headers=read).status_code, 422)

    def test_simulator_end_to_end(self):
        runners = [Agent(LocalClient(self.store), board, self.modules) for board in self.ids]
        batch = self.store.submit(self.plan, 'e2e')
        try:
            for _ in range(80):
                for runner in runners: runner.tick()
                states = self.store.batch(batch['id'])['runs']
                if all(r['state'] == 'succeeded' for r in states): break
                time.sleep(.05)
            self.assertTrue(all(r['state'] == 'succeeded' for r in states), states)
            self.assertTrue(all(r['result']['synthetic'] is True for r in states))
            self.assertTrue(all(r['module_sha256'] for r in states))
        finally:
            for runner in runners: runner.shutdown()


if __name__ == '__main__': unittest.main()
