import sys
import unittest
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App


class ProviderHighlightTests(unittest.TestCase):
    def test_card_last_model_includes_failed_requests_and_honest_alias_labels(self):
        now = datetime.now(timezone.utc).isoformat()
        view = SimpleNamespace(activity_state={'stats': {'a': {'last_model': 'claude-opus-4-6-thinking', 'last': now}}, 'events': [], 'latest': {}})
        self.assertEqual(App.last_account_model(view, 'a'), 'Opus 4.6 Thinking')
        view.activity_state['stats'] = {}
        view.activity_state['events'] = [{'name':'a', 'at':now, 'model':'claude-sonnet-4-5', 'failed':True}]
        self.assertEqual(App.last_account_model(view, 'a'), '3.1 Pro Low')
        view.model_aliases = {'claude-sonnet-4-5': 'gemini-3.8-pro-high'}
        self.assertEqual(App.last_account_model(view, 'a'), '3.8 Pro High')
        view.activity_state['stats']['a'] = {'last_model': 'gemini-3.8-flash-high', 'last': now}
        self.assertEqual(App.last_account_model(view, 'a'), '3.8 Flash High')
        self.assertEqual(App.last_account_model(view, 'unknown'), '')

    def test_idle_waiting_and_stale_status_do_not_highlight_and_models_expire(self):
        now = datetime.now(timezone.utc)
        view = SimpleNamespace(items=[{'name': 'a'}], model_family=App.model_family,
            activity_state={'latest': {'gemini-3-flash': {'name': 'a', 'model': 'gemini-3-flash', 'at': now.isoformat()}},
                            'stats': {'a': {'last_model': 'gemini-3-flash', 'last': now.isoformat()}}},
            gateway_jobs=[], gateway_jobs_checked=time.monotonic())
        self.assertEqual(App.active_provider_accounts(view), {})
        view.gateway_jobs = [{'model': 'gemini-3-flash', 'state': 'running'}]
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'a'})
        view.gateway_jobs[0]['state'] = 'waiting'
        self.assertEqual(App.active_provider_accounts(view), {})
        view.gateway_jobs[0]['state'] = 'running'
        view.gateway_jobs_checked -= 11
        self.assertEqual(App.active_provider_accounts(view), {})
        self.assertEqual(App.last_account_model(view, 'a', now + timedelta(seconds=59)), '3 Flash')
        self.assertEqual(App.last_account_model(view, 'a', now + timedelta(seconds=60)), '')

    def test_wait_caption_is_short_and_names_actual_provider(self):
        jobs = [{'model': 'claude-opus-4-6-thinking', 'retry_at': 1000 + 151 * 3600}]
        self.assertEqual(App.quota_wait_text(jobs, now=1000), 'until Claude · 151h 00m')
        jobs.append({'model': 'claude-sonnet-4-5', 'retry_at': 1000 + 22 * 60})
        self.assertEqual(App.quota_wait_text(jobs, now=1000), 'until Claude · 151h 00m  /  until Gemini · 22m')

    def test_alias_can_select_claude_without_marking_gemini_active(self):
        view = SimpleNamespace(items=[{'name': 'a', 'disabled': False}],
            activity_state={'latest': {'claude-sonnet-4-5': {'name': 'a', 'model': 'claude-sonnet-4-5',
                'upstream_model': 'claude-opus-4-6-thinking', 'at': '2026-10-07T00:00:00Z'}}}, model_family=App.model_family,
                gateway_jobs=[{'model': 'claude-opus-4-6-thinking', 'state': 'running'}], gateway_jobs_checked=time.monotonic())
        self.assertEqual(App.active_provider_accounts(view), {'claude': 'a'})

    def test_independent_selections_aliases_and_disabled_latest(self):
        state = {'latest': {
            'claude-sonnet-4-5': {'name': 'a', 'at': '2026-10-07T00:00:00Z'},
            'claude-opus-4-6-thinking': {'name': 'b', 'at': '2026-10-07T00:00:01Z'}}}
        view = SimpleNamespace(items=[{'name': n, 'disabled': False} for n in ('a', 'b', 'c')],
                               activity_state=state, model_family=App.model_family,
                               gateway_jobs=[{'model': 'gemini-3-flash', 'state': 'running'}, {'model': 'claude-opus-4-6-thinking', 'state': 'running'}],
                               gateway_jobs_checked=time.monotonic())
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'a', 'claude': 'b'})
        state['latest']['gemini-3.8-flash-high'] = {'name': 'c', 'at': '2026-10-07T00:00:02Z'}
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'c', 'claude': 'b'})
        state['latest']['claude-sonnet-4-6'] = {'name': 'c', 'at': '2026-10-07T00:00:03Z'}
        self.assertEqual(App.active_provider_accounts(view), {'gemini': 'c', 'claude': 'c'})
        view.items[2]['disabled'] = True
        self.assertEqual(App.active_provider_accounts(view), {})


if __name__ == '__main__': unittest.main()
