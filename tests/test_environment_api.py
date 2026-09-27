import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from side_galaxy.api import create_app
from side_galaxy.environments import pack_environment
from side_galaxy.models import Description, Enrollment, Heartbeat, Plan


class EnvironmentAPITests(unittest.TestCase):
    def test_streamed_upload_authorization_and_claim_scoped_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'image'
            image.mkdir()
            (image / 'rootfs.raw').write_bytes(b'raw-test-disk')
            (image / 'kernel').write_bytes(b'kernel-test-data')
            (image / 'environment.json').write_text(json.dumps({'schema': 1, 'name': 'test-guest', 'architecture': 'aarch64',
                'disk': {'file': 'rootfs.raw', 'format': 'raw'}, 'boot': {'kernel': 'kernel', 'cmdline': 'console=ttyAMA0'},
                'files': {}, 'runtime': {'os': 'linux', 'commands': ['python3']}}))
            archive = root / 'environment.zip'
            pack_environment(image, archive)
            data = archive.read_bytes()
            app = create_app(root / 'db.sqlite', token='operator-token-at-least-24-chars', background=False)
            store = app.state.store
            board = store.enroll(Enrollment(name='test-target'))
            description = Description(name='prepared guest', mode='qemu-environment', cpus=[0, 1, 2], memory_mib=2048,
                capabilities=['cpu-affinity', 'memory-limit', 'workload-bundle', 'environment-bundle'], templates=['workload'],
                module_sha256='a' * 64, environment_architectures=['aarch64'])
            store.heartbeat(board['board_id'], Heartbeat(description=description))
            operator = {'Authorization': 'Bearer operator-token-at-least-24-chars'}
            agent = {'Authorization': 'Bearer ' + board['agent_token']}
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/environments', content=data).status_code, 403)
                response = client.post('/api/environments', content=iter([data[:100], data[100:]]), headers=operator)
                self.assertEqual(response.status_code, 201, response.text)
                digest = response.json()['sha256']
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                self.assertEqual(len(client.get('/api/environments', headers=operator).json()), 1)
                path = f"/api/agent/{board['board_id']}/environments/{digest}"
                self.assertEqual(client.get(path, headers=agent).status_code, 404)
                with store.tx() as db:
                    # A claimed experiment authorizes exactly its pinned environment.
                    db.execute('INSERT INTO batches(id,key,plan,sha256,created) VALUES(?,?,?,?,?)',
                        ('batch', 'key', json.dumps({'environment_sha256': digest}), 'b' * 64, 1))
                    db.execute('INSERT INTO runs(id,batch_id,board_id,state,created,module_sha256) VALUES(?,?,?,?,?,?)',
                        ('run', 'batch', board['board_id'], 'running', 1, 'a' * 64))
                downloaded = client.get(path, headers=agent)
                self.assertEqual(downloaded.status_code, 200)
                self.assertEqual(downloaded.content, data)
                self.assertEqual(client.get(path, headers=operator).status_code, 403)
                invalid = client.post('/api/environments', content=b'not zip', headers=operator)
                self.assertEqual(invalid.status_code, 422)
                self.assertFalse(list(store.environments.root.glob('.upload-*')))


if __name__ == '__main__': unittest.main()
