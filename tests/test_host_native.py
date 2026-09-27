import ctypes
from pathlib import Path
import tempfile
import unittest

from side_galaxy.native import host_call, library, NativeError


class NativeHostParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / 'proc'
        self.sys = self.root / 'sys'
        self.proc.mkdir()
        self.sys.mkdir()

    def sample(self):
        # Fixture counters verify parsing only; they are not hardware samples.
        return host_call('sample', {'proc_root': str(self.proc), 'sys_root': str(self.sys), 'disk_path': str(self.root)})

    def test_cpu_delta_excludes_duplicate_guest_counters_and_reads_sensors(self):
        (self.proc / 'stat').write_text('cpu 100 0 50 850 0 0 0 0 25 0\ncpu0 100 0 50 850 0 0 0 0 25 0\n')
        (self.proc / 'meminfo').write_text('MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\n')
        frequency = self.sys / 'devices/system/cpu/cpu0/cpufreq'
        frequency.mkdir(parents=True)
        (frequency / 'scaling_cur_freq').write_text('1500000\n')
        thermal = self.sys / 'class/thermal/thermal_zone0'
        thermal.mkdir(parents=True)
        (thermal / 'temp').write_text('42500\n')
        first = self.sample()
        self.assertIsNone(first['cpu_percent'])
        self.assertEqual(first['memory_total_mib'], 2048)
        self.assertEqual(first['memory_available_mib'], 1024)
        self.assertEqual(first['cpu_frequency_mhz'], 1500)
        self.assertEqual(first['temperature_celsius'], 42.5)
        (self.proc / 'stat').write_text('cpu 130 0 70 900 0 0 0 0 40 0\ncpu0 130 0 70 900 0 0 0 0 40 0\n')
        second = self.sample()
        self.assertEqual(second['cpu_percent'], 50)
        self.assertEqual(second['per_cpu'][0]['percent'], 50)

    def test_malformed_and_reset_counters_do_not_become_measurements(self):
        (self.proc / 'stat').write_text('cpu -1 0 0 2\ncpu0 1 junk 3 4\ncpu999999999999999999999 1 0 0 1\n')
        (self.proc / 'meminfo').write_text('MemTotal: -10 kB\nMemAvailable: 100junk kB\n')
        thermal = self.sys / 'class/thermal/thermal_zone0'
        thermal.mkdir(parents=True)
        (thermal / 'temp').write_text('42000garbage\n')
        value = self.sample()
        self.assertIsNone(value['cpu_percent'])
        self.assertEqual(value['per_cpu'], [])
        self.assertIsNone(value['memory_total_mib'])
        self.assertIsNone(value['memory_available_mib'])
        self.assertIsNone(value['temperature_celsius'])
        (self.proc / 'stat').write_text('cpu 18446744073709551615 1 0 1\n')
        self.assertIsNone(self.sample()['cpu_percent'])
        (self.proc / 'stat').write_text('cpu 10 0 0 10\n')
        self.assertIsNone(self.sample()['cpu_percent'])
        (self.proc / 'stat').write_text('cpu 1 0 0 1\n')
        self.assertIsNone(self.sample()['cpu_percent'])
        (self.proc / 'stat').write_text('cpu 2 0 0 2\n')
        self.assertEqual(self.sample()['cpu_percent'], 50)

    def test_invalid_host_call_returns_owned_error_without_crossing_abi(self):
        for payload in ([], {'cpus': []}):
            with self.assertRaises(NativeError): host_call('unknown-operation', payload)
        core = library()
        pointer = core.sg_host_call(None, b'{}')
        self.assertTrue(pointer)
        try: self.assertIn(b'"ok":false', ctypes.string_at(pointer))
        finally: core.sg_core_free(pointer)


if __name__ == '__main__': unittest.main()
