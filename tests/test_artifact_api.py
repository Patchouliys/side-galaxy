import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from concurrent.futures import Future
import zipfile

from fastapi.testclient import TestClient
from side_galaxy.api import create_app
from side_galaxy.models import Completion, Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Agent, LocalClient, Modules


def bundle():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('experiment.json', json.dumps({'schema': 1, 'name': 'integration', 'run': ['python3', 'main.py'], 'outputs': []}))
        archive.writestr('main.py', 'raise RuntimeError("simulator must not execute this")')
    return data.getvalue()


class ArtifactAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = create_app(self.root / 'db.sqlite', token='operator-token-at-least-24-chars', read_token='reader-token-at-least-24-chars', background=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.operator = {'Authorization': 'Bearer operator-token-at-least-24-chars'}
        self.reader = {'Authorization': 'Bearer reader-token-at-least-24-chars'}
        self.store = self.app.state.store
        self.store.set_workspace_mode(True)
        self.modules = Modules(self.root / 'modules', 'pi4', 'simulator')
        self.boards = [self.store.enroll(Enrollment(name=name)) for name in ['first', 'second']]
        for board in self.boards: self.store.heartbeat(board['board_id'], Heartbeat(description=self.modules.current[1]))

    def upload(self):
        response = self.client.post('/api/artifacts', content=bundle(), headers=self.operator)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['sha256']

    def plan(self, sha):
        return Plan(boards=[self.boards[0]['board_id']], template='workload', artifact_sha256=sha, interference_cpus=[], duration_seconds=1)

    def test_artifact_authorization_assignment_and_tamper(self):
        self.assertEqual(self.client.post('/api/artifacts', content=bundle(), headers=self.reader).status_code, 403)
        self.assertEqual(self.client.post('/api/artifacts', content=b'bad zip', headers=self.operator).status_code, 422)
        sha = self.upload()
        self.assertEqual(self.client.get('/api/artifacts', headers=self.reader).json()[0]['sha256'], sha)
        self.assertFalse(self.store.preflight(self.plan('0' * 64))['valid'])
        board = self.boards[0]
        agent_header = {'Authorization': 'Bearer ' + board['agent_token']}
        route = f'/api/agent/{board["board_id"]}/artifacts/{sha}'
        self.assertEqual(self.client.get(route, headers=agent_header).status_code, 404)
        batch = self.store.submit(self.plan(sha), 'artifact-auth')
        self.store.poll(board['board_id'])
        self.assertEqual(self.client.get(route, headers=agent_header).content, bundle())
        self.assertEqual(self.client.get(route, headers={'Authorization': 'Bearer ' + self.boards[1]['agent_token']}).status_code, 403)
        self.store.artifacts.get(sha).write_bytes(b'corrupted')
        self.assertEqual(self.client.get(route, headers=agent_header).status_code, 404)

    def test_simulator_stages_but_does_not_execute_uploaded_code(self):
        sha = self.upload()
        batch = self.store.submit(self.plan(sha), 'artifact-simulator')
        agent = Agent(LocalClient(self.store), self.boards[0]['board_id'], self.modules)
        try:
            for _ in range(100):
                agent.tick()
                run = self.store.batch(batch['id'])['runs'][0]
                if run['state'] in ('succeeded', 'failed'): break
                time.sleep(.02)
            self.assertEqual(run['state'], 'succeeded', run)
            self.assertTrue(run['result']['synthetic'])
            self.assertFalse(run['result']['code_executed'])
            self.assertEqual(run['result']['artifact_sha256'], sha)
        finally: agent.shutdown()

    def test_output_download_digest_and_listing_redaction(self):
        sha = self.upload()
        batch = self.store.submit(self.plan(sha), 'outputs')
        job = self.store.poll(self.boards[0]['board_id'])
        content = b'reproducible result\n'
        result = {'outputs': [{'path': 'results/data.txt', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(), 'data_base64': base64.b64encode(content).decode()}]}
        self.store.finish(self.boards[0]['board_id'], job['id'], Completion(state='succeeded', result=result, module_sha256=job['module_sha256']))
        listing = self.client.get('/api/batches/' + batch['id'], headers=self.reader)
        self.assertNotIn('data_base64', listing.text)
        route = f'/api/runs/{job["id"]}/outputs/0'
        self.assertEqual(self.client.get(route).status_code, 401)
        download = self.client.get(route, headers=self.reader)
        self.assertEqual(download.content, content)
        self.assertEqual(download.headers['X-Content-SHA256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.client.get(route[:-1] + '-1', headers=self.reader).status_code, 404)

    def test_workload_constraints_and_pending_transfer_cancellation(self):
        with self.assertRaises(ValueError): Plan(boards=['x'], template='workload')
        with self.assertRaises(ValueError): Plan(boards=['x'], duration_seconds=121)
        self.assertEqual(self.plan('0'*64).model_copy(update={'duration_seconds': 86400}).duration_seconds, 86400)
        sha = self.upload()
        batch = self.store.submit(self.plan(sha), 'cancel-transfer')
        agent = Agent(LocalClient(self.store), self.boards[0]['board_id'], self.modules)
        try:
            agent.tick()
            self.assertIsNotNone(agent.staging)
            self.store.cancel(batch['id'])
            for _ in range(100):
                agent.tick()
                run = self.store.batch(batch['id'])['runs'][0]
                if run['state'] == 'cancelled': break
                time.sleep(.01)
            self.assertEqual(run['state'], 'cancelled')
            self.assertFalse(run['result']['code_executed'])
            self.assertTrue(self.store.preflight(self.plan(sha))['valid'])
        finally: agent.shutdown()

    def test_stale_staging_never_starts_under_replacement_job(self):
        sha = self.upload()
        batch = self.store.submit(self.plan(sha), 'stale-staging')
        board = self.boards[0]['board_id']
        job = self.store.poll(board)
        agent = Agent(LocalClient(self.store), board, self.modules)
        future = Future()
        future.set_result(self.store.artifacts.get(sha))
        agent.staging = (self.modules.current[0], job, future)
        try:
            with self.store.tx() as db:
                db.execute("UPDATE runs SET state='lost' WHERE id=?", (job['id'],))
            replacement = self.store.submit(self.plan(sha), 'replacement')
            agent.tick()
            self.assertIsNone(agent.execution)
            self.assertEqual(agent.pending[0], job['id'])
            self.assertFalse(agent.pending[1].result['code_executed'])
        finally: agent.shutdown()

    def test_module_required_memory_and_oversized_plan_rejected(self):
        desc = self.modules.current[1].model_copy(update={'memory_limit_required': True})
        board = self.boards[0]['board_id']
        self.store.heartbeat(board, Heartbeat(description=desc))
        plan = Plan(boards=[board], memory_mib=None)
        self.assertFalse(self.store.preflight(plan)['valid'])
        with self.assertRaises(ValueError):
            Plan(boards=[board], template='workload', artifact_sha256='0'*64, interference_cpus=[], arguments=['x'*4096]*10)
