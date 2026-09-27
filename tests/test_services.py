import argparse
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from side_galaxy.service_cli import add_parser, execute
from side_galaxy.services import ServiceManager, render_definition, systemd_quote
from side_galaxy.profiles import catalog


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manager = ServiceManager(self.root / 'state', system='Darwin', home=self.root / 'home')
        self.calls, self.registered = [], False
        socket_patch = patch('side_galaxy.services.socket.socket')
        socket_patch.start()
        self.addCleanup(socket_patch.stop)
        self.commands = patch.object(self.manager, '_run', side_effect=self.run_manager)
        self.commands.start()
        self.addCleanup(self.commands.stop)
        self.health = patch.object(self.manager, '_health', return_value=False)
        self.health.start()
        self.addCleanup(self.health.stop)

    def run_manager(self, command, check=True):
        self.calls.append(command)
        if command[1] == 'print':
            return SimpleNamespace(returncode=0 if self.registered else 113,
                                   stdout='state = running\n pid = 4242\n last exit code = 0\n' if self.registered else '')
        if command[1] == 'bootstrap': self.registered = True
        if command[1] == 'bootout': self.registered = False
        return SimpleNamespace(returncode=0, stdout='')

    def install(self):
        return self.manager.install_controller(self.root / 'test.db', 47982)

    def test_private_install_and_status_do_not_disclose_configuration(self):
        with patch.dict(os.environ, {'SG_TOKEN': 'private-operator-token-for-testing'}):
            status = self.install()
        self.assertTrue(status['installed'])
        self.assertTrue(status['running'])
        self.assertFalse(status['reachable'])
        self.assertNotIn('private-operator-token', json.dumps(status))
        self.assertNotIn(str(self.root), json.dumps(status))
        definition = self.manager.definition_path('controller')
        self.assertEqual(definition.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.manager.root / 'controller.json').stat().st_mode & 0o777, 0o600)
        data = plistlib.loads(definition.read_bytes())
        self.assertTrue(data['KeepAlive'])
        self.assertEqual(data['ProgramArguments'][-1], str((self.root / 'test.db').resolve()))
        self.assertEqual(data['EnvironmentVariables']['SG_TOKEN'], 'private-operator-token-for-testing')

    def test_install_is_idempotent_and_does_not_replace_different_settings(self):
        self.install()
        self.install()
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            self.manager.install_controller(self.root / 'other.db', 47983)
        self.assertEqual(sum(command[1] == 'bootstrap' for command in self.calls), 1)

    def test_custom_profiles_and_multiple_lab_roots_survive_supervision(self):
        profiles = self.root / 'custom profiles'
        (profiles / 'boards').mkdir(parents=True)
        (profiles / 'boards' / 'custom-board.json').write_text(json.dumps({'id': 'custom-board', 'name': 'Custom board'}))
        labs = [self.root / 'first lab', self.root / 'second lab']
        with patch.dict(os.environ, {'SG_PROFILES_DIR': str(profiles)}):
            status = self.manager.install_controller(self.root / 'custom.db', 47982, labs)
        config = self.manager._config('controller')
        self.assertEqual(config['environment']['SG_PROFILES_DIR'], str(profiles))
        self.assertEqual(config['argv'][-4:], ['--lab-state-dir', str(labs[0].resolve()), '--lab-state-dir', str(labs[1].resolve())])
        definition = plistlib.loads(self.manager.definition_path('controller').read_bytes())
        self.assertEqual(definition['ProgramArguments'], config['argv'])
        self.assertEqual(definition['EnvironmentVariables']['SG_PROFILES_DIR'], str(profiles))
        self.assertIn('custom-board', [item['id'] for item in catalog(definition['EnvironmentVariables']['SG_PROFILES_DIR'])['boards']])
        self.assertNotIn(str(self.root), json.dumps(status))

        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command', required=True))
        args = parser.parse_args(['service', 'install', 'controller', '--lab-state-dir', str(labs[0]), '--lab-state-dir', str(labs[1])])
        with patch('side_galaxy.service_cli.ServiceManager') as manager:
            execute(args)
        manager.return_value.install_controller.assert_called_once_with('.data/galaxy.db', 7980, [str(p) for p in labs])

    def test_active_work_blocks_stop_and_admission_is_locked_during_safe_stop(self):
        self.install()
        db = self.root / 'test.db'
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE runs (state TEXT)')
            connection.execute("INSERT INTO runs VALUES ('running')")
        for state in ('waiting', 'queued', 'running', 'cancelling'):
            with sqlite3.connect(db) as connection: connection.execute('UPDATE runs SET state=?', (state,))
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, 'active experiments'):
                self.manager.action('controller', 'restart')
            self.assertTrue(self.registered)
        with sqlite3.connect(db) as connection: connection.execute("UPDATE runs SET state='succeeded'")
        with self.manager._idle_guard('controller'):
            with sqlite3.connect(db, timeout=.01) as competing:
                with self.assertRaises(sqlite3.OperationalError): competing.execute("INSERT INTO runs VALUES ('queued')")
        self.manager.action('controller', 'uninstall')
        self.assertFalse(self.registered)
        self.assertFalse(self.manager.definition_path('controller').exists())
        self.assertTrue(db.exists())

    def test_tunnel_uses_only_existing_private_config_and_fixed_forwarding_argv(self):
        self.install()
        config = self.root / 'ssh_config'
        config.write_text('Host test-board\n  HostName 127.0.0.1\n')
        config.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'match the paired controller'):
            self.manager.install_tunnel(config, 'test-board', 47983, 17982)
        self.assertIsNone(self.manager._config('tunnel'))
        self.manager.install_tunnel(config, 'test-board', 47982, 17982)
        argv = self.manager._config('tunnel')['argv']
        self.assertIn('127.0.0.1:17982:127.0.0.1:47982', argv)
        self.assertIn('ControlMaster=no', argv)
        self.assertIn('ExitOnForwardFailure=yes', argv)
        self.assertNotIn('sh', argv)
        with self.assertRaises(ValueError): self.manager.install_tunnel(config, '-oProxyCommand=bad', 47982, 17982)
        config.chmod(0o644)
        with self.assertRaises(ValueError): self.manager.install_tunnel(config, 'test-board', 47982, 17982)
        with self.assertRaisesRegex(ValueError, 'paired tunnel'):
            self.manager.action('controller', 'uninstall')

    def test_systemd_has_restart_policy_and_escapes_commands_without_a_shell(self):
        config = {'kind': 'controller', 'cwd': '/tmp/test space', 'argv': ['/tmp/python', 'a$HOME%value', 'quote"here'],
                  'environment': {'SG_TOKEN': 'private$token%value'}}
        result = render_definition(config, 'Linux', self.root).decode()
        self.assertIn('Restart=always', result)
        self.assertIn('Type=exec', result)
        self.assertIn('"a$$HOME%%value"', result)
        self.assertIn('quote\\"here', result)
        self.assertNotIn('/bin/sh', result)
        self.assertEqual(systemd_quote('$value'), '"$value"')
        with self.assertRaises(ValueError): systemd_quote('bad\nvalue')

    def test_cli_routes_have_no_remote_service_definition_argument(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest='command', required=True)
        add_parser(sub)
        args = parser.parse_args(['service', 'install', 'controller', '--db', 'test.db', '--port', '7982'])
        self.assertEqual((args.service_action, args.service_kind, args.port), ('install', 'controller', 7982))
        self.assertIsNone(parser.parse_args(['service', 'status']).service_kind)
        self.assertEqual(parser.parse_args(['service', 'restart', 'controller']).service_kind, 'controller')


if __name__ == '__main__': unittest.main()
