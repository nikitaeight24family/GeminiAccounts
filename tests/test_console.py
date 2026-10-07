import contextlib
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import Controller
from console import Terminal, confirm, reset_text, family, parser
from runtime import initialize, native_asset


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'GEMINI_ACCOUNTS_HOME': str(self.root)})
        self.env.start()
        self.controller = Controller()
        initialize(self.controller)
        self.terminal = Terminal(self.controller)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_consent_denial_changes_no_client_files(self):
        self.terminal.integrations.home = self.root / 'home'
        with patch('builtins.input', return_value='no'), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.terminal.configure(['claude_cli', 'codex']))
        self.assertFalse((self.root / 'home').exists())
        self.assertFalse(self.terminal.integrations.backup_path.exists())

    def test_explicit_consent_and_exact_restoration_without_service(self):
        self.terminal.integrations.home = self.root / 'home'
        path = self.terminal.integrations.paths()['claude_cli'][0]
        path.parent.mkdir(parents=True)
        original = b'{"env":{"OTHER":"original"}}\r\n'
        path.write_bytes(original)
        with patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.terminal.configure(['claude_cli', 'codex']))
            self.assertNotEqual(path.read_bytes(), original)
            self.assertTrue(self.terminal.restore())
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.terminal.integrations.paths()['codex'][0].exists())
        self.assertTrue((self.controller.proxy_dir / 'auth').exists())

    def test_architectures_are_pinned(self):
        self.assertEqual(native_asset('Darwin', 'arm64')[0], 'darwin_aarch64.tar.gz')
        self.assertEqual(native_asset('Darwin', 'x86_64')[0], 'darwin_amd64.tar.gz')
        self.assertEqual(len(native_asset('Windows', 'AMD64')[1]), 64)

    def test_reset_and_provider_display(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(reset_text((now + timedelta(hours=4, minutes=22)).isoformat(), now), '4h 22m')
        self.assertEqual(reset_text(None), '--')
        self.assertEqual(family('claude-sonnet-4-5'), 'gemini')
        self.assertEqual(family('claude-opus-4-6-thinking'), 'claude')
        self.assertTrue(parser().parse_args(['configure', '--yes', '--clients', 'codex']).yes)
        with patch('builtins.input', side_effect=EOFError):
            self.assertFalse(confirm('Allow?'))

    def test_status_reports_both_active_subscriptions_and_four_quotas(self):
        account = {'name': 'a', 'email': 'example@test.invalid', 'auth_index': 'a', 'disabled': False}
        self.terminal.accounts = [account]
        self.terminal.activity.state['latest'] = {
            'gemini-3-flash': {'name': 'a', 'model': 'gemini-3-flash', 'at': '2026-10-07T01:00:00Z'},
            'claude-opus-4-6-thinking': {'name': 'a', 'model': 'claude-opus-4-6-thinking', 'at': '2026-10-07T02:00:00Z'}}
        self.terminal.caches['a'] = {'data': {'groups': [
            {'kind': kind, 'buckets': [{'window': window, 'remaining': .5} for window in ('5h', 'weekly')]}
            for kind in ('gemini', 'claude')]}}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.terminal.show_status(refresh=False)
        self.assertIn('gemini + claude', output.getvalue())
        self.assertEqual(output.getvalue().count('50.0%'), 4)


if __name__ == '__main__':
    unittest.main()
