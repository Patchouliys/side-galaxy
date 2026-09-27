"""Log protocol and local subprocess checks; these are not hardware acceptance."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from side_galaxy.api import create_app
from side_galaxy.models import Completion, Description, Enrollment, Heartbeat, Plan
from side_galaxy.run_logs import MAX_EVENTS, MAX_LOG_BYTES, RunLogs
from side_galaxy.runtime import Agent, Execution, LocalClient
from side_galaxy.workload_runner import emit_log


class RunningLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = create_app(self.root / 'logs.db', token='operator-test-token-with-24-chars',
                              read_token='reader-test-token-with-24-chars', background=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.store = self.app.state.store
        self.reader = {'Authorization': 'Bearer reader-test-token-with-24-chars'}
        self.description = Description(name='Log protocol runtime', mode='linux-process',
            cpus=[0, 1], reserved_cpus=[0], memory_mib=512,
            capabilities=['cpu-affinity', 'memory-limit'], templates=['cpu-contention'],
            module_sha256='a' * 64)
        self.boards = [self.store.enroll(Enrollment(name=name)) for name in ('first', 'second')]
        for board in self.boards:
            self.store.heartbeat(board['board_id'], Heartbeat(description=self.description))
        self.board = self.boards[0]['board_id']
        self.plan = Plan(boards=[self.board], interference_cpus=[], duration_seconds=10)
        self.batch = self.store.submit(self.plan, 'logging')
        self.job = self.store.poll(self.board)
        self.route = f'/api/agent/{self.board}/runs/{self.job["id"]}/logs'
        self.read_route = f'/api/runs/{self.job["id"]}/logs'
        self.headers = {'Authorization': 'Bearer ' + self.boards[0]['agent_token']}
        self.logs = RunLogs(self.store)

    @staticmethod
    def event(sequence, text='output\n', stream='stdout'):
        return {'sequence': sequence, 'stream': stream, 'text': text}

    def append(self, events, **kwargs):
        return self.client.post(self.route, json={'events': events, **kwargs}, headers=self.headers)

    def read(self, after=0):
        response = self.client.get(self.read_route, params={'after': after}, headers=self.reader)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_reader_and_board_scoped_authorization_and_validation(self):
        body = {'events': [self.event(1)]}
        self.assertEqual(self.client.get(self.read_route).status_code, 401)
        self.assertEqual(self.client.post(self.route, json=body).status_code, 403)
        self.assertEqual(self.client.post(self.route, json=body, headers=self.reader).status_code, 403)
        other = self.boards[1]
        wrong_headers = {'Authorization': 'Bearer ' + other['agent_token']}
        self.assertEqual(self.client.post(self.route, json=body, headers=wrong_headers).status_code, 403)
        wrong_owner = self.route.replace(self.board, other['board_id'])
        self.assertEqual(self.client.post(wrong_owner, json=body, headers=wrong_headers).status_code, 404)
        for events in ([self.event(0)], [self.event(1, stream='shell')],
                       [self.event(1, text='x' * 2049)], [self.event(n) for n in range(1, 66)]):
            with self.subTest(events=len(events), first=events[0]['sequence']):
                self.assertEqual(self.append(events).status_code, 422)
        self.assertEqual(self.client.get(self.read_route, params={'after': -1}, headers=self.reader).status_code, 422)
        self.assertEqual(self.read()['next_sequence'], 0)

    def test_duplicate_gap_and_conflict_are_atomic(self):
        self.assertEqual(self.append([self.event(1), self.event(3)]).status_code, 409)
        self.assertEqual(self.read()['events'], [])
        self.assertEqual(self.append([self.event(1)]).json()['next_sequence'], 1)
        self.assertEqual(self.append([self.event(1), self.event(2, stream='stderr')]).json()['next_sequence'], 2)
        self.assertEqual([e['sequence'] for e in self.read()['events']], [1, 2])
        self.assertEqual(self.append([self.event(3), self.event(1, text='changed')]).status_code, 409)
        self.assertEqual(self.read()['next_sequence'], 2)
        self.assertEqual(self.append([self.event(2, stream='stdout')]).status_code, 409)
        self.assertEqual(self.append([self.event(4)]).status_code, 409)

    def test_cursor_pagination_and_storage_byte_bound(self):
        # Four-byte text makes the byte limit distinct from character count.
        text = '\U0001f30c' * 512
        count = MAX_LOG_BYTES // len(text.encode()) + 2
        for start in range(1, count + 1, 64):
            response = self.append([self.event(n, text) for n in range(start, min(start + 64, count + 1))])
            self.assertEqual(response.status_code, 200, response.text)
        first = self.read()
        self.assertEqual(len(first['events']), 128)
        self.assertEqual(first['next_sequence'], 128)
        second = self.read(first['next_sequence'])
        self.assertEqual(second['events'][0]['sequence'], 129)
        final = self.read(second['next_sequence'])
        self.assertEqual(final['events'], [])
        self.assertEqual(final['next_sequence'], count)
        self.assertTrue(final['truncated'])
        # Even omitted text retains a bounded fingerprint, so retries remain
        # idempotent and cannot replace a previously acknowledged event.
        self.assertEqual(self.append([self.event(count, text)]).status_code, 200)
        self.assertEqual(self.append([self.event(count, 'different')]).status_code, 409)
        with self.store.tx() as db:
            state = db.execute('SELECT * FROM run_log_state WHERE run_id=?', (self.job['id'],)).fetchone()
            total = db.execute('SELECT SUM(length(CAST(text AS BLOB))) FROM run_log_events WHERE run_id=?', (self.job['id'],)).fetchone()[0]
        self.assertLessEqual(state['bytes'], MAX_LOG_BYTES)
        self.assertEqual(total, state['bytes'])

    def test_empty_events_are_count_bounded_and_truncation_is_sticky(self):
        for start in range(1, MAX_EVENTS + 2, 64):
            events = [self.event(n, '') for n in range(start, min(start + 64, MAX_EVENTS + 2))]
            result = self.logs.append(self.board, self.job['id'], events)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['next_sequence'], MAX_EVENTS + 1)
        self.assertTrue(self.logs.append(self.board, self.job['id'], [])['truncated'])
        with self.store.tx() as db:
            count = db.execute('SELECT count(*) FROM run_log_events WHERE run_id=?', (self.job['id'],)).fetchone()[0]
        self.assertLessEqual(count, MAX_EVENTS)
        self.assertEqual(self.append([self.event(MAX_EVENTS + 1, '')]).status_code, 409)

    def test_log_delivery_does_not_release_resources_or_replace_final_result(self):
        waiting = self.store.submit(self.plan, 'wait-for-cleanup', enqueue=True)
        self.assertEqual(self.append([self.event(1)], truncated=True).status_code, 200)
        self.assertEqual(self.store.batch(waiting['id'])['runs'][0]['state'], 'waiting')
        self.assertEqual(self.store.batch(self.batch['id'])['runs'][0]['state'], 'running')
        final = {'stdout': 'complete stdout\n', 'stderr': 'complete stderr\n', 'cleanup_ok': False}
        self.store.finish(self.board, self.job['id'], Completion(state='failed', result=final,
            module_sha256=self.job['module_sha256'], cleanup_ok=False))
        self.assertEqual(self.store.batch(self.batch['id'])['runs'][0]['result'], final)
        self.assertEqual(self.store.batch(waiting['id'])['runs'][0]['state'], 'waiting')
        self.assertTrue(next(board for board in self.store.boards() if board['id'] == self.board)['quarantined'])
        self.assertEqual(self.append([self.event(2)]).status_code, 200)
        self.assertEqual(self.store.batch(self.batch['id'])['runs'][0]['result'], final)
        self.assertEqual(self.read()['events'][0]['text'], 'output\n')

    def test_lost_run_accepts_late_logs_without_releasing_quarantine(self):
        with self.store.tx() as db:
            db.execute("UPDATE runs SET state='lost' WHERE id=?", (self.job['id'],))
            db.execute('UPDATE boards SET quarantined=1 WHERE id=?', (self.board,))
        self.assertEqual(self.append([self.event(1, 'last known output')]).status_code, 200)
        self.assertEqual(self.store.batch(self.batch['id'])['runs'][0]['state'], 'lost')
        self.assertTrue(next(board for board in self.store.boards() if board['id'] == self.board)['quarantined'])

    def test_real_subprocess_output_arrives_before_completion_and_keeps_final_logs(self):
        release = self.root / 'release'
        module = self.root / 'module.py'
        module.write_text('''import json, os, pathlib, sys, time
request = json.load(sys.stdin)
fd = int(os.environ['SG_EVENT_FD'])
os.write(fd, b'not-json\\n')
os.write(fd, (json.dumps({'stream':'stdout','text':'live before exit\\n'})+'\\n').encode())
deadline = time.monotonic() + 10
while not pathlib.Path(RELEASE).exists() and time.monotonic() < deadline:
    time.sleep(.01)
print(json.dumps({'stdout':'final output\\n','stderr':'final warning\\n','cleanup_ok':True}))
'''.replace('RELEASE', repr(str(release))))
        execution = Execution(module, {**self.job, 'mode': 'linux-process'})
        try:
            deadline = time.monotonic() + 5
            while not execution.log_events and time.monotonic() < deadline:
                self.assertIsNone(execution.poll())
                time.sleep(.01)
            self.assertIsNone(execution.process.poll())
            self.assertEqual(execution.log_events[0]['text'], 'live before exit\n')
            self.assertTrue(execution.logs_truncated, 'Malformed transport must be visible')
            self.assertEqual(self.append(execution.log_events).status_code, 200)
            self.assertEqual(self.read()['events'][0]['text'], 'live before exit\n')
            release.touch()
            completion = None
            while completion is None and time.monotonic() < deadline:
                completion = execution.poll()
                if completion is None: time.sleep(.01)
            self.assertIsNotNone(completion)
            self.assertTrue(completion.cleanup_ok)
            self.assertEqual(completion.result['stdout'], 'final output\n')
            self.assertEqual(completion.result['stderr'], 'final warning\n')
            self.store.finish(self.board, self.job['id'], completion)
            self.assertEqual(self.store.batch(self.batch['id'])['runs'][0]['state'], 'succeeded')
        finally:
            release.touch()
            if execution.event_fd is not None:
                execution.stop(cancelled=True)
                while execution.poll() is None: time.sleep(.01)

    def test_emitter_preserves_utf8_at_transport_chunk_boundary(self):
        writes = []
        payload = ('x' * 511 + '\U0001f30c' + ' end\n').encode()
        with patch.dict(os.environ, {'SG_EVENT_FD': '123'}), \
             patch('side_galaxy.workload_runner.os.write', side_effect=lambda fd, data: writes.append(data) or len(data)):
            emit_log('stdout', payload)
            emit_log('stdout', b'', final=True)
        combined = ''.join(json.loads(line)['text'] for line in writes)
        self.assertEqual(combined, payload.decode())

    def test_emitter_preserves_partial_characters_across_reads_and_flushes_eof(self):
        writes = []
        payload = 'before \U0001f30c after'.encode()
        with patch.dict(os.environ, {'SG_EVENT_FD': '124'}), \
             patch('side_galaxy.workload_runner.os.write', side_effect=lambda fd, data: writes.append(data) or len(data)):
            emit_log('stdout', payload[:8])
            emit_log('stderr', b'other stream')
            emit_log('stdout', payload[8:])
            emit_log('stdout', b'\xe2', final=True)
            emit_log('stderr', b'', final=True)
        events = [json.loads(line) for line in writes]
        self.assertEqual(''.join(e['text'] for e in events if e['stream'] == 'stdout'), payload.decode() + '\ufffd')
        self.assertEqual(''.join(e['text'] for e in events if e['stream'] == 'stderr'), 'other stream')

    def test_agent_retries_complete_tail_without_blocking_completion_on_network(self):
        started, release = threading.Event(), threading.Event()
        owner = self

        class InterruptedLogs(LocalClient):
            fail_once = True

            def logs(self, *args):
                if self.fail_once:
                    self.fail_once = False
                    started.set()
                    if not release.wait(5): raise TimeoutError('Test did not release transport')
                    raise ValueError('Reply lost')
                return super().logs(*args)

        modules = SimpleNamespace(current=(self.root / 'unused-module.py', self.description),
                                  reload=lambda **kwargs: None, error=None)
        agent = Agent(InterruptedLogs(self.store), self.board, modules)
        completion = Completion(state='succeeded', result={'stdout': 'final remains independent', 'cleanup_ok': True},
                                module_sha256=self.job['module_sha256'], cleanup_ok=True)
        agent.execution = SimpleNamespace(job=self.job, log_events=[self.event(n, f'event {n}\n') for n in range(1, 151)],
            logs_truncated=False, logs_suppressed=False, drain_logs=lambda: None,
            poll=lambda: completion, stop=lambda **kwargs: None)
        try:
            agent.tick()
            self.assertTrue(started.wait(1))
            self.assertIsNone(agent.execution)
            # Transport is still blocked, but completion can release a clean run.
            agent.tick()
            final = self.store.batch(self.batch['id'])['runs'][0]
            self.assertEqual(final['state'], 'succeeded')
            self.assertEqual(final['result']['stdout'], 'final remains independent')
            self.assertTrue(final['result']['live_logs_delivery_pending'])
            self.assertTrue(self.store.preflight(self.plan)['valid'])
            release.set()
            deadline = time.monotonic() + 5
            while agent.log_backlog and time.monotonic() < deadline:
                agent.tick()
                time.sleep(.01)
            self.assertFalse(agent.log_backlog)
            first = owner.read()
            second = owner.read(first['next_sequence'])
            events = first['events'] + second['events']
            self.assertEqual([e['sequence'] for e in events], list(range(1, 151)))
        finally:
            release.set()
            agent.shutdown()

    def test_agent_backlog_limit_marks_suppressed_output_in_final_evidence(self):
        modules = SimpleNamespace(current=(self.root / 'unused-module.py', self.description),
                                  reload=lambda **kwargs: None, error=None)
        client = SimpleNamespace(logs=lambda board, run, events, truncated: {'next_sequence': 0})
        agent = Agent(client, self.board, modules)
        agent.log_backlog = {str(n): {'events': [], 'truncated': False, 'reported': False, 'closed': False} for n in range(8)}
        completion = Completion(state='succeeded', result={}, module_sha256=self.job['module_sha256'])
        agent.execution = SimpleNamespace(job=self.job, log_events=[self.event(1)], logs_truncated=False,
            logs_suppressed=False, drain_logs=lambda: None)
        try:
            agent._close_logs(completion)
            self.assertEqual(len(agent.log_backlog), 8)
            self.assertTrue(completion.result['live_logs_truncated'])
            self.assertEqual(agent.execution.log_events, [])
        finally:
            agent.execution = None
            agent.shutdown()


if __name__ == '__main__':
    unittest.main()
