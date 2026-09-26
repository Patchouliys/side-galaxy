import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from side_galaxy.api import create_app
from side_galaxy.models import Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Modules


class WorkspaceAPITests(unittest.TestCase):
    def test_real_default_demo_switch_and_native_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / 'db', local_access=True, background=False)
            store = app.state.store
            description = Modules(root / 'module', 'generic', 'simulator').current[1]
            real = store.enroll(Enrollment(name='real', system_profile='linux-process'))['board_id']
            store.heartbeat(real, Heartbeat(description=description.model_copy(update={'mode': 'linux-process'})))
            with TestClient(app) as client:
                self.assertFalse(client.get('/api/workspace').json()['demo'])
                self.assertEqual(Enrollment(name='new-board').system_profile, 'linux-process')
                self.assertEqual([b['id'] for b in client.get('/api/boards').json()], [real])
                self.assertEqual(client.get('/api/boards', headers={'Host': 'outside.example'}).status_code, 403)
                self.assertTrue(client.put('/api/workspace', json={'demo': True}).json()['demo'])
                self.assertEqual(len(client.get('/api/boards').json()), 4)
                plan = Plan(boards=['pi4-lab'], duration_seconds=1)
                sample = store.submit(plan, 'sample')
                self.assertFalse(client.put('/api/workspace', json={'demo': False}).json()['demo'])
                self.assertEqual([b['id'] for b in client.get('/api/boards').json()], [real])
                self.assertFalse(client.post('/api/preflight', json=plan.model_dump()).json()['valid'])
                self.assertEqual(client.post('/api/batches', json=plan.model_dump(), headers={'Idempotency-Key': 'blocked'}).status_code, 409)
                self.assertEqual(client.get('/api/batches').json(), [])
                self.assertEqual(store.batch(sample['id'])['runs'][0]['state'], 'cancelled')
                self.assertEqual(len(store.batches()), 1)
                self.assertTrue(client.get('/api/workspace').json()['local_access'])
                client.put('/api/workspace', json={'demo': True})
                self.assertEqual(len(client.get('/api/boards').json()), 4)

    def test_operator_actions_remain_protected_after_mode_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'db', token='operator-token-at-least-24-chars',
                             read_token='reader-token-at-least-24-chars', background=False)
            reader = {'Authorization': 'Bearer reader-token-at-least-24-chars'}
            operator = {'Authorization': 'Bearer operator-token-at-least-24-chars'}
            with TestClient(app) as client:
                self.assertEqual(client.put('/api/workspace', json={'demo': True}, headers=reader).status_code, 403)
                self.assertEqual(client.post('/api/labs/unknown/restart', json={'force': True}, headers=reader).status_code, 403)
                self.assertEqual(client.post('/api/boards/unknown/reload?force=true', headers=reader).status_code, 403)
                client.put('/api/workspace', json={'demo': True}, headers=operator)
                self.assertEqual(client.get('/api/boards').status_code, 401)
                self.assertFalse(client.get('/api/workspace', headers=reader).json()['local_access'])
                self.assertEqual(client.post('/api/labs/unknown/restart', json={}, headers=operator).status_code, 404)

    def test_async_restart_blocks_duplicate_and_admission_until_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lab').mkdir()
            (root / 'lab' / 'state.json').write_text('{}')
            app = create_app(root / 'db', local_access=True, background=False)
            store = app.state.store
            desc = Modules(root / 'module', 'generic', 'simulator').current[1].model_copy(update={'mode': 'linux-process'})
            board = store.enroll(Enrollment(name='QEMU', system_profile='linux-process'))['board_id']
            store.heartbeat(board, Heartbeat(description=desc))
            release = threading.Event()

            class Lab:
                vm_status = 'running'
                def __init__(self, path): pass
                def status(self): return {'status': self.vm_status, 'stage': 'ready', 'instance_id': 'test-instance', 'board_id': board}
                def restart(self, **kwargs):
                    if not release.wait(5): raise ValueError('timeout')
                    return {'boot_id_before': 'old-boot', 'boot_id_after': 'new-boot', 'agent_ready': True}

            with patch('side_galaxy.lab.Lab', Lab), TestClient(app) as client:
                try:
                    Lab.vm_status = 'paused'
                    self.assertEqual(client.post('/api/labs/test-instance/restart', json={}).status_code, 409)
                    self.assertIsNone(store.boards()[0]['maintenance'])
                    Lab.vm_status = 'running'
                    response = client.post('/api/labs/test-instance/restart', json={'force': True})
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertEqual(client.post('/api/labs/test-instance/restart', json={}).status_code, 409)
                    self.assertFalse(store.preflight(Plan(boards=[board]))['valid'])
                    release.set()
                    for _ in range(100):
                        state = client.get('/api/labs').json()[0]['operation']['state']
                        if state != 'running': break
                        time.sleep(.01)
                    self.assertEqual(state, 'succeeded')
                    self.assertTrue(store.preflight(Plan(boards=[board]))['valid'])
                    with patch.object(Lab, 'restart', side_effect=ValueError('private diagnostic path')):
                        self.assertEqual(client.post('/api/labs/test-instance/restart', json={}).status_code, 202)
                        for _ in range(100):
                            operation = client.get('/api/labs').json()[0]['operation']
                            if operation['state'] != 'running': break
                            time.sleep(.01)
                        self.assertEqual(operation['state'], 'failed')
                        self.assertNotIn('private diagnostic path', operation['error'])
                        self.assertFalse(store.preflight(Plan(boards=[board]))['valid'])
                finally: release.set()
