import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from model_inventory import ModelInventory
from integrations import Integrations


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.accounts = [{'name': 'first', 'provider': 'antigravity'}, {'name': 'second', 'provider': 'codex'}]
        self.models = {'first': ['gemini-old'], 'second': ['gpt-current']}
        def request(path):
            if path == '/auth-files': return {'files': self.accounts}
            from urllib.parse import parse_qs, urlsplit
            name = parse_qs(urlsplit(path).query)['name'][0]
            if self.models[name] is None: raise OSError('offline')
            return {'models': [{'id': m} for m in self.models[name]]}
        self.state = {}
        self.inventory = ModelInventory(SimpleNamespace(request=request), self.state, lambda: self.now)

    def test_new_models_added_and_old_removed_after_confirmation(self):
        self.inventory.refresh()
        self.models['first'] = ['gemini-new']
        self.assertEqual(self.inventory.refresh(), {'gemini-old', 'gemini-new', 'gpt-current'})
        self.now += 61
        self.assertEqual(self.inventory.refresh(), {'gemini-new', 'gpt-current'})
        self.assertEqual(self.state['accounts']['second']['provider'], 'codex')

    def test_partial_failure_does_not_commit_or_retire(self):
        self.inventory.refresh(); before = copy.deepcopy(self.state)
        self.models['first'] = []; self.models['second'] = None; self.now += 300
        with self.assertRaises(OSError): self.inventory.refresh()
        self.assertEqual(self.state, before)

    def test_model_available_on_other_account_is_not_retired(self):
        self.models['second'] = ['gemini-old']; self.inventory.refresh()
        self.models['first'] = []; self.now += 300
        self.assertIn('gemini-old', self.inventory.refresh())

    def test_reappearance_cancels_retirement(self):
        self.inventory.refresh(); self.models['first'] = []; self.inventory.refresh()
        self.now += 61; self.models['first'] = ['gemini-old']; self.inventory.refresh()
        self.assertNotIn('gemini-old', self.state['missing'])


class MenuSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.controller = SimpleNamespace(data_dir=root, family_model_choices=lambda: {'gemini': [], 'claude': []}, chatgpt_model_choices=lambda: [])
        self.i = Integrations(self.controller, root/'home', root/'local')
        self.i.configure_desktop_routes = Mock()

    def tearDown(self): self.tmp.cleanup()

    def test_desktop_add_remove_preserves_settings_without_new_default(self):
        route = self.i.claude_desktop_route('gemini-new')
        doc = {'userSetting': True, 'inferenceModels': [{'name': 'old', 'isFamilyDefault': True}]}
        self.assertTrue(self.i.sync_model_menu('claude_desktop', doc, {'gemini-new'}))
        saved = self.i.read_json(self.i.paths()['claude_desktop'][2])
        self.assertTrue(saved['userSetting'])
        self.assertEqual([m['name'] for m in saved['inferenceModels']], [route])
        self.assertTrue(saved['inferenceModels'][0]['isFamilyDefault'])
        self.assertFalse(self.i.sync_model_menu('claude_desktop', saved, {'gemini-new'}))

    def test_cli_discovers_models_and_keeps_explicit_choice(self):
        doc = {'availableModels': ['gemini-current'],
               'env': {'ANTHROPIC_MODEL': 'retired', 'OTHER': 'keep'}}
        self.i.sync_model_menu('claude_cli', doc, {'new'})
        saved = self.i.read_json(self.i.paths()['claude_cli'][0])
        self.assertEqual(saved['env']['ANTHROPIC_MODEL'], 'new')
        self.assertNotIn('availableModels', saved)
        self.assertEqual(saved['env']['OTHER'], 'keep')
        self.assertEqual(saved['env']['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'], '1')

    def test_codex_owned_catalog_reconciled_without_changing_selection(self):
        path = self.i.paths()['codex'][2]
        self.i.write_json(path, {'models': [{'slug': 'gpt-old', 'custom': 'keep'}]})
        doc = {'model_catalog_json': str(path), 'model': 'gpt-old'}
        self.assertTrue(self.i.sync_model_menu('codex', doc, {'gpt-new'}))
        self.assertEqual([m['slug'] for m in self.i.read_json(path)['models']], ['gpt-new'])
        self.assertEqual(doc['model'], 'gpt-old')
        self.assertFalse(self.i.sync_model_menu('codex', doc, {'gpt-new'}))

    def test_codex_repopulates_after_confirmed_empty_catalog(self):
        path = self.i.paths()['codex'][2]
        self.i.write_json(path, {'models':[{'slug':'old','custom':'preserved'}]})
        doc={'model_catalog_json':str(path)}
        self.i.sync_model_menu('codex',doc,set())
        self.assertEqual(self.i.read_json(path)['models'],[])
        self.i.sync_model_menu('codex',doc,{'gpt-next'})
        self.assertEqual(self.i.read_json(path)['models'][0]['slug'],'gpt-next')
        self.assertFalse(self.i.sync_model_menu('codex',doc,{'gpt-next'}))

    def test_cli_keeps_current_choice_but_retires_old_slots(self):
        doc={'env':{'ANTHROPIC_MODEL':'gemini-current','ANTHROPIC_DEFAULT_SONNET_MODEL':'gemini-old','OTHER':'keep'}}
        self.i.sync_model_menu('claude_cli',doc,{'gemini-current','gemini-future'})
        saved=self.i.read_json(self.i.paths()['claude_cli'][0])
        self.assertEqual(saved['env']['ANTHROPIC_MODEL'],'gemini-current')
        self.assertNotEqual(saved['env']['ANTHROPIC_DEFAULT_SONNET_MODEL'],'gemini-old')
        self.assertNotIn('availableModels', saved)
        self.assertFalse(self.i.sync_model_menu('claude_cli',saved,{'gemini-current','gemini-future'}))

    def test_oauth_sync_preserves_separately_managed_tokenharbor(self):
        from tokenharbor import CLIENT_MODEL
        entry = {'name': CLIENT_MODEL, 'labelOverride': 'Free model', 'isFamilyDefault': False}
        self.i.sync_model_menu('claude_desktop', {'inferenceModels': [entry]}, {'gemini-new', CLIENT_MODEL})
        saved = self.i.read_json(self.i.paths()['claude_desktop'][2])
        self.assertIn(entry, saved['inferenceModels'])


class DynamicPolicyTests(unittest.TestCase):
    def test_future_catalog_drives_pings_without_version_constants(self):
        from model_policy import select_model
        self.assertEqual(select_model({'gpt-92-luna','gpt-91-luna','gpt-99-sol'}, family='gpt',cheap=True), 'gpt-92-luna')
        self.assertEqual(select_model({'claude-haiku-92','claude-opus-99'}, family='claude',cheap=True), 'claude-haiku-92')
        self.assertIsNone(select_model({'gemini-99-pro-high','gpt-image-99'},cheap=True))

    def test_aliases_and_non_text_models_do_not_duplicate_picker(self):
        from model_policy import canonical_models
        self.assertEqual(canonical_models({'gemini-99-low','gemini-selected','gemini-99-image'}, {'gemini-selected':'gemini-99-low'}), {'gemini-99-low'})
