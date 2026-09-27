"""Measured-history API checks using temporary state, not hardware measurements."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from side_galaxy.api import create_app
from side_galaxy.cli import main
from side_galaxy.mcp_server import create_mcp
from side_galaxy.models import Completion, Description, Enrollment, Heartbeat, HostSample, Plan
from side_galaxy.telemetry import MAX_SAMPLES, Telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'telemetry.db'
        self.app = create_app(self.path, token='operator-test-token-with-24-chars',
                              read_token='reader-test-token-with-24-chars', background=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.store, self.telemetry = self.app.state.store, self.app.state.telemetry
        self.reader = {'Authorization': 'Bearer reader-test-token-with-24-chars'}
        self.description = Description(name='Measured target', mode='linux-process', cpus=[0, 1],
            reserved_cpus=[0], memory_mib=1024, capabilities=['cpu-affinity', 'memory-limit'],
            templates=['cpu-contention'], module_sha256='a' * 64, memory_overhead_mib=128)
        self.targets = [self.store.enroll(Enrollment(name=name)) for name in ('process', 'guest', 'independent')]
        for index, target in enumerate(self.targets):
            self.store.heartbeat(target['board_id'], Heartbeat(description=self.description,
                physical_host_id=('b' if index < 2 else 'c') * 64))
        self.board = self.targets[0]['board_id']
        self.route = f'/api/boards/{self.board}/telemetry'
        self.heartbeat_route = f'/api/agent/{self.board}/heartbeat'
        self.agent = {'Authorization': 'Bearer ' + self.targets[0]['agent_token']}

    def post(self, sample, headers=None):
        return self.client.post(self.heartbeat_route,
            json={'description': self.description.model_dump(), 'telemetry': sample},
            headers=self.agent if headers is None else headers)

    def read(self, board=None, limit=60):
        result = self.client.get(f'/api/boards/{board or self.board}/telemetry',
                                 params={'limit': limit}, headers=self.reader)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_authorization_missing_samples_and_limits(self):
        self.assertEqual(self.client.get(self.route).status_code, 401)
        self.assertEqual(self.client.get(self.route, headers=self.agent).status_code, 401)
        self.assertEqual(self.read()['history'], [])
        self.assertTrue(self.read()['stale'])
        for limit in (0, 721, 'nan'):
            self.assertEqual(self.client.get(self.route, params={'limit': limit}, headers=self.reader).status_code, 422)
        self.assertEqual(self.client.get('/api/boards/unknown/telemetry', headers=self.reader).status_code, 404)
        body = {'sampled_at': 1, 'source': 'linux', 'cpu_percent': 0}
        for headers in ({}, self.reader, {'Authorization': 'Bearer ' + self.targets[1]['agent_token']}):
            self.assertEqual(self.post(body, headers).status_code, 403)
        self.assertEqual(self.read()['history'], [])

    def test_invalid_samples_do_not_change_history(self):
        for extra in ({'cpu_percent': 101}, {'cpu_frequency_mhz': -1}, {'temperature_celsius': 'NaN'},
                      {'source': 'fabricated'}, {'sampled_at': -1}, {'private_path': '/not/telemetry'},
                      {'per_cpu': [{'id': 1024}]}, {'per_cpu': [{'id': 0}] * 1025}):
            with self.subTest(extra=list(extra)):
                response = self.post({'sampled_at': 1, 'source': 'linux', **extra})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.read()['history'], [])

    def test_receipt_freshness_null_zero_and_persistence(self):
        with patch('side_galaxy.telemetry.time.time', return_value=100):
            response = self.post({'sampled_at': 999999, 'source': 'linux', 'cpu_percent': 0,
                                  'temperature_celsius': None, 'cgroup_available': True})
            self.assertEqual(response.status_code, 200, response.text)
            result = self.read()
            self.assertFalse(result['stale'])
            self.assertEqual(result['latest']['cpu_percent'], 0)
            self.assertIsNone(result['latest']['temperature_celsius'])
            self.assertEqual(result['latest']['received_at'], 100)
        with patch('side_galaxy.telemetry.time.time', return_value=121):
            self.assertTrue(Telemetry(self.store).read(self.board)['stale'])
        with patch('side_galaxy.telemetry.time.time', return_value=125):
            self.assertEqual(self.post({'sampled_at': 2, 'source': 'unavailable'}).status_code, 200)
            latest = self.read()['latest']
            self.assertEqual(latest['source'], 'unavailable')
            self.assertIsNone(latest['cpu_percent'])

    def test_duplicate_rate_limit_retention_and_latest_window(self):
        for received, sampled in ((100, 1), (101, 2), (105, 1), (110, 3)):
            with patch('side_galaxy.telemetry.time.time', return_value=received):
                self.telemetry.append(self.board, HostSample(sampled_at=sampled, source='linux'))
        self.assertEqual([v['sampled_at'] for v in self.read()['history']], [1, 3])
        for index in range(MAX_SAMPLES + 5):
            with patch('side_galaxy.telemetry.time.time', return_value=200 + index * 5):
                self.telemetry.append(self.board, HostSample(sampled_at=100 + index, source='linux'))
        history = self.read(limit=MAX_SAMPLES)['history']
        self.assertEqual(len(history), MAX_SAMPLES)
        self.assertEqual(history[0]['sampled_at'], 105)
        self.assertEqual(self.read(limit=3)['history'], history[-3:])
        with self.store.tx() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0], MAX_SAMPLES)

    def test_host_allocations_exclude_waiting_and_independent_hosts(self):
        plan = Plan(boards=[self.board], interference_cpus=[])
        batch = self.store.submit(plan, 'allocated')
        waiting = self.store.submit(plan, 'waiting', enqueue=True)
        sibling = self.read(self.targets[1]['board_id'])
        self.assertEqual(len(sibling['allocations']), 1)
        allocation = sibling['allocations'][0]
        self.assertEqual(allocation['batch_id'], batch['id'])
        self.assertNotEqual(allocation['batch_id'], waiting['id'])
        self.assertEqual(allocation['cpus'], [1])
        self.assertEqual(allocation['memory_mib'], 256)
        self.assertEqual(allocation['memory_overhead_mib'], 128)
        self.assertEqual(allocation['resource_policy'], 'auto')
        self.assertEqual(self.read(self.targets[2]['board_id'])['allocations'], [])
        job = self.store.poll(self.board)
        self.store.finish(self.board, job['id'], Completion(state='failed', result={'cleanup_ok': False},
            module_sha256=job['module_sha256'], cleanup_ok=False))
        result = self.read(self.targets[1]['board_id'])
        self.assertTrue(result['host_quarantined'])
        self.assertEqual(result['allocations'], [])
        self.assertEqual(self.store.batch(waiting['id'])['runs'][0]['state'], 'waiting')

    def test_changed_host_never_relabels_old_measurements(self):
        self.telemetry.append(self.board, HostSample(sampled_at=1, source='linux', cpu_percent=42))
        self.store.heartbeat(self.board, Heartbeat(description=self.description, physical_host_id='d' * 64))
        self.assertEqual(self.read()['history'], [])
        self.telemetry.append(self.board, HostSample(sampled_at=1, source='linux', cpu_percent=7))
        result = self.read()
        self.assertEqual(result['physical_host_id'], 'd' * 64)
        self.assertEqual(result['latest']['cpu_percent'], 7)

    def test_cli_and_mcp_request_contracts(self):
        fake = MagicMock()
        fake.request.return_value = {'board_id': self.board, 'history': []}
        with patch('side_galaxy.cli.Client', return_value=fake), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(main(['telemetry', self.board, '--limit', '3']))
        self.assertEqual(json.loads(output.getvalue())['board_id'], self.board)
        fake.request.assert_called_once_with('GET', f'/api/boards/{self.board}/telemetry?limit=3')
        fake.request.reset_mock()
        with patch('side_galaxy.cli.Client', return_value=fake), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['telemetry', self.board, '--limit', '721']), 1)
        fake.request.assert_not_called()

        async def check_mcp():
            server = create_mcp()
            tools = await server.list_tools()
            telemetry = next(tool for tool in tools if tool.name == 'get_device_telemetry')
            self.assertTrue(telemetry.annotations.readOnlyHint)
            self.assertEqual(telemetry.inputSchema['properties']['limit']['default'], 60)
            with patch('side_galaxy.mcp_server.Client', return_value=fake):
                await server.call_tool('get_device_telemetry', {'board_id': self.board, 'limit': 2})
            fake.request.assert_called_once_with('GET', f'/api/boards/{self.board}/telemetry?limit=2', None, None)
        asyncio.run(check_mcp())


if __name__ == '__main__':
    unittest.main()
