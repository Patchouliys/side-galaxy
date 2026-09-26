import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from side_galaxy.lab_cli import default_image


class LabImageTests(unittest.TestCase):
    def test_verified_download_cache_and_corruption(self):
        content = b'verified-test-image'
        hashes = {'aarch64': ('arm64', hashlib.sha512(content).hexdigest())}
        with tempfile.TemporaryDirectory() as folder, patch('side_galaxy.lab_cli.IMAGE_HASHES', hashes):
            stream = MagicMock()
            stream.__enter__.return_value.iter_bytes.return_value = [content[:5], content[5:]]
            with patch('side_galaxy.lab_cli.httpx.stream', return_value=stream) as request:
                path, digest = default_image('aarch64', folder)
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(default_image('aarch64', folder), (path, digest))
                self.assertEqual(request.call_count, 1)
                path.write_bytes(b'corrupted')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    default_image('aarch64', folder)

    def test_unverified_download_is_not_published(self):
        hashes = {'aarch64': ('arm64', hashlib.sha512(b'expected').hexdigest())}
        with tempfile.TemporaryDirectory() as folder, patch('side_galaxy.lab_cli.IMAGE_HASHES', hashes):
            stream = MagicMock()
            stream.__enter__.return_value.iter_bytes.return_value = [b'wrong']
            with patch('side_galaxy.lab_cli.httpx.stream', return_value=stream):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    default_image('aarch64', folder)
            self.assertFalse(list(Path(folder).glob('*.qcow2')))


if __name__ == '__main__': unittest.main()
