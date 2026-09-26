import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from side_galaxy.models import Plan
from side_galaxy.modules import kvm
from side_galaxy.runtime import Execution, Modules


class ModuleTests(unittest.TestCase):
    def test_reload_pins_running_generation_and_rolls_back_invalid_code(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'plugin.py'
            source.write_text(Path('src/side_galaxy/modules/simulator.py').read_text())
            modules = Modules(Path(root) / 'snapshots', 'pi4', 'simulator', module_file=source)
            old_path, old_description = modules.current
            plan = Plan(boards=['test'], duration_seconds=1)
            job = {'plan':plan.model_dump(), 'module_sha256':old_description.module_sha256, 'mode':'synthetic'}
            running = Execution(old_path, job)
            source.write_text(source.read_text().replace('12000 *', '18000 *'))
            modules.reload()
            self.assertNotEqual(old_description.module_sha256, modules.current[1].module_sha256)
            self.assertIn('12000 *', old_path.read_text())
            deadline = time.monotonic()+5
            result = None
            while result is None and time.monotonic() < deadline:
                result = running.poll()
                time.sleep(.03)
            self.assertEqual(result.result['metrics']['sample_operations'], 12000)
            current = modules.current
            source.write_text('not valid python !!!')
            modules.reload()
            self.assertEqual(current, modules.current)
            self.assertIn('validation failed', modules.error)

    def test_custom_board_and_system_manifests(self):
        with tempfile.TemporaryDirectory() as root:
            extra = Path(root) / 'profiles'
            (extra/'boards').mkdir(parents=True)
            (extra/'systems').mkdir()
            (extra/'boards'/'new.json').write_text(json.dumps({'id':'new-board','name':'New board','reserved_cpus':[0,3]}))
            (extra/'systems'/'new.json').write_text(json.dumps({'id':'new-system','name':'New OS','module':'simulator'}))
            modules = Modules(Path(root)/'snapshots', 'new-board', 'new-system', extra)
            self.assertEqual(modules.current[1].reserved_cpus, [0,3])

    def check_kvm(self, failure=None):
        current = {'0':'0-3', '1':'0-3'}
        calls = []
        def fake(*args):
            calls.append(args)
            if args[0]=='domuuid': return '00000000-0000-0000-0000-000000000001'
            if args[0]=='domstate': return 'running'
            if args[0]=='domstats':
                if failure == 'stats': raise RuntimeError('stats failed')
                return 'cpu.time=100'
            if args[0]=='vcpupin':
                if len(args)==3: return 'VCPU CPU Affinity\n----------------\n'+'\n'.join(k+' '+v for k,v in current.items())
                if failure=='restore' and args[3]=='0-3': raise RuntimeError('restore failed')
                current[args[2]]=args[3]
                return ''
        plan = Plan(boards=['test'], template='kvm-affinity', cpus=[1,2], interference_cpus=[], memory_mib=None, duration_seconds=1)
        with patch.dict('os.environ', {'SG_KVM_DOMAIN':'dedicated-test'}), patch.object(kvm, 'virsh', side_effect=fake), patch.object(kvm.os,'sched_getaffinity',return_value={0,1,2,3},create=True), patch.object(kvm,'Path') as path, patch.object(kvm.signal,'signal'), patch.object(kvm.time,'sleep',side_effect=InterruptedError if failure=='cancel' else None):
            path.return_value.read_text.return_value='test-boot-id'
            result = kvm.run(plan.model_dump())
        return result, current, calls

    def test_kvm_affinity_restores_on_success_failure_and_cancel(self):
        for failure in (None, 'stats', 'cancel'):
            with self.subTest(failure=failure):
                result, current, calls = self.check_kvm(failure)
                self.assertTrue(result['cleanup_ok'])
                self.assertEqual(current, {'0':'0-3','1':'0-3'})
                self.assertEqual(result['boot_id_before'], result['boot_id_after'])
                self.assertFalse(any(call[0] in ('destroy','reboot','shutdown') for call in calls))

    def test_kvm_failed_restore_is_explicit(self):
        result, _, _ = self.check_kvm('restore')
        self.assertFalse(result['cleanup_ok'])


if __name__ == '__main__': unittest.main()
