import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from side_galaxy.environments import EnvironmentStore, pack_environment, validate_environment, verify_directory
from side_galaxy.modules import qemu_environment as qemu


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.files = {'rootfs.raw': b'raw root disk\0' * 100, 'kernel': b'test kernel'}
        self.manifest = {'schema': 1, 'name': 'test environment', 'architecture': 'aarch64',
                         'disk': {'file': 'rootfs.raw', 'format': 'raw'},
                         'boot': {'kernel': 'kernel', 'cmdline': 'console=ttyAMA0 root=/dev/vda'},
                         'files': {k: hashlib.sha256(v).hexdigest() for k, v in self.files.items()}}
        (self.source / 'environment.json').write_text(json.dumps(self.manifest))
        for name, data in self.files.items(): (self.source / name).write_bytes(data)
        self.bundle = self.root / 'bundle.zip'
        pack_environment(self.source, self.bundle)
        self.store = EnvironmentStore(self.root / 'store')

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, replacements=None, extra=None):
        target = self.root / 'hostile.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('environment.json', json.dumps(self.manifest))
            for name, data in self.files.items(): archive.writestr(name, (replacements or {}).get(name, data))
            if extra:
                archive.writestr(*extra)
        return target

    def test_optional_runtime_rejects_explicit_null_and_invalid_fields(self):
        for runtime in (None, {'os': 'linux', 'commands': None},
                        {'os': 'linux', 'commands_complete': None}, {'os': None}):
            with self.subTest(runtime=runtime):
                self.manifest['runtime'] = runtime
                with self.assertRaises(ValueError): self.store.put_file(self.archive())
        self.manifest.pop('runtime')
        self.assertEqual(validate_environment(self.archive()), self.manifest)
        self.assertEqual(self.store.list(), [])

    def test_pack_rejects_null_boot_and_nonstring_optional_boot_files(self):
        for boot in (None, {'kernel': 'kernel', 'cmdline': None},
                     {'kernel': 'kernel', 'cmdline': '', 'initrd': None},
                     {'firmware': []}):
            with self.subTest(boot=boot):
                manifest = {**self.manifest, 'boot': boot}
                (self.source / 'environment.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError): pack_environment(self.source, self.root / 'invalid.zip')
        self.assertFalse((self.root / 'invalid.zip').exists())

    def test_roundtrip_streamed_deduplicated_and_tamper_detected(self):
        metadata = self.store.put_file(self.bundle)
        with self.bundle.open('rb') as stream:
            self.assertEqual(self.store.put_stream(stream), metadata)
        self.assertEqual(self.store.list(), [metadata])
        base = self.store.unpack(metadata['sha256'])
        self.assertEqual(verify_directory(base), self.manifest)
        self.assertEqual(self.store.unpack(metadata['sha256']), base)
        (base / 'rootfs.raw').chmod(0o600)
        (base / 'rootfs.raw').write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.store.unpack(metadata['sha256'])

    def test_unsafe_files_links_duplicates_and_hash_rejected(self):
        link = zipfile.ZipInfo('firmware.fd')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [self.archive({'kernel': b'wrong'}).read_bytes(),
                 self.archive(extra=('../outside', b'bad')).read_bytes(),
                 self.archive(extra=(link, b'kernel')).read_bytes(),
                 self.archive(extra=('kernel', b'duplicate')).read_bytes()]
        for data in cases:
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.store.put_stream(io.BytesIO(data))
        self.assertEqual(self.store.list(), [])
        self.assertFalse((self.root / 'outside').exists())

    def test_metadata_cache_does_not_rehash_unchanged_images(self):
        metadata = self.store.put_file(self.bundle)
        with patch('side_galaxy.environments.validate_environment', side_effect=AssertionError('unexpected image scan')):
            self.assertEqual(self.store.list(), [metadata])
            self.assertEqual(self.store.metadata(metadata['sha256']), metadata)
        path = self.store.get(metadata['sha256'])
        path.chmod(0o600)
        path.write_bytes(b'tampered')
        self.assertEqual(self.store.list(), [])

    def test_bounded_stream_and_expansion_fail_before_publication(self):
        with patch('side_galaxy.environments.MAX_ENVIRONMENT', 32), self.assertRaises(ValueError):
            self.store.put_file(self.bundle)
        with patch('side_galaxy.environments.MAX_EXPANDED', 32), self.assertRaises(ValueError):
            self.store.put_file(self.bundle)
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_raw_only_and_symlink_cache(self):
        self.manifest['disk']['format'] = 'qcow2'
        with self.assertRaises(ValueError): validate_environment(self.archive())
        metadata = self.store.put_file(self.bundle)
        (self.store.root / metadata['sha256']).symlink_to(self.source)
        with self.assertRaises(ValueError): self.store.unpack(metadata['sha256'])

    def test_missing_metadata_is_key_error_and_warm_unpack_does_not_decompress_again(self):
        with self.assertRaises(KeyError): self.store.metadata('0' * 64)
        metadata = self.store.put_file(self.bundle)
        base = self.store.unpack(metadata['sha256'])
        with patch('side_galaxy.environments.validate_environment', side_effect=AssertionError('unexpected decompression')):
            self.assertEqual(self.store.unpack(metadata['sha256']), base)

    def test_offline_qemu_argv_has_no_network_or_shared_directory(self):
        command = qemu.command_for(self.manifest, self.source, self.root,
                                   {'cpus': [1, 2], 'memory_mib': 512}, 'kvm', 'test-uuid')
        self.assertEqual(command[command.index('-accel') + 1], 'kvm')
        self.assertEqual(command[command.index('-smp') + 1], '2')
        self.assertEqual(command[command.index('-nic') + 1], 'none')
        self.assertNotIn('-virtfs', command)
        self.assertNotIn('hostfwd', ' '.join(command))

    def test_stop_uses_verified_qmp_identity_and_confirms_exit(self):
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        process.returncode = 0
        channel = MagicMock()
        channel.read.return_value = {'QMP': {}}
        channel.command.side_effect = [{}, {'UUID': 'instance'}, {}]
        with patch.object(qemu, 'Channel', return_value=channel):
            result = qemu.stop_vm(process, '/unused', 'instance')
        self.assertTrue(result['qmp_identity_verified'])
        self.assertTrue(result['vm_stopped'])
        channel.command.assert_any_call('quit')
        process.wait.assert_called_once_with(timeout=5)

    def test_identity_mismatch_never_sends_quit_to_unverified_socket(self):
        process = MagicMock()
        process.poll.side_effect = [None, -15]
        process.returncode = -15
        process.wait.side_effect = [subprocess.TimeoutExpired('qemu', 5), None]
        channel = MagicMock()
        channel.read.return_value = {'QMP': {}}
        channel.command.side_effect = [{}, {'UUID': 'another-instance'}]
        with patch.object(qemu, 'Channel', return_value=channel):
            result = qemu.stop_vm(process, '/unused', 'instance')
        self.assertFalse(result['qmp_identity_verified'])
        self.assertTrue(result['vm_stopped'])
        self.assertNotIn(unittest.mock.call('quit'), channel.command.call_args_list)
        process.terminate.assert_called_once()

    def test_qga_preserves_guest_path_and_sends_complete_large_frames(self):
        channel = MagicMock()
        channel.read.side_effect = [{'return': 123}, {'return': {'pid': 42}}]
        with patch.object(qemu, 'Channel', return_value=channel), patch.object(qemu.time, 'monotonic_ns', return_value=123):
            self.assertEqual(qemu.qga('/unused.sock', 'guest-exec', path='/usr/bin/python3'), {'pid': 42})
        channel.write.assert_any_call({'execute': 'guest-exec', 'arguments': {'path': '/usr/bin/python3'}})
        payload = {'execute': 'guest-file-write', 'arguments': {'buf-b64': 'x' * 90000}}
        qemu.Channel.write(channel, payload)
        channel.socket.sendall.assert_called_with(json.dumps(payload).encode() + b'\n')

    def test_guest_event_file_preserves_split_utf8_and_bounds_disk_use(self):
        from side_galaxy import workload_runner as runner
        target = self.root / 'events.jsonl'
        with patch.dict(os.environ, {'SG_EVENT_FILE': str(target)}, clear=True), \
                patch.object(runner, 'MAX_EVENT_FILE', 4096), \
                patch.object(runner.emit_log, 'decoders', {}, create=True), \
                patch.object(runner.emit_log, 'full_files', set(), create=True), \
                patch.object(runner.emit_log, 'dropped', False, create=True):
            data = '星🌌'.encode()
            runner.emit_log('stdout', data[:2])
            runner.emit_log('stdout', data[2:], final=True)
            events = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual(''.join(event['text'] for event in events), '星🌌')
            runner.emit_log('stderr', b'x' * 10000)
            size = target.stat().st_size
            runner.emit_log('stderr', b'y' * 10000, final=True)
            self.assertEqual(target.stat().st_size, size)
            self.assertLessEqual(size, 4096)
            events = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertTrue(events[-1]['truncated'])

    def test_guest_event_tail_reassembles_lines_and_closes_handles(self):
        events = []
        tail = qemu.GuestEvents('/socket', '/events', events.append)
        data = (json.dumps({'stream': 'stdout', 'text': 'running 🌌'}, ensure_ascii=False) + '\n').encode()
        replies = [11, {}, {'count': 5, 'buf-b64': base64.b64encode(data[:5]).decode(), 'eof': False}, {},
                   12, {}, {'count': len(data) - 5, 'buf-b64': base64.b64encode(data[5:]).decode(), 'eof': True}, {}]
        with patch.object(qemu, 'qga', side_effect=replies) as request:
            tail.poll()
            self.assertEqual(events, [])
            tail.poll(drain=True)
            request.assert_any_call('/socket', 'guest-file-close', handle=11)
            request.assert_any_call('/socket', 'guest-file-close', handle=12)
        self.assertEqual(events, [{'stream': 'stdout', 'text': 'running 🌌'}])
        self.assertFalse(tail.truncated)
        with patch.object(qemu, 'qga', side_effect=[13, RuntimeError('read failure'), {}]) as request:
            tail.poll()
            request.assert_any_call('/socket', 'guest-file-close', handle=13)
        self.assertTrue(tail.truncated)

    def test_linux_does_not_silently_fall_back_from_kvm(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(qemu.platform, 'system', return_value='Linux'), \
                patch('builtins.open', side_effect=PermissionError('KVM denied')):
            with self.assertRaises(PermissionError): qemu.accelerator()
        with patch.dict(os.environ, {'SG_QEMU_ACCEL': 'tcg'}):
            self.assertEqual(qemu.accelerator(), 'tcg')


if __name__ == '__main__':
    unittest.main()
