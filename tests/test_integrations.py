import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Controller, AccountError
from integrations import Integrations
from installer import install


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.controller = Controller(proxy_dir=self.root / 'proxy', data_dir=self.root / 'data')
        self.controller.proxy_dir.mkdir()
        (self.controller.proxy_dir / 'client-key.txt').write_text('local-test-key')
        self.client = Integrations(self.controller, self.root / 'home', self.root / 'local')

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_preserves_other_settings_and_restores_exact_original_bytes(self):
        paths = self.client.paths()
        cli = paths['claude_cli'][0]
        cli.parent.mkdir(parents=True)
        original = b'{"env":{"OTHER":"keep"},"permissions":{"allow":["Read"]}}\r\n'
        cli.write_bytes(original)
        codex = paths['codex'][0]
        codex.parent.mkdir(parents=True)
        codex_original = b'model = "original"\n[features]\nexample = true\n'
        codex.write_bytes(codex_original)
        self.client.apply(['claude_cli', 'codex', 'claude_desktop'])
        self.client.apply(['claude_cli', 'codex', 'claude_desktop'])
        self.assertEqual(json.loads(cli.read_text())['env']['OTHER'], 'keep')
        self.assertEqual(json.loads(cli.read_text())['permissions']['allow'], ['Read'])
        config = tomllib.loads(codex.read_text())
        self.assertEqual(config['model_provider'], 'gemini_accounts')
        self.assertTrue(config['features']['example'])
        self.assertEqual(config['model_providers']['gemini_accounts']['wire_api'], 'responses')
        self.assertEqual(tomllib.loads(paths['codex'][1].read_text())['model_provider'], 'gemini_accounts')
        self.assertNotIn(b'local-test-key', self.client.backup_path.read_bytes())
        self.client.restore()
        self.assertEqual(cli.read_bytes(), original)
        self.assertEqual(codex.read_bytes(), codex_original)
        self.assertFalse(paths['codex'][1].exists())
        self.assertTrue(all(not p.exists() for p in paths['claude_desktop']))

    def test_invalid_existing_config_is_not_overwritten(self):
        path = self.client.paths()['codex'][0]
        path.parent.mkdir(parents=True)
        path.write_text('not valid TOML')
        with self.assertRaises(tomllib.TOMLDecodeError):
            self.client.apply(['codex'])
        self.assertEqual(path.read_text(), 'not valid TOML')

    def test_legacy_model_labels_follow_aliases_and_restore_exactly(self):
        library = self.client.local / 'Claude-3p' / 'configLibrary'
        legacy = '5010c5ea-93a5-425b-aba1-6b85f3a14292'
        library.mkdir(parents=True)
        self.client.write_json(library / '_meta.json', {'appliedId': legacy})
        path = library / (legacy + '.json')
        self.client.write_json(path, {
            'inferenceGatewayBaseUrl': 'http://127.0.0.1:8317',
            'inferenceGatewayApiKey': 'keep-key',
            'inferenceModels': [{'name': 'claude-sonnet-4-5', 'labelOverride': 'Gemini Pro', 'isFamilyDefault': True}]})
        original = path.read_bytes()
        self.controller.model_aliases = lambda: {'claude-sonnet-4-5': 'gemini-pro-agent'}
        self.assertEqual(self.client.paths()['claude_desktop'][2], path)
        self.assertTrue(self.client.refresh_desktop_model_labels())
        preset = self.client.read_json(path)
        self.assertEqual(preset['inferenceModels'][0]['labelOverride'], 'Gemini · 3.1 Pro High')
        self.assertEqual(preset['inferenceModels'][0]['name'], 'claude-sonnet-4-5')
        self.assertEqual(preset['inferenceGatewayApiKey'], 'keep-key')
        self.assertFalse(self.client.refresh_desktop_model_labels())
        self.client.restore()
        self.assertEqual(path.read_bytes(), original)

    def test_unrelated_gateway_is_not_adopted(self):
        library = self.client.local / 'Claude-3p' / 'configLibrary'
        legacy = '5010c5ea-93a5-425b-aba1-6b85f3a14292'
        self.client.write_json(library / '_meta.json', {'appliedId': legacy})
        self.client.write_json(library / (legacy + '.json'), {'inferenceGatewayBaseUrl': 'https://example.com',
            'inferenceModels': [{'name': 'other', 'labelOverride': 'Gemini Pro'}]})
        self.assertIsNone(self.client.legacy_desktop_preset())
        self.assertFalse(self.client.refresh_desktop_model_labels())

    def test_installer_creates_fresh_keys_and_retains_config_on_update(self):
        payload = self.root / 'payload'
        payload.mkdir()
        for name in ('GeminiAccounts.exe', 'GeminiQuotaQueue.exe', 'cli-proxy-api.exe', 'start-proxy.ps1', 'CLIProxyAPI-LICENSE.txt'):
            (payload / name).write_bytes(b'test payload')
        target = self.root / 'installed'
        install(payload, target, shortcuts=False)
        key = (target / 'ClaudeGemini' / 'client-key.txt').read_bytes()
        config = (target / 'ClaudeGemini' / 'config.yaml').read_bytes()
        install(payload, target, shortcuts=False)
        self.assertEqual(config, (target / 'ClaudeGemini' / 'config.yaml').read_bytes())
        self.assertEqual(key, (target / 'ClaudeGemini' / 'client-key.txt').read_bytes())
        other = self.root / 'other'
        install(payload, other, shortcuts=False)
        self.assertNotEqual(key, (other / 'ClaudeGemini' / 'client-key.txt').read_bytes())


if __name__ == '__main__': unittest.main()
