import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App


class ProviderHighlightTests(unittest.TestCase):
    def test_card_last_model_includes_failed_requests_and_honest_alias_labels(self):
        view = SimpleNamespace(activity_state={'stats': {'a': {'last_model': 'claude-opus-4-6-thinking'}}, 'events': [], 'latest': {}})
        self.assertEqual(App.last_account_model(view, 'a'), 'Opus 4.6 Thinking')
        view.activity_state['stats'] = {}
        view.activity_state['events'] = [{'name':'a', 'at':'2026-10-07T00:00:00Z', 'model':'claude-sonnet-4-5', 'failed':True}]
        self.assertEqual(App.last_account_model(view, 'a'), '3.1 Pro Low')
        view.model_aliases = {'claude-sonnet-4-5': 'gemini-3.8-pro-high'}
        self.assertEqual(App.last_account_model(view, 'a'), '3.8 Pro High')
        view.activity_state['stats']['a'] = {'last_model': 'gemini-3.8-flash-high'}
        self.assertEqual(App.last_account_model(view, 'a'), '3.8 Flash High')
        self.assertEqual(App.last_account_model(view, 'unknown'), '')

    def test_wait_caption_is_short_and_names_actual_provider(self):
        jobs = [{'model': 'claude-opus-4-6-thinking', 'retry_at': 1000 + 151 * 3600}]
        self.assertEqual(App.quota_wait_text(jobs, now=1000), 'until Claude · 151h 00m')
        jobs.append({'model': 'claude-sonnet-4-5', 'retry_at': 1000 + 22 * 60})
        self.assertEqual(App.quota_wait_text(jobs, now=1000), 'until Claude · 151h 00m  /  until Gemini · 22m')

    def test_alias_can_select_claude_without_marking_gemini_active(self):
        view = SimpleNamespace(items=[{'name': 'a', 'disabled': False}],
            activity_state={'latest': {'claude-sonnet-4-5': {'name': 'a', 'model': 'claude-sonnet-4-5',
                'upstream_model': 'claude-opus-4-6-thinking', 'at': '2026-10-07T00:00:00Z'}}}, model_family=App.model_family)
        self.assertEqual(App.active_provider_accounts(view), {'claude': 'a'})

    def test_independent_selections_aliases_and_disabled_latest(self):
        state = {'latest': {
            'claude-sonnet-4-5': {'name': 'a', 'at': '2026-10-07T00:00:00Z'},
            'claude-opus-4-6-thinking': {'name': 'b', 'at': '2026-10-07T00:00:01Z'}}}
        view = SimpleNamespace(items=[{'name': n, 'disabled': False} for n in ('a', 'b', 'c')],
                               activity_state=state, model_family=App.model_family)
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'a', 'claude': 'b'})
        state['latest']['gemini-3.8-flash-high'] = {'name': 'c', 'at': '2026-10-07T00:00:02Z'}
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'c', 'claude': 'b'})
        state['latest']['claude-sonnet-4-6'] = {'name': 'c', 'at': '2026-10-07T00:00:03Z'}
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'c', 'claude': 'c'})
        view.items[2]['disabled'] = True
        self.assertEqual(App.active_provider_accounts(view), {})


if __name__ == '__main__': unittest.main()
