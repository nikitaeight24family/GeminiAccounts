import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

from backend import Controller, AccountError
from integrations import Integrations
from model_names import model_name


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.controller = Controller(proxy_dir=root / 'proxy', data_dir=root / 'data')
        self.controller.proxy_dir.mkdir()
        self.entries = [{'alias': 'claude-sonnet-4-5', 'name': 'gemini-3.1-pro-low', 'fork': True},
                        {'alias': 'claude-haiku-4-5', 'name': 'gemini-3.8-flash-high', 'fork': True},
                        {'alias': 'custom', 'name': 'gemini-3-flash'}]
        self.config = self.controller.proxy_dir / 'config.yaml'
        self.config.write_text(yaml.safe_dump({'oauth': {'model-alias': {'antigravity': self.entries}}}), encoding='utf-8')
        self.controller.accounts = lambda: [{'name': 'a', 'auth_index': 'A', 'disabled': False}]
        self.controller.models = lambda account: ['gemini-3.1-pro-low', 'gemini-pro-agent', 'gemini-3.8-flash-high', 'gemini-3-flash', 'gemini-3.1-flash-image', 'gemini-3.5-flash-lite', 'claude-opus-4-6-thinking', 'claude-sonnet-4-6', 'gpt-oss-120b-medium']
        self.calls = []
        self.controller.request = self.request

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, method='GET', payload=None):
        self.calls.append((path, method, payload))
        if method == 'GET':
            return {'oauth-model-alias': {'antigravity': self.entries, 'other-provider': [{'alias': 'keep', 'name': 'original'}]}}
        self.entries = payload['aliases']
        self.config.write_text(yaml.safe_dump({'oauth': {'model-alias': {'antigravity': self.entries}}}), encoding='utf-8')
        return {'status': 'ok'}

    def test_high_uses_real_upstream_id_and_preserves_other_aliases(self):
        result = self.controller.set_model_choices('gemini-pro-agent', 'gemini-3.8-flash-high')
        self.assertEqual(result['claude-sonnet-4-5'], 'gemini-pro-agent')
        self.assertEqual(result['custom'], 'gemini-3-flash')
        self.assertEqual(model_name('gemini-pro-agent'), '3.1 Pro High')
        path, method, payload = self.calls[-1]
        self.assertEqual((path, method, payload['provider']), ('/oauth-model-alias', 'PATCH', 'antigravity'))
        self.assertTrue(self.entries[0]['force-mapping'])
        self.assertEqual(self.controller.model_aliases()['claude-sonnet-4-5'], 'gemini-pro-agent')

    def test_unknown_models_are_not_silently_applied(self):
        with self.assertRaises(AccountError):
            self.controller.set_model_choices('gemini-3.1-pro-high-does-not-exist', 'gemini-3-flash')
        self.assertEqual(self.calls, [])
        self.assertNotIn('gemini-3.1-flash-image', self.controller.model_choices()['flash'])

    def test_every_text_model_can_be_chosen_for_either_slot(self):
        choices = self.controller.model_choices()
        for group in ('pro', 'flash'):
            for model in ('claude-opus-4-6-thinking', 'claude-sonnet-4-6', 'gemini-3.5-flash-lite', 'gpt-oss-120b-medium'):
                self.assertIn(model, choices[group])
        result = self.controller.set_model_choices('claude-opus-4-6-thinking', 'gemini-3.5-flash-lite')
        self.assertEqual(result['claude-sonnet-4-5'], 'claude-opus-4-6-thinking')

    def test_previous_requests_keep_their_original_model(self):
        state = {'stats': {'a': {'last_model': 'claude-sonnet-4-5'}}, 'events': [
            {'name': 'a', 'model': 'claude-sonnet-4-5', 'reason': 'Response received'}]}
        path = self.controller.data_dir / 'activity.json'
        path.write_text(json.dumps(state))
        self.controller.set_model_choices('gemini-pro-agent', 'gemini-3.8-flash-high')
        saved = json.loads(path.read_text())
        self.assertEqual(saved['stats']['a']['last_model'], 'gemini-3.1-pro-low')
        self.assertEqual(saved['events'][0]['upstream_model'], 'gemini-3.1-pro-low')

    def test_new_codex_setup_uses_the_selected_model(self):
        self.controller.set_model_choices('gemini-pro-agent', 'gemini-3.8-flash-high')
        client = Integrations(self.controller, Path(self.temp.name) / 'home', Path(self.temp.name) / 'local')
        (self.controller.proxy_dir / 'client-key.txt').write_text('test-key')
        client.apply(['codex'])
        import tomllib
        self.assertEqual(tomllib.loads(client.paths()['codex'][0].read_text())['model'], 'gemini-pro-agent')


if __name__ == '__main__': unittest.main()
