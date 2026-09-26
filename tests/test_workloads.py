import base64
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import warnings
import zipfile

import httpx

from side_galaxy.cli import main as cli_main
from side_galaxy.client import Client
from side_galaxy.models import Completion, ExecutionEnvironment, Plan
from side_galaxy.artifacts import Artifacts
from side_galaxy.modules import kvm, linux_process
from side_galaxy.store import Store
from side_galaxy.workload_runner import (MAX_EXPANDED, MAX_LOG, MAX_OUTPUTS, execute,
                                        probe_execution_environment, validate_bundle)

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'src/side_galaxy/workload_runner.py'


def bundle(manifest=None, files=(), raw=None):
    stream = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        warnings.simplefilter('ignore', UserWarning)
        archive.writestr('experiment.json', raw if raw is not None else json.dumps(
            {'schema': 1, 'name': 'test', 'run': [sys.executable, '-c', 'print("hello")']} if manifest is None else manifest))
        for name, data in files:
            archive.writestr(name, data)
    return stream.getvalue()


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_code(self, code, seconds=3, **manifest_fields):
        manifest = {'schema': 1, 'name': 'test', 'run': [sys.executable, '-c', code], **manifest_fields}
        data = bundle(manifest)
        path = self.root / 'code.zip'
        path.write_bytes(data)
        return execute(path, self.root / 'work', seconds, artifact_sha256=hashlib.sha256(data).hexdigest())

    def test_real_example_setup_arguments_environment_and_output(self):
        example = ROOT / 'examples/hello-workload'
        files = [(path.name, path.read_bytes()) for path in example.iterdir() if path.name != 'experiment.json']
        data = bundle(json.loads((example / 'experiment.json').read_text()), files)
        path = self.root / 'example.zip'
        path.write_bytes(data)
        result = execute(path, self.root / 'work', 5, ['--iterations', '17'], {'EXPERIMENT_LABEL': 'override'})
        self.assertNotIn('error', result)
        self.assertEqual([step['phase'] for step in result['steps']], ['setup', 'run'])
        self.assertTrue(result['cleanup_ok'])
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('结果目录已准备', result['stdout'])
        output = result['outputs'][0]
        payload = base64.b64decode(output['data_base64'])
        self.assertEqual(output['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(json.loads(payload)['iterations'], 17)
        self.assertEqual(json.loads(payload)['label'], 'override')

    def test_reject_unsafe_zip_and_invalid_manifest(self):
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        variants = [
            [('..', '')], [('../escape', '')], [('/absolute', '')], [('C:drive', '')],
            [('back\\slash', '')], [('dir/../escape', '')], [('dir//file', '')],
            [('experiment.json', '{}')], [('A', ''), ('a', '')], [('x', ''), ('x/y', '')],
            [(link, 'target')], [('z', '') for _ in range(512)],
        ]
        for files in variants:
            with self.subTest(files=str(files)[:80]), self.assertRaises(ValueError):
                validate_bundle(bundle(files=files))
        for manifest in [[], {}, {'schema': True}, {'schema': 1, 'name': 'x', 'run': ['']},
                         {'schema': 1, 'name': 'x', 'run': ['echo'], 'env': {'x': 1}},
                         {'schema': 1, 'name': 'x', 'run': ['echo'], 'outputs': ['../out']}]:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                validate_bundle(bundle(manifest))
        with self.assertRaises(ValueError):
            validate_bundle(bundle(raw='{"schema":1,"schema":1,"name":"x","run":["echo"]}'))
        with self.assertRaises(ValueError):
            validate_bundle(b'not a zip')

    def test_reject_zip_bomb_and_crc_corruption(self):
        data = bundle(files=[('large', b'0' * (MAX_EXPANDED + 1))])
        self.assertLess(len(data), 100000)
        with self.assertRaises(ValueError):
            validate_bundle(data)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('experiment.json', json.dumps({'schema': 1, 'name': 'x', 'run': ['echo']}))
            archive.writestr('file', b'PAYLOAD')
        data = stream.getvalue().replace(b'PAYLOAD', b'PAYLOAx')
        with self.assertRaises(ValueError):
            validate_bundle(data)

    def test_nonzero_setup_stops_run_and_is_failure(self):
        result = self.run_code('print("should not run")', setup=[[sys.executable, '-c', 'import sys;sys.exit(7)']])
        self.assertEqual(result['exit_code'], 7)
        self.assertIn('nonzero', result['error'])
        self.assertEqual(len(result['steps']), 1)
        self.assertTrue(result['cleanup_ok'])

    def test_timeout_reaps_process_and_reports_failure(self):
        result = self.run_code('import os,time;print(os.getpid(),flush=True);time.sleep(30)', seconds=0.2)
        self.assertIn('TimeoutError', result['error'])
        self.assertTrue(result['cleanup_ok'])
        with self.assertRaises(ProcessLookupError):
            os.kill(int(result['stdout'].strip()), 0)

    def test_timeout_cleans_a_real_process_tree(self):
        code = '\n'.join([
            'import subprocess,signal,sys,time,os',
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])',
            'def stopped(signum, frame):',
            '    child.wait(timeout=2)',
            '    raise SystemExit(0)',
            'signal.signal(signal.SIGTERM,stopped)',
            'print(child.pid,flush=True)',
            'time.sleep(30)',
        ])
        result = self.run_code(code, seconds=.3)
        self.assertIn('TimeoutError', result['error'])
        self.assertTrue(result['cleanup_ok'])
        self.assertTrue(result['cleanup'][0]['group_gone'])
        with self.assertRaises(ProcessLookupError):
            os.kill(int(result['stdout'].strip()), 0)

    def test_sigterm_returns_json_and_reaps_experiment(self):
        data = bundle({'schema': 1, 'name': 'cancel', 'run': [sys.executable, '-c',
                      'import os,time,pathlib;pathlib.Path("ready").write_text(str(os.getpid()));time.sleep(30)']})
        path = self.root / 'cancel.zip'
        path.write_bytes(data)
        workspace = self.root / 'work'
        process = subprocess.Popen([sys.executable, str(RUNNER), '--bundle', str(path), '--workspace', str(workspace),
                                    '--plan', '{"duration_seconds":30}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not (workspace / 'ready').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue((workspace / 'ready').exists())
            pid = int((workspace / 'ready').read_text())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            result = json.loads(stdout)
            self.assertEqual(stderr, b'')
            self.assertIn('cancelled', result['error'])
            self.assertTrue(result['cleanup_ok'])
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_output_and_log_limits_are_explicit(self):
        result = self.run_code('import os;os.write(1,b"x"*200000);os.write(2,b"y"*200000)')
        self.assertEqual(len(result['stdout'].encode()), MAX_LOG)
        self.assertEqual(len(result['stderr'].encode()), MAX_LOG)
        self.assertTrue(result['logs_truncated'])
        self.assertEqual(result['stdout_bytes'], 200000)
        self.assertEqual(result['stderr_bytes'], 200000)
        self.assertNotIn('error', result)

    def test_unsafe_or_oversized_outputs_are_failures(self):
        for index, code in enumerate([
            'import pathlib;pathlib.Path("out").symlink_to("/etc/hosts")',
            'import os;os.mkfifo("out")',
            'import pathlib;pathlib.Path("out").write_bytes(b"x"*' + str(MAX_OUTPUTS + 1) + ')',
            'pass',
        ]):
            data = bundle({'schema': 1, 'name': 'outputs', 'run': [sys.executable, '-c', code], 'outputs': ['out']})
            path = self.root / ('output' + str(index) + '.zip')
            path.write_bytes(data)
            with self.subTest(index=index):
                result = execute(path, self.root / ('work' + str(index)), 3)
                self.assertIn('error', result)
                self.assertEqual(result['outputs'], [])
                self.assertTrue(result['cleanup_ok'])

    def test_declared_hash_mismatch_never_starts(self):
        path = self.root / 'bundle.zip'
        path.write_bytes(bundle())
        result = execute(path, self.root / 'work', 3, artifact_sha256='0' * 64)
        self.assertIn('SHA-256 mismatch', result['error'])
        self.assertEqual(result['exit_code'], 125)
        self.assertEqual(result['steps'], [])
        self.assertFalse((self.root / 'work').exists())

    def test_uncertain_cleanup_is_not_success(self):
        with patch('side_galaxy.workload_runner._cleanup', return_value=False):
            result = self.run_code('print("done")')
        self.assertFalse(result['cleanup_ok'])
        self.assertIn('cleanup', result['error'])

    def test_pack_rejects_fifo_without_blocking(self):
        directory = self.root / 'experiment'
        directory.mkdir()
        (directory / 'experiment.json').write_text(json.dumps({'schema': 1, 'name': 'fifo', 'run': ['echo', 'test']}))
        os.mkfifo(directory / 'pipe')
        output = self.root / 'packed.zip'
        result = subprocess.run([sys.executable, '-m', 'side_galaxy.cli', 'pack', str(directory),
                                 '--output', str(output)], capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Only regular experiment files', result.stderr)
        self.assertFalse(output.exists())

    def test_pack_rejects_expanded_total_before_reading_next_compressible_file(self):
        directory = self.root / 'experiment'
        directory.mkdir()
        for name in ('a-zero.bin', 'b-zero.bin'):
            # Sparse zero-filled files compress well, so the ZIP size is not the relevant limit.
            with (directory / name).open('wb') as stream:
                stream.truncate(MAX_EXPANDED * 5 // 8)
        (directory / 'experiment.json').write_text(json.dumps({'schema': 1, 'name': 'large', 'run': ['echo']}))
        output = self.root / 'packed.zip'
        written = []
        original_write = zipfile.ZipFile.write

        def track_write(archive, filename, *args, **kwargs):
            written.append(Path(filename).name)
            return original_write(archive, filename, *args, **kwargs)

        error = io.StringIO()
        with patch.object(zipfile.ZipFile, 'write', track_write), redirect_stderr(error):
            code = cli_main(['pack', str(directory), '--output', str(output)])
        self.assertEqual(code, 1)
        self.assertIn('expanded size', error.getvalue())
        self.assertEqual(written, ['a-zero.bin'])
        self.assertFalse(output.exists())

    def test_completion_rejects_oversized_corrupt_or_excessive_outputs(self):
        def item(value, name='output.bin'):
            return {'path': name, 'size': len(value), 'sha256': hashlib.sha256(value).hexdigest(),
                    'data_base64': base64.b64encode(value).decode()}

        valid = item(b'hello')
        oversized = item(b'x' * (MAX_OUTPUTS + 1))
        total_overflow = [item(b'x' * (MAX_OUTPUTS // 2 + 1), name) for name in ('first.bin', 'second.bin')]
        variants = [[oversized], total_overflow, [{**valid, 'sha256': '0' * 64}],
                    [item(b'', str(index) + '.bin') for index in range(33)]]
        for index, outputs in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                Completion(state='succeeded', result={'outputs': outputs}, module_sha256='a' * 64)
        accepted = Completion(state='succeeded', result={'outputs': [valid]}, module_sha256='a' * 64)
        self.assertEqual(accepted.result['outputs'], [valid])

    def test_client_bounds_download_before_reading_full_response(self):
        class LargeStream(httpx.SyncByteStream):
            def __init__(self):
                self.chunks_read = 0
                self.closed = False

            def __iter__(self):
                for _ in range(20):
                    self.chunks_read += 1
                    yield b'x' * 65536

            def close(self):
                self.closed = True

        stream = LargeStream()
        client = Client('http://127.0.0.1')
        client.http.close()
        client.http = httpx.Client(base_url='http://127.0.0.1', transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream, headers={'X-Content-SHA256': '0' * 64})))
        try:
            with self.assertRaisesRegex(ValueError, 'Output exceeds size limit'):
                client.download_output('run', 0)
            self.assertEqual(stream.chunks_read, MAX_OUTPUTS // 65536 + 1)
            self.assertTrue(stream.closed)
        finally:
            client.http.close()

    def test_artifact_cache_tampering_and_key_validation(self):
        artifacts = Artifacts(self.root / 'artifacts')
        data = bundle()
        entry = artifacts.put(data)
        self.assertEqual(artifacts.get(entry['sha256']).read_bytes(), data)
        with patch('side_galaxy.artifacts.validate_bundle', side_effect=AssertionError('unnecessary ZIP reread')):
            self.assertEqual(artifacts.list(), [entry])
        reopened = Artifacts(self.root / 'artifacts')
        self.assertEqual(reopened.list(), [entry])
        artifacts.get(entry['sha256']).write_bytes(b'tampered')
        with self.assertRaises(KeyError):
            artifacts.get(entry['sha256'])
        self.assertEqual(artifacts.list(), [])
        for digest in ('../etc/passwd', 'A' * 64, None):
            with self.assertRaises(KeyError):
                artifacts.get(digest)
        artifacts.put(data)
        self.assertEqual(artifacts.list(), [entry])

    def test_portability_manifest_rejects_ambiguous_or_unbounded_requirements(self):
        manifest = {'schema': 1, 'name': 'portability', 'run': ['echo']}
        for requirements in [None, [], {'unknown': []}, {'architectures': []},
                             {'architectures': ['arm64']}, {'architectures': ['aarch64', 'aarch64']},
                             {'architectures': [{}]}, {'os': 'Linux'}, {'os': False},
                             {'commands': ['/usr/bin/cc']}, {'commands': ['cc', 'cc']},
                             {'commands': ['x' * 65]}, {'commands': [str(i) for i in range(33)]}]:
            with self.subTest(requirements=requirements), self.assertRaises(ValueError):
                validate_bundle(bundle({**manifest, 'requires': requirements}))
        valid = {'architectures': ['aarch64', 'x86_64'], 'os': 'linux', 'commands': ['cc', 'python3']}
        self.assertEqual(validate_bundle(bundle({**manifest, 'requires': valid}))['requires'], valid)
        self.assertNotIn('requires', validate_bundle(bundle(manifest)))

    def test_runner_rechecks_requirements_before_any_setup(self):
        environment = probe_execution_environment('')
        requirements = [({'architectures': ['incompatible']}, 'architecture mismatch'),
                        ({'os': 'incompatible'}, 'OS mismatch'),
                        ({'commands': ['side-galaxy-command-does-not-exist']}, 'command missing')]
        for index, (requires, error) in enumerate(requirements):
            with self.subTest(requires=requires):
                path = self.root / (str(index) + '.zip')
                path.write_bytes(bundle({'schema': 1, 'name': 'recheck', 'requires': requires,
                                         'setup': [[sys.executable, '-c', 'open("started","w").close()']],
                                         'run': [sys.executable, '-c', 'print("not reached")']}))
                workspace = self.root / ('work' + str(index))
                result = execute(path, workspace, 3)
                self.assertIn(error, result['error'])
                self.assertEqual(result['exit_code'], 125)
                self.assertEqual(result['steps'], [])
                self.assertTrue(result['cleanup_ok'])
                self.assertFalse((workspace / 'started').exists())
        result = self.run_code('print("compatible")', requires={
            'architectures': [environment['architecture']], 'os': environment['os']})
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['stdout'].strip(), 'compatible')

    def test_runner_checks_effective_path_and_inventory_hides_directories(self):
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'present').write_text('#!/bin/sh\nexit 0\n')
        (tools / 'present').chmod(0o700)
        (tools / 'not-executable').write_text('data')
        environment = probe_execution_environment(str(tools))
        self.assertEqual(environment['commands'], ['present'])
        self.assertTrue(environment['commands_complete'])
        self.assertNotIn(str(tools), json.dumps(environment))
        path = self.root / 'custom-path.zip'
        path.write_bytes(bundle({'schema': 1, 'name': 'path', 'requires': {'commands': ['present']},
                                 'run': [sys.executable, '-c', 'print("effective path")']}))
        result = execute(path, self.root / 'work', 3, environment={'PATH': str(tools)})
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['execution_environment']['commands'], ['present'])
        result = execute(path, self.root / 'missing-path-work', 3, environment={'PATH': str(self.root / 'missing')})
        self.assertIn('command missing', result['error'])
        self.assertEqual(result['steps'], [])

    def test_probe_architecture_aliases_inventory_limit_and_model_bounds(self):
        from types import SimpleNamespace

        class Entries:
            def __enter__(self):
                return (SimpleNamespace(name='tool' + str(i), path='/bin/tool' + str(i),
                                        is_file=lambda: True) for i in range(4097))

            def __exit__(self, *args):
                pass

        with patch('os.scandir', return_value=Entries()), patch('os.access', return_value=True), \
             patch('platform.machine', return_value='arm64'), patch('struct.calcsize', return_value=8):
            environment = probe_execution_environment('/bin')
        self.assertEqual(environment['architecture'], 'aarch64')
        self.assertEqual(len(environment['commands']), 4096)
        self.assertFalse(environment['commands_complete'])
        ExecutionEnvironment(**environment)
        with self.assertRaises(ValueError):
            ExecutionEnvironment(**{**environment, 'commands': environment['commands'] + ['overflow']})
        with self.assertRaises(ValueError):
            ExecutionEnvironment(**{**environment, 'commands': ['/bin/cc']})

    def test_linux_and_kvm_share_probe_but_kvm_executes_it_in_guest(self):
        local = linux_process.execution_environment()
        self.assertEqual(local['architecture'], probe_execution_environment('')['architecture'])
        guest = {'architecture': 'x86_64', 'os': 'linux', 'commands': ['cc'], 'commands_complete': True}

        def command(domain, argv):
            self.assertEqual(domain, 'guest-domain')
            self.assertEqual(argv[0], '-c')
            # The exact source sent to QGA also runs independently of package imports.
            completed = subprocess.run([sys.executable, *argv], text=True, capture_output=True, timeout=5, check=True)
            self.assertEqual(json.loads(completed.stdout)['architecture'], local['architecture'])
            return {'out-data': base64.b64encode(json.dumps(guest).encode()).decode(), 'exitcode': 0}

        with patch.object(kvm, 'guest_command', side_effect=command):
            self.assertEqual(kvm.guest_environment('guest-domain'), guest)
        with patch.object(kvm, 'guest_command', return_value={'out-truncated': True}):
            with self.assertRaisesRegex(ValueError, 'truncated'):
                kvm.guest_environment('guest-domain')
        with patch.object(kvm, 'domain', return_value='guest-domain'), \
             patch.object(kvm, 'virsh', return_value='running'), \
             patch.object(kvm.os, 'sched_getaffinity', return_value={0, 1}, create=True), \
             patch.object(kvm, 'guest_available', return_value=True), \
             patch.object(kvm, 'guest_environment', side_effect=ValueError('probe unavailable')):
            description = kvm.describe()
        self.assertIsNone(description['execution_environment'])
        self.assertIn('workload', description['templates'])

    def test_store_passes_verified_requirements_and_legacy_default_to_native(self):
        store = Store.__new__(Store)
        store.artifacts = Artifacts(self.root / 'artifacts')
        requires = {'architectures': ['aarch64'], 'os': 'linux', 'commands': ['cc']}
        manifest = {'schema': 1, 'name': 'portable', 'run': ['cc'], 'requires': requires}
        artifact = store.artifacts.put(bundle(manifest))
        plan = Plan(boards=['target'], template='workload', interference_cpus=[], artifact_sha256=artifact['sha256'])
        payload = store._plan(plan)
        self.assertTrue(payload['artifact_available'])
        self.assertEqual(payload['artifact_requirements'], requires)
        self.assertEqual(store.artifacts.list()[0]['manifest']['requires'], requires)
        store.artifacts.get(artifact['sha256']).write_bytes(b'tampered')
        self.assertFalse(store._plan(plan)['artifact_available'])
        legacy = store.artifacts.put(bundle())
        plan.artifact_sha256 = legacy['sha256']
        self.assertEqual(store._plan(plan)['artifact_requirements'], {})

    @unittest.skipUnless(shutil.which('cc'), 'local C compiler unavailable')
    def test_c_example_compiles_and_reports_actual_local_environment(self):
        source = ROOT / 'examples/c-portability/main.c'
        executable = self.root / 'portability-check'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable)],
                       capture_output=True, timeout=30, check=True)
        completed = subprocess.run([str(executable), '--iterations', '17'], cwd=self.root,
                                   capture_output=True, text=True, timeout=5, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result, json.loads((self.root / 'result.json').read_text()))
        self.assertEqual(result['iterations'], 17)
        self.assertEqual(result['os'], platform.system())
        self.assertEqual(result['machine'], platform.machine())
        self.assertNotIn(str(self.root), completed.stdout)


if __name__ == '__main__':
    unittest.main()
