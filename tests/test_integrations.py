import json
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Controller, AccountError
from integrations import Integrations
from installer import install
from tokenharbor import TokenHarbor, CLIENT_MODEL, UPSTREAM_MODEL, PROVIDER


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.controller = Controller(proxy_dir=self.root / 'proxy', data_dir=self.root / 'data')
        self.controller.proxy_dir.mkdir()
        (self.controller.proxy_dir / 'client-key.txt').write_text('local-test-key')
        self.client = Integrations(self.controller, self.root / 'home', self.root / 'local')
        self.client.connection_models=lambda: set(self.client.gemini_model_choices()) | {'gemini-pro-agent','gemini-3-flash','claude-sonnet-4-6'}
        self.routes = []
        def management(path, method='GET', payload=None):
            if path != '/oauth-model-alias':
                raise AccountError('No test gateway')
            if method == 'PATCH':
                self.routes = payload['aliases']
            return {'oauth-model-alias': {'antigravity': self.routes}}
        self.controller.request = management

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
        provider = config['model_providers']['gemini_accounts']
        self.assertFalse(provider['requires_openai_auth'])
        self.assertEqual(provider['experimental_bearer_token'], 'local-test-key')
        profile_provider = tomllib.loads(paths['codex'][1].read_text())['model_providers']['gemini_accounts']
        self.assertEqual(profile_provider, provider)
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
        self.assertTrue(preset['inferenceModels'][0]['supports1m'])
        self.assertTrue(preset['inferenceModels'][0]['prefer1m'])
        self.assertFalse(self.client.refresh_desktop_model_labels())
        self.client.restore()
        self.assertEqual(path.read_bytes(), original)

    def test_context_setup_keeps_claude_and_gemini_separate(self):
        self.controller.preferences.update({'gemini-model': 'gemini-pro-agent', 'claude-model': 'claude-sonnet-4-6'})
        self.client.apply(['claude_cli', 'claude_desktop'])
        env = self.client.read_json(self.client.paths()['claude_cli'][0])['env']
        self.assertIn(env['ANTHROPIC_MODEL'], self.client.connection_models())
        self.assertIn(env['ANTHROPIC_DEFAULT_OPUS_MODEL'], self.client.connection_models())
        models = self.client.read_json(self.client.paths()['claude_desktop'][2])['inferenceModels']
        gemini = next(m for m in models if m['name'] == self.client.claude_desktop_route('gemini-pro-agent'))
        claude = next(m for m in models if m['name'] == 'claude-sonnet-4-6')
        self.assertTrue(gemini['supports1m'])
        self.assertFalse(claude['supports1m'])
        self.assertEqual(env['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], '1')
        self.assertTrue(any(route['alias'] == self.client.claude_desktop_route('gemini-pro-agent')
                            and route['name'] == 'gemini-pro-agent' for route in self.routes))

    def test_flash_reasoning_levels_appear_in_client_catalogs(self):
        choices = ['gemini-3.8-flash-high', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-low',
                   'gemini-3.5-flash-low']
        self.controller.family_model_choices = lambda: {'gemini': choices, 'claude': ['claude-sonnet-4-6']}
        cache = self.client.home / '.codex' / 'models_cache.json'
        self.client.write_json(cache, {'models': [{'slug': 'gpt-test', 'display_name': 'GPT Test',
            'default_reasoning_level': 'medium', 'supported_reasoning_levels': []}]})
        self.client.apply(['claude_desktop', 'codex'])
        desktop = self.client.read_json(self.client.paths()['claude_desktop'][2])['inferenceModels']
        self.assertTrue(all(any(entry['name'] == self.client.claude_desktop_route(model) for entry in desktop)
                            for model in choices))
        self.assertTrue(all('gemini' not in entry['name'] for entry in desktop))
        self.assertTrue(all(any(route['alias'] == self.client.claude_desktop_route(model) and route['name'] == model
                                for route in self.routes) for model in choices))
        codex = self.client.read_json(self.client.paths()['codex'][2])['models']
        self.assertEqual({entry['slug'] for entry in codex}, self.client.connection_models())
        self.assertEqual([next(row['default_reasoning_level'] for row in codex if row['slug']==m) for m in choices],
                         ['high', 'medium', 'low', 'medium'])
        config = tomllib.loads(self.client.paths()['codex'][0].read_text())
        self.assertEqual(config['model_catalog_json'], str(self.client.paths()['codex'][2].resolve()))
        self.client.restore()
        self.assertFalse(self.client.paths()['codex'][2].exists())

    def test_client_menu_routes_each_model_to_itself(self):
        self.controller.family_model_choices = lambda: {
            'gemini': ['gemini-pro-agent', 'gemini-3.1-pro-low', 'gemini-3-flash'],
            'claude': ['claude-sonnet-4-6', 'claude-opus-4-6-thinking']}
        self.routes = [{'alias': 'claude-sonnet-4-6', 'name': 'claude-opus-4-6-thinking'}]
        self.client.apply(['claude_desktop'])
        entries = self.client.read_json(self.client.paths()['claude_desktop'][2])['inferenceModels']
        low = self.client.claude_desktop_route('gemini-3.1-pro-low')
        self.assertIn(low, [entry['name'] for entry in entries])
        self.assertIn('claude-sonnet-4-6', [entry['name'] for entry in entries])
        self.assertNotIn('claude-opus-4-6-thinking', [entry['name'] for entry in entries])
        self.assertEqual(next(item['name'] for item in self.routes if item['alias'] == low), 'gemini-3.1-pro-low')
        self.assertFalse(any(item['alias'] == 'claude-sonnet-4-6' for item in self.routes))

    def test_approved_desktop_routes_are_restored_after_gateway_restart(self):
        self.client.write_json(self.controller.proxy_dir / 'cliproxy-models.json',
                               {'antigravity': [{'id': 'gemini-3.1-pro-low'}, {'id': 'gemini-3-flash'}]})
        self.client.apply(['claude_desktop'])
        expected = {entry['alias']: entry['name'] for entry in self.routes
                    if '-ga-' in entry['alias'] or entry['alias'] == 'claude-haiku-4-5'}
        self.assertTrue(expected)
        self.assertEqual(expected['claude-haiku-4-5'], 'gemini-3-flash')
        self.routes = [entry for entry in self.routes if entry['alias'] not in expected]
        self.assertTrue(self.client.reconcile_desktop_routes())
        self.assertEqual({entry['alias']: entry['name'] for entry in self.routes if entry['alias'] in expected}, expected)
        self.assertFalse(self.client.reconcile_desktop_routes())

    def test_desktop_routes_are_not_created_without_approved_setup(self):
        self.client.write_json(self.controller.proxy_dir / 'cliproxy-models.json',
                               {'antigravity': [{'id': 'gemini-3-flash'}]})
        self.assertFalse(self.client.reconcile_desktop_routes())
        self.assertEqual(self.routes, [])

    def test_fast_slot_repair_preserves_other_models_and_restores_backup(self):
        self.client.apply(['claude_desktop'])
        path = self.client.paths()['claude_desktop'][2]
        preset = self.client.read_json(path)
        preset['inferenceModels'].append({'name':'gemini-retired','anthropicFamilyTier':'haiku','isFamilyDefault':True})
        self.client.write_json(path, preset)
        self.assertTrue(self.client.repair_desktop_fast_slot())
        changed = self.client.read_json(path)
        self.assertNotIn('gemini-retired', [m['name'] for m in changed['inferenceModels']])
        self.assertEqual(changed['inferenceGatewayApiKey'], preset['inferenceGatewayApiKey'])
        self.assertFalse(self.client.repair_desktop_fast_slot())

    def test_unrelated_gateway_is_not_adopted(self):
        library = self.client.local / 'Claude-3p' / 'configLibrary'
        legacy = '5010c5ea-93a5-425b-aba1-6b85f3a14292'
        self.client.write_json(library / '_meta.json', {'appliedId': legacy})
        self.client.write_json(library / (legacy + '.json'), {'inferenceGatewayBaseUrl': 'https://example.com',
            'inferenceModels': [{'name': 'other', 'labelOverride': 'Gemini Pro'}]})
        self.assertIsNone(self.client.legacy_desktop_preset())
        self.assertFalse(self.client.refresh_desktop_model_labels())

    def test_tokenharbor_free_model_requires_explicit_connection_and_restores(self):
        config_path = self.controller.proxy_dir / 'config.yaml'
        config = {'server': {'host': '127.0.0.1', 'port': 8317},
                  'access': {'api-keys': ['local-key']},
                  'oauth': {'model-alias': {'antigravity': []}}}
        config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
        self.client.apply(['claude_desktop'])
        preset_path = self.client.paths()['claude_desktop'][2]
        before = self.client.read_json(preset_path)
        self.assertNotIn(CLIENT_MODEL, [entry['name'] for entry in before['inferenceModels']])
        connection = TokenHarbor(self.controller, self.client)
        with patch.object(connection, 'verify_key'), patch.object(connection, 'model_listed', return_value=True), \
             patch.object(connection, 'probe_gateway', return_value=True):
            self.assertTrue(connection.connect('thk_test-key'))
        updated = yaml.safe_load(config_path.read_text())
        group = next(entry for entry in updated['api-keys']['claude'] if entry['name'] == PROVIDER)
        self.assertEqual(group['models'][0]['name'], UPSTREAM_MODEL)
        self.assertEqual(group['models'][0]['alias'], CLIENT_MODEL)
        self.assertEqual([entry['name'] for entry in self.client.read_json(preset_path)['inferenceModels']]
                         .count(CLIENT_MODEL), 1)
        self.assertEqual(self.client.read_json(preset_path)['inferenceModels'][0], before['inferenceModels'][0])
        self.client.restore()
        restored = yaml.safe_load(config_path.read_text())
        self.assertFalse(restored.get('api-keys', {}).get('claude'))
        self.assertFalse(preset_path.exists())

    def test_tokenharbor_does_not_touch_unapproved_claude_config(self):
        config_path = self.controller.proxy_dir / 'config.yaml'
        config_path.write_text(yaml.safe_dump({'server': {'host': '127.0.0.1', 'port': 8317}}), encoding='utf-8')
        connection = TokenHarbor(self.controller, self.client)
        with patch.object(connection, 'verify_key'), patch.object(connection, 'model_listed', return_value=True), \
             patch.object(connection, 'probe_gateway', return_value=True):
            self.assertFalse(connection.connect('thk_test-key'))
        self.assertFalse(any(path.exists() for path in self.client.paths()['claude_desktop']))

    def test_tokenharbor_added_after_chatgpt_only_fresh_desktop_setup(self):
        config_path = self.controller.proxy_dir / 'config.yaml'
        config_path.write_text(yaml.safe_dump({'server': {'host': '127.0.0.1', 'port': 8317}}), encoding='utf-8')
        self.controller.chatgpt_model_choices = lambda: ['gpt-test']
        self.controller.accounts = lambda: []
        self.client.apply(['claude_desktop'])
        path = self.client.paths()['claude_desktop'][2]
        before = self.client.read_json(path)
        self.assertFalse(any(m['labelOverride'].startswith('Gemini') for m in before['inferenceModels']))
        connection = TokenHarbor(self.controller, self.client)
        with patch.object(connection, 'verify_key'), patch.object(connection, 'model_listed', return_value=True), \
             patch.object(connection, 'probe_gateway', return_value=True):
            self.assertTrue(connection.connect('thk_test-key'))
        after = self.client.read_json(path)
        self.assertEqual(after['inferenceModels'][:-1], before['inferenceModels'])
        self.assertEqual(after['inferenceModels'][-1]['name'], CLIENT_MODEL)
        self.assertFalse(after['inferenceModels'][-1]['isFamilyDefault'])
        after['inferenceModels'] = before['inferenceModels']
        self.client.write_json(path, after)
        self.assertTrue(self.client.reconcile_desktop_routes())
        self.assertFalse(self.client.reconcile_desktop_routes())
        self.assertEqual(sum(m['name'] == CLIENT_MODEL for m in self.client.read_json(path)['inferenceModels']), 1)

    def test_tokenharbor_connected_before_chatgpt_only_desktop_setup(self):
        config_path = self.controller.proxy_dir / 'config.yaml'
        config_path.write_text(yaml.safe_dump({'server': {'host': '127.0.0.1', 'port': 8317}}), encoding='utf-8')
        self.controller.chatgpt_model_choices = lambda: ['gpt-test']
        self.controller.accounts = lambda: []
        connection = TokenHarbor(self.controller, self.client)
        with patch.object(connection, 'verify_key'), patch.object(connection, 'model_listed', return_value=True), \
             patch.object(connection, 'probe_gateway', return_value=True):
            self.assertFalse(connection.connect('thk_test-key'))
        self.client.connection_models=lambda: {'gpt-test',CLIENT_MODEL}
        self.client.apply(['claude_desktop'])
        path = self.client.paths()['claude_desktop'][2]
        self.assertIn(CLIENT_MODEL, [m['name'] for m in self.client.read_json(path)['inferenceModels']])
        self.assertIsNotNone(connection.approved_desktop_preset())

    def test_tokenharbor_rolls_back_if_gateway_cannot_use_free_route(self):
        config_path = self.controller.proxy_dir / 'config.yaml'
        config_path.write_text(yaml.safe_dump({'server': {'host': '127.0.0.1', 'port': 8317}}), encoding='utf-8')
        original = config_path.read_bytes()
        connection = TokenHarbor(self.controller, self.client)
        with patch.object(connection, 'verify_key'), patch.object(connection, 'model_listed', return_value=True), \
             patch.object(connection, 'probe_gateway', return_value=False), patch('tokenharbor.time.sleep'):
            with self.assertRaises(AccountError):
                connection.connect('thk_test-key')
        self.assertEqual(config_path.read_bytes(), original)

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
    def test_codex_disables_openai_browser_and_enforces_steps_commands(self):
        paths = self.client.paths()
        codex = paths['codex'][0]
        codex.parent.mkdir(parents=True, exist_ok=True)
        codex.write_text(
            '[desktop]\nconversationDetailMode = "STEPS_PROSE"\nsansFontSize = 14\n\n'
            '[plugins."browser@openai-bundled"]\nenabled = true\n\n'
            '[mcp_servers.node_repl]\ncommand = "test"\n'
        )
        global_state = self.client.home / '.codex' / '.codex-global-state.json'
        global_state.write_text(json.dumps({'electron-persisted-atom-state': {'home-composer-mode-v1': 'work'}}))
        self.client.apply(['codex'])
        config = tomllib.loads(codex.read_text())
        self.assertEqual(config.get('desktop', {}).get('conversationDetailMode'), 'STEPS_COMMANDS')
        self.assertFalse(config.get('plugins', {}).get('browser@openai-bundled', {}).get('enabled'))
        catalog = self.client.read_json(paths['codex'][2])
        for model in catalog.get('models', []):
            self.assertTrue(model.get('node_repl_disabled'))
            self.assertFalse(model.get('supports_search_tool'))
            self.assertNotIn('web_search_tool_type', model)
        updated_state = json.loads(global_state.read_text())
        self.assertEqual(updated_state.get('electron-persisted-atom-state', {}).get('home-composer-mode-v1'), 'chat')


if __name__ == '__main__': unittest.main()
