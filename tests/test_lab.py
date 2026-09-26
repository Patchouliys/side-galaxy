import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import uuid

from side_galaxy.lab import EXTRACT_REQUIREMENTS, Lab, _endpoint
from side_galaxy.profiles import profile


def state():
    return {'instance_id': str(uuid.uuid4()), 'arch': 'x86_64', 'cpus': 4,
            'memory_mib': 2048, 'ssh_port': 22222, 'disk_gib': 16, 'stage': 'ready'}


class LabTests(unittest.TestCase):
    def test_restart_confirms_new_boot_and_fresh_agent_after_tunnel_restoration(self):
        for force in (False, True):
            with self.subTest(force=force), tempfile.TemporaryDirectory() as directory:
                lab = Lab(directory)
                item = {**state(), 'board_id': 'board', 'server': 'http://127.0.0.1:7980'}
                lab._write('state.json', item)
                (lab.root / 'disk.qcow2').write_bytes(b'preserved disk')
                before, after = str(uuid.uuid4()), str(uuid.uuid4())
                boots, events = iter([before, before, after, after]), []
                def remote(item, script, **kwargs):
                    if script.startswith('cat /proc/'):
                        return subprocess.CompletedProcess([], 0, next(boots), '')
                    events.append(script.strip())
                    return subprocess.CompletedProcess([], 255 if 'reboot' in script else 0, '', '')
                def run(command, **kwargs):
                    if 'exit' in command: events.append('close-tunnel')
                    if '-R' in command:
                        events.append('restore-tunnel')
                        self.assertIn('127.0.0.1:17980:127.0.0.1:7980', command)
                    return subprocess.CompletedProcess(command, 1 if 'check' in command else 0, '', '')
                client = Mock()
                client.request.side_effect = [[{'id': 'board', 'seen': seen, 'description': {'mode': 'linux-process'},
                                               'reload_requested': 1, 'reload_ack': ack, 'reload_error': error}]
                                              for seen, ack, error in ((999, 1, None), (1001, 0, None),
                                                                       (1002, 1, 'validation failed'), (1003, 1, None))]
                with patch.object(lab, '_running', return_value='running'), patch.object(lab, '_remote', side_effect=remote), patch.object(lab, '_run', side_effect=run), patch.object(lab, '_qmp', side_effect=lambda state, command: events.append(command)), patch.object(lab, '_install') as install, patch('side_galaxy.lab.Client', return_value=client), patch('side_galaxy.lab.time.time', return_value=1000), patch('side_galaxy.lab.time.sleep'):
                    result = lab.restart(force=force, token='operator')
                self.assertTrue(result['agent_ready'])
                self.assertEqual((result['boot_id_before'], result['boot_id_after']), (before, after))
                self.assertEqual(result['board_id'], item['board_id'])
                self.assertEqual(result['instance_id'], item['instance_id'])
                self.assertNotIn(directory, json.dumps(result))
                self.assertEqual(lab._read()['stage'], 'ready')
                self.assertEqual((lab.root / 'disk.qcow2').read_bytes(), b'preserved disk')
                self.assertEqual(client.request.call_count, 4)
                install.assert_not_called()
                if force:
                    self.assertEqual(events[0], 'system_reset')
                    self.assertFalse(any('stop ' in event or 'reboot ' in event for event in events))
                else:
                    self.assertEqual(events[:2], ['systemctl stop side-galaxy-agent.service', 'systemctl reboot --no-block'])
                    self.assertNotIn('system_reset', events)
                self.assertLess(events.index('close-tunnel'), events.index('restore-tunnel'))
                self.assertLess(events.index('restore-tunnel'), events.index('systemctl is-active --quiet side-galaxy-agent.service'))

    def test_restart_wrong_identity_never_touches_ssh_or_resets_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            lab, item = Lab(directory), {**state(), 'board_id': 'board', 'server': 'http://127.0.0.1:7980'}
            lab._write('state.json', item)
            conn, seen = self.qmp_server(lab, str(uuid.uuid4()))
            with patch('side_galaxy.lab.socket.socket', return_value=conn), patch.object(lab, '_run') as run, self.assertRaisesRegex(ValueError, 'identity'):
                lab.restart(force=True)
            run.assert_not_called()
            self.assertEqual(seen, ['qmp_capabilities', 'query-uuid'])
            self.assertEqual(lab._read()['stage'], 'restart-failed')

    def test_restart_timeout_never_reports_ready_without_changed_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            lab, item = Lab(directory), {**state(), 'board_id': 'board', 'server': 'http://127.0.0.1:7980'}
            lab._write('state.json', item)
            clock = iter(range(1000))
            with patch.object(lab, '_running', return_value='running'), patch.object(lab, '_boot_id', return_value=str(uuid.uuid4())), patch.object(lab, '_qmp') as qmp, patch.object(lab, '_run'), patch.object(lab, '_tunnel') as tunnel, patch('side_galaxy.lab.time.monotonic', side_effect=lambda: next(clock)), patch('side_galaxy.lab.time.sleep'), self.assertRaisesRegex(ValueError, 'timed out'):
                lab.restart(force=True, timeout=30)
            qmp.assert_called_once_with(unittest.mock.ANY, 'system_reset')
            tunnel.assert_not_called()
            self.assertEqual(lab._read()['stage'], 'restart-failed')

    def test_cli_restart_uses_shared_async_api_instead_of_bypassing_maintenance(self):
        from side_galaxy.lab_cli import add_parser, execute
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command'))
        args = parser.parse_args(['lab', 'restart', '--force'])
        lab, client = Mock(), Mock()
        lab.status.return_value = {'instance_id': 'managed-instance'}
        lab._read.return_value = {'server': 'http://127.0.0.1:7980'}
        client.request.return_value = {'operation_id': 'operation', 'state': 'running'}
        with patch('side_galaxy.lab.Lab', return_value=lab), patch('side_galaxy.client.Client', return_value=client):
            self.assertEqual(execute(args)['state'], 'running')
            client.request.assert_called_once_with('POST', '/api/labs/managed-instance/restart', {'force': True})
            lab.restart.assert_not_called()
            client.request.side_effect = ValueError('HTTP 404: Not found')
            with self.assertRaisesRegex(ValueError, 'Register this lab directory'):
                execute(args)

    def test_qemu_argv_keeps_paths_structured_and_management_local(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(Path(directory) / 'disk, space;$x')
            item = state()
            command = lab._command(item, '/usr/bin/qemu-system-x86_64', accel='tcg')
            blocks = [json.loads(command[i + 1]) for i, token in enumerate(command) if token == '-blockdev']
            self.assertEqual(blocks[0]['file']['filename'], str(lab.root / 'disk.qcow2'))
            self.assertTrue(blocks[1]['read-only'])
            self.assertIn('user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:22222-:22', command)
            self.assertEqual(command[command.index('-uuid') + 1], item['instance_id'])
            self.assertIn('disk,, space;$x', command[command.index('-qmp') + 1])
            self.assertNotIn('-enable-kvm', command)
            self.assertEqual(profile('boards', 'qemu-virt')['architecture'], 'detected')

    def test_bad_image_digest_has_no_state_or_process_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'base.qcow2'
            source = Path(directory) / 'source.tar.gz'
            image.write_bytes(b'image')
            source.write_bytes(b'source')
            lab = Lab(Path(directory) / 'new')
            with patch('side_galaxy.lab.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                lab.up(image=image, image_sha512='0' * 128, source_archive=source)
            run.assert_not_called()
            self.assertFalse(lab.root.exists())

    def test_seed_contains_generic_identity_only_and_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(directory)
            commands = []
            def execute(command, **kwargs):
                commands.append(command)
                if command[0] == 'ssh-keygen':
                    (lab.root / 'id_ed25519').write_text('PRIVATE KEY')
                    (lab.root / 'id_ed25519.pub').write_text('ssh-ed25519 AAAATEST side-galaxy-lab')
                if command[0] == 'hdiutil': (lab.root / 'seed.iso').write_bytes(b'ISO')
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(lab, '_run', side_effect=execute), patch('side_galaxy.lab.shutil.which', return_value=None), patch('side_galaxy.lab.platform.system', return_value='Darwin'):
                lab._seed(state())
            text = (lab.root / 'seed/user-data').read_text()
            user = json.loads(text.removeprefix('#cloud-config\n'))
            self.assertEqual(user['hostname'], 'side-galaxy-lab')
            self.assertEqual(user['users'][0]['name'], 'galaxy')
            self.assertFalse(user['ssh_pwauth'])
            self.assertNotIn('PRIVATE KEY', text)
            self.assertNotIn(directory, text)
            self.assertEqual(commands[0][commands[0].index('-C') + 1], 'side-galaxy-lab')
            for name in ('id_ed25519', 'seed/user-data', 'seed/meta-data', 'seed.iso'):
                self.assertEqual((lab.root / name).stat().st_mode & 0o077, 0)

    def qmp_server(self, lab, identity):
        conn, stream = MagicMock(), MagicMock()
        conn.__enter__.return_value = conn
        conn.makefile.return_value = stream
        stream.__enter__.return_value = stream
        messages = [{'QMP': {'version': {}}}, {'return': {}, 'id': 'qmp_capabilities'},
                    {'event': 'RESUME'}, {'return': {'UUID': identity}, 'id': 'query-uuid'},
                    {'return': {'status': 'running'}, 'id': 'query-status'}]
        stream.readline.side_effect = [(json.dumps(message) + '\n').encode() for message in messages]
        seen = []
        stream.write.side_effect = lambda data: seen.append(json.loads(data)['execute'])
        return conn, seen

    def test_qmp_uuid_verified_before_command(self):
        with tempfile.TemporaryDirectory() as directory:
            lab, item = Lab(directory), state()
            conn, seen = self.qmp_server(lab, item['instance_id'])
            with patch('side_galaxy.lab.socket.socket', return_value=conn):
                self.assertEqual(lab._qmp(item, 'query-status'), {'status': 'running'})
            self.assertEqual(seen, ['qmp_capabilities', 'query-uuid', 'query-status'])

    def test_down_refuses_other_vm_and_does_not_use_pid_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            lab, item = Lab(directory), state()
            lab._write('state.json', item)
            conn, seen = self.qmp_server(lab, str(uuid.uuid4()))
            with patch('side_galaxy.lab.socket.socket', return_value=conn), patch.object(lab, '_run') as run, patch('os.kill') as kill, self.assertRaisesRegex(ValueError, 'identity'):
                lab.down()
            run.assert_not_called()
            kill.assert_not_called()
            self.assertEqual(seen, ['qmp_capabilities', 'query-uuid'])

    def test_status_redacts_private_state_and_ignores_stale_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(directory)
            item = {**state(), 'agent_token': 'secret', 'source_archive': '/private/owner/project.tar.gz',
                    'server': 'http://localhost:7980', 'board_id': 'board'}
            lab._write('state.json', item)
            (lab.root / 'qemu.pid').write_text(str(os.getpid()))
            with patch('os.kill') as kill:
                result = lab.status()
            kill.assert_not_called()
            self.assertEqual(result['status'], 'stopped')
            self.assertFalse(result['synthetic'])
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn('/private/', json.dumps(result))
            self.assertNotIn('server', result)

    def test_down_stops_agent_before_qmp_and_preserves_reusable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            lab, item = Lab(directory), state()
            lab._write('state.json', item)
            (lab.root / 'disk.qcow2').write_bytes(b'disk')
            events = []
            with patch.object(lab, '_running', side_effect=['running', None, None, None, None, None]), patch.object(lab, '_remote', side_effect=lambda *args, **kwargs: events.append('stop-agent')), patch.object(lab, '_qmp', side_effect=lambda item, op: events.append(op)), patch.object(lab, '_run') as run:
                result = lab.down()
            self.assertEqual(events, ['stop-agent', 'system_powerdown'])
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual((lab.root / 'disk.qcow2').read_bytes(), b'disk')
            self.assertEqual(lab._read()['instance_id'], item['instance_id'])
            self.assertIn('exit', run.call_args.args[0])

    def test_timeout_diagnostics_are_kept_in_private_log(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(directory)
            error = subprocess.TimeoutExpired(['ssh'], 1, output=b'compiler started\n', stderr=b'diagnostic\n')
            with patch('side_galaxy.lab.subprocess.run', side_effect=error), self.assertRaisesRegex(ValueError, 'timed out'):
                lab._run(['ssh'], timeout=1)
            log = lab.root / 'bootstrap.log'
            self.assertEqual(log.read_text(), 'compiler started\ndiagnostic\n')
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_repeat_up_reuses_disk_board_and_installed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image, source = root / 'image.qcow2', root / 'source.tar.gz'
            image.write_bytes(b'image')
            source.write_bytes(b'source')
            lab = Lab(root / 'state')
            installed = {'hash': ''}
            client = Mock()
            def request(method, path, data=None):
                if path == '/api/boards' and method == 'POST':
                    self.assertEqual(data, {'name': 'QEMU Linux x86_64', 'board_profile': 'qemu-virt', 'system_profile': 'linux-process'})
                    return {'board_id': 'test-board', 'agent_token': 'secret'}
                if path == '/api/boards':
                    return [{'id': 'test-board', 'status': 'ready', 'description': {'mode': 'linux-process'}}]
                return {'status': 'ok'}
            client.request.side_effect = request
            def remote(item, script, **kwargs):
                result = installed['hash'] if script.startswith('cat ') else ''
                return subprocess.CompletedProcess([], 0, result, '')
            def install(item, path, source_hash, wheels, timeout): installed['hash'] = source_hash
            options = {'image': image, 'image_sha512': hashlib.sha512(b'image').hexdigest(), 'source_archive': source, 'arch': 'x86_64'}
            with patch('side_galaxy.lab._tool', side_effect=lambda value, default: '/usr/bin/' + default), patch('side_galaxy.lab.Client', return_value=client), patch.object(lab, '_prepare') as prepare, patch.object(lab, '_running', return_value='running'), patch.object(lab, '_run', return_value=subprocess.CompletedProcess([], 0, '', '')), patch.object(lab, '_remote', side_effect=remote), patch.object(lab, '_copy'), patch.object(lab, '_tunnel'), patch.object(lab, '_install', side_effect=install) as installer:
                first = lab.up(**options)
                second = lab.up(**options)
                self.assertEqual(first, second)
                self.assertEqual(installer.call_count, 1)
                self.assertEqual(prepare.call_args_list[0].args[0]['instance_id'], first['instance_id'])
                with self.assertRaisesRegex(ValueError, 'settings differ'):
                    lab.up(**{**options, 'cpus': 8})
            self.assertEqual(sum(call.args[:2] == ('POST', '/api/boards') for call in client.request.call_args_list), 1)
            self.assertEqual((lab.root / 'agent.json').stat().st_mode & 0o777, 0o600)
            self.assertNotIn(directory, (lab.root / 'agent.json').read_text())
            self.assertNotIn('secret', json.dumps(second))

    def test_endpoint_rejects_remote_or_credentialed_tunnels(self):
        self.assertEqual(_endpoint('http://127.0.0.1:7980'), ('127.0.0.1', 7980))
        self.assertEqual(_endpoint('http://[::1]:7980'), ('::1', 7980))
        for server in ('http://10.0.2.2:7980', 'http://user:pass@localhost:7980', 'http://localhost/path', 'http://localhost/?token=secret'):
            with self.subTest(server=server), self.assertRaises(ValueError): _endpoint(server)

    def test_source_update_refuses_to_stop_an_agent_with_active_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image, source = root / 'image.qcow2', root / 'source.tar.gz'
            image.write_bytes(b'image')
            source.write_bytes(b'updated source')
            lab = Lab(root / 'state')
            lab.root.mkdir(mode=0o700)
            digest = hashlib.sha512(b'image').hexdigest()
            item = {**state(), 'board_id': 'test-board', 'image_sha512': digest, 'server': 'http://127.0.0.1:7980'}
            lab._write('state.json', item)
            client = Mock()
            client.request.return_value = [{'id': 'test-board', 'active_run': 'active-experiment'}]
            with patch('side_galaxy.lab._tool', side_effect=lambda value, default: '/usr/bin/' + default), patch('side_galaxy.lab.Client', return_value=client), patch.object(lab, '_prepare'), patch.object(lab, '_running', return_value='running'), patch.object(lab, '_run', return_value=subprocess.CompletedProcess([], 0, '', '')), patch.object(lab, '_remote', return_value=subprocess.CompletedProcess([], 0, 'previous source hash', '')) as remote, patch.object(lab, '_tunnel'), patch.object(lab, '_install') as installer:
                with self.assertRaisesRegex(ValueError, 'active experiment'):
                    lab.up(image=image, image_sha512=digest, source_archive=source, arch='x86_64')
            installer.assert_not_called()
            self.assertEqual([call.args[1] for call in remote.call_args_list], ['cat /opt/side-galaxy/source.sha256\n'])

    def test_source_lockfile_extraction_is_bounded_and_rejects_links_or_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.tar.gz', root / 'requirements.txt'
            cases = [('valid', ['package/deploy/requirements.txt'], tarfile.REGTYPE, b'dependency==1 --hash=sha256:123\n'),
                     ('missing', ['package/README.md'], tarfile.REGTYPE, b'no lock'),
                     ('duplicate', ['one/deploy/requirements.txt', 'two/deploy/requirements.txt'], tarfile.REGTYPE, b'lock'),
                     ('link', ['package/deploy/requirements.txt'], tarfile.SYMTYPE, b''),
                     ('oversized', ['package/deploy/requirements.txt'], tarfile.REGTYPE, b'x' * (1024 * 1024 + 1))]
            for name, paths, kind, data in cases:
                with self.subTest(name=name):
                    target.unlink(missing_ok=True)
                    with tarfile.open(source, 'w:gz') as archive:
                        for path in paths:
                            item = tarfile.TarInfo(path)
                            item.type, item.size = kind, len(data)
                            if kind == tarfile.SYMTYPE: item.linkname = '/etc/passwd'
                            archive.addfile(item, io.BytesIO(data))
                    result = subprocess.run([sys.executable, '-c', EXTRACT_REQUIREMENTS, str(source), str(target)], capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, name == 'valid')
                    if name == 'valid': self.assertEqual(target.read_bytes(), data)
                    else:
                        self.assertFalse(target.exists())
                        self.assertIn('complete Side Galaxy sdist', result.stderr)

    def test_guest_installs_locked_requirements_before_source_without_dependency_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = Lab(directory)
            wheels = Path(directory) / 'wheels'
            wheels.mkdir()
            (wheels / 'dependency.whl').write_bytes(b'wheel')
            with patch.object(lab, '_remote') as remote, patch.object(lab, '_copy'):
                lab._install(state(), Path(directory) / 'source.tar.gz', 'a' * 64, wheels, 120)
            script = remote.call_args.args[1]
            locked = script.index('pip install --require-hashes --no-index --find-links')
            source = script.index('pip install --no-deps --no-index --find-links')
            self.assertLess(script.index('sha256sum -c -'), script.index('archive.extractfile'))
            self.assertLess(locked, source)
            self.assertNotIn('extractall', script)
            self.assertNotIn(directory, script)


if __name__ == '__main__': unittest.main()
