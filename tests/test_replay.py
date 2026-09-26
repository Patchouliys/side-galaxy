import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient
from side_galaxy.api import create_app
from side_galaxy.models import Enrollment, Heartbeat, Plan
from side_galaxy.runtime import Modules


class ReplayTests(unittest.TestCase):
    def test_replay_preserves_bundle_parameters_and_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / 'db', token='operator-token-at-least-24-chars', read_token='reader-token-at-least-24-chars', background=False)
            store = app.state.store
            store.set_workspace_mode(True)
            description = Modules(root / 'modules', 'generic', 'simulator').current[1]
            boards = [store.enroll(Enrollment(name=name))['board_id'] for name in ('source', 'target')]
            for board in boards: store.heartbeat(board, Heartbeat(description=description))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('experiment.json', json.dumps({'schema':1, 'name':'portable', 'run':['python3','main.py']}))
                archive.writestr('main.py', 'print("portable")')
            artifact = store.artifacts.put(buffer.getvalue())
            plan = Plan(boards=[boards[0]], template='workload', artifact_sha256=artifact['sha256'],
                        interference_cpus=[], arguments=['repeat'], environment={'LABEL':'same'}, duration_seconds=1)
            source = store.submit(plan, 'source-key')
            original = store.cancel(source['id'])
            endpoint = '/api/batches/' + source['id'] + '/replay'
            headers = {'Authorization':'Bearer operator-token-at-least-24-chars', 'Idempotency-Key':'replay-key'}
            with TestClient(app) as client:
                denied = client.post(endpoint, json={'boards':[boards[1]]}, headers={**headers, 'Authorization':'Bearer reader-token-at-least-24-chars'})
                self.assertEqual(denied.status_code, 403)
                replay = client.post(endpoint, json={'boards':[boards[1]]}, headers=headers)
                self.assertEqual(replay.status_code, 201, replay.text)
                data = replay.json()
                self.assertEqual(data['plan'], {**plan.model_dump(), 'boards':[boards[1]]})
                self.assertNotEqual(data['id'], source['id'])
                self.assertEqual(store.batch(source['id']), original)
                self.assertEqual(client.post(endpoint, json={'boards':[boards[1]]}, headers=headers).json()['id'], data['id'])
                self.assertEqual(client.post(endpoint, json={'boards':['missing']}, headers={**headers,'Idempotency-Key':'missing'}).status_code, 409)
                self.assertEqual(client.post(endpoint, json={'boards':[boards[1],boards[1]]}, headers=headers).status_code, 422)
                self.assertEqual(client.post(endpoint, json={'boards':[boards[0]]}, headers={**headers,'Idempotency-Key':'source-key'}).status_code, 422)
                self.assertEqual(len(store.batches()), 2)


if __name__ == '__main__': unittest.main()
