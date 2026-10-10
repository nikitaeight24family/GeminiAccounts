import sys
import unittest
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App
from backend import Controller


class QuotaUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.controller_patch = patch('app.Controller', lambda: Controller(proxy_dir=root / 'proxy', data_dir=root / 'data'))
        self.controller_patch.start()

    def tearDown(self):
        self.controller_patch.stop()
        self.temp.cleanup()

    def test_five_hour_rows_hide_below_one_percent_weekly(self):
        group = {'buckets': [{'window': '5h', 'remaining': 1},
                             {'window': 'weekly', 'remaining': .0099}]}
        self.assertEqual([b['window'] for b in App.visible_quota_buckets(group)], ['weekly'])
        group['buckets'][1]['remaining'] = .01
        self.assertEqual([b['window'] for b in App.visible_quota_buckets(group)], ['5h', 'weekly'])
        group['buckets'][1]['remaining'] = None
        self.assertEqual(len(App.visible_quota_buckets(group)), 2)

    def test_depleted_weekly_accounts_are_below_a_divider(self):
        import customtkinter as ctk
        with patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), patch.object(App, 'fetch_quota'), \
                patch.object(App, 'fetch_models'), patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'):
            app = App()
            try:
                now = datetime.now(timezone.utc)
                values = {'ready': (.01, 4), 'dead_late': (.009, 96), 'dead_early': (0, 48),
                          'verify': (0, 24)}
                for name, (remaining, hours) in values.items():
                    app.quota_cache[name] = {'data': {'groups': [{'kind': 'gemini', 'buckets': [
                        {'window': '5h', 'remaining': 1, 'reset': (now + timedelta(hours=1)).isoformat()},
                        {'window': 'weekly', 'remaining': remaining,
                         'reset': (now + timedelta(hours=hours)).isoformat()}]}]}}
                accounts = [{'name': name, 'email': name, 'disabled': False, 'unavailable': False,
                             'access_issue': 'verification' if name == 'verify' else None}
                            for name in ('dead_late', 'ready', 'verify', 'dead_early')]
                app.loaded(accounts)
                self.assertEqual([name for name, _ in app.account_layout],
                                 ['verify', 'ready', 'dead_early', 'dead_late'])
                self.assertTrue(any(index == 2 and widget.cget('height') == 1
                                    for index, widget, _ in app.account_group_widgets))
                self.assertTrue(any(widget.cget('text') == 'Weekly quota below 1% · 2'
                                    for _, widget, _ in app.account_group_widgets
                                    if isinstance(widget, ctk.CTkLabel)))
            finally:
                app.closed = True
                app.destroy()

    def test_model_selection_is_left_to_connected_clients(self):
        import customtkinter as ctk
        with patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'):
            app = App()
            try:
                buttons = []
                def collect(widget):
                    if isinstance(widget, ctk.CTkButton):
                        buttons.append(widget.cget('text'))
                    for child in widget.winfo_children():
                        collect(child)
                collect(app)
                self.assertIn('Connect applications', buttons)
                self.assertNotIn('⚙', buttons)
                self.assertFalse(hasattr(app, 'model_settings'))
            finally:
                app.closed = True
                app.destroy()

    def test_ten_accounts_fit_and_all_four_limits_remain_visible(self):
        with patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'):
            app = App()
            if hasattr(app, 'restore_details_job'):
                app.after_cancel(app.restore_details_job)
            try:
                app.controller.preferences = {'labels': {}}
                # A 4K desktop at 175% has approximately 1200 logical pixels.
                # Allow this viewport on CI desktops with smaller monitors too.
                app.maxsize(2400, 2400)
                app.geometry('1120x1180')
                items = [{'name': str(i), 'email': f'account.number{i}@gmail.com', 'disabled': False, 'unavailable': False} for i in range(10)]
                now = datetime.now(timezone.utc)
                for item in items:
                    app.quota_cache[item['name']] = {'data': {'groups': [
                        {'kind': kind, 'buckets': [
                            {'window': window, 'remaining': 1, 'reset': (now + timedelta(hours=5 if window == '5h' else 160)).isoformat()}
                            for window in ('5h', 'weekly')]}
                        for kind in ('gemini', 'claude')]}}
                app.loaded(items)
                app.update()
                canvas = app.account_list._parent_canvas
                first = app.account_widgets['0']['card']
                last = app.account_widgets['9']['card']
                self.assertLessEqual(last.winfo_rooty() + last.winfo_height(), canvas.winfo_rooty() + canvas.winfo_height())
                self.assertLess(first.winfo_height() / first._get_widget_scaling(), 105)
                app.activity_state['latest'] = {
                    'gemini-3-flash': {'name': '0', 'model': 'gemini-3-flash', 'at': now.isoformat(), 'failed': False},
                    'claude-opus-4-6-thinking': {'name': '1', 'model': 'claude-opus-4-6-thinking',
                                               'at': now.isoformat(), 'failed': False}}
                app.gateway_jobs = [{'model': 'gemini-3-flash', 'state': 'running'}, {'model': 'claude-opus-4-6-thinking', 'state': 'running'}]
                app.gateway_jobs_checked = time.monotonic()
                app.animate_active_borders()
                self.assertEqual(app.active_account_names(), {'0', '1'})
                self.assertEqual(app.active_provider_accounts(), {'gemini': '0', 'claude': '1'})
                self.assertEqual(app.account_widgets['0']['active_families'], ('gemini',))
                self.assertEqual(app.account_widgets['1']['active_families'], ('claude',))
                app.activity_state['stats']['0'] = {'last_model': 'claude-sonnet-4-6', 'last': datetime.now(timezone.utc).isoformat()}
                app.animate_active_borders()
                app.update()
                heading = app.account_widgets['0']['button']
                model_items = heading._canvas.find_withtag('last_model')
                self.assertEqual(len(model_items), 2)
                self.assertEqual(heading._canvas.itemcget(model_items[-1], 'text'), '3 Flash')
                self.assertLess(heading._canvas.bbox(model_items[-1])[2], heading.winfo_width())
                canvas_active = app.account_widgets['1']['card']._canvas
                segments = canvas_active.find_withtag('rainbow')
                self.assertGreater(len(segments), 50)
                self.assertGreater(len({canvas_active.itemcget(i, 'fill') for i in segments}), 20)
                self.assertTrue(first._canvas.find_withtag('rainbow'))
                old_colors = [canvas_active.itemcget(i, 'fill') for i in segments]
                app.draw_rainbow_border(app.account_widgets['1'], .5)
                self.assertNotEqual(old_colors, [canvas_active.itemcget(i, 'fill') for i in segments])
                # A newer Gemini request leaves Claude's subscription selected.
                app.activity_state['latest']['gemini-3-flash'] = {
                    'name': '2', 'model': 'gemini-3-flash', 'at': datetime.now(timezone.utc).isoformat()}
                app.animate_active_borders()
                self.assertEqual(app.active_provider_accounts(), {'gemini': '2', 'claude': '1'})
                self.assertFalse(first._canvas.find_withtag('rainbow'))
                self.assertTrue(canvas_active.find_withtag('rainbow'))
                # Both services can select the same account with both badges.
                app.activity_state['latest']['claude-opus-4-6-thinking'] = {
                    'name': '2', 'model': 'claude-opus-4-6-thinking', 'at': datetime.now(timezone.utc).isoformat()}
                app.animate_active_borders()
                self.assertEqual(app.active_account_names(), {'2'})
                self.assertEqual(app.account_widgets['2']['active_families'], ('gemini', 'claude'))
                app.update()
                badge_canvas = app.account_widgets['2']['button']._canvas
                for family in ('gemini', 'claude'):
                    self.assertTrue(badge_canvas.find_withtag('active_' + family))
                self.assertEqual(app.total_quota_bar.get(), 1)
                self.assertEqual(app.total_weekly_bar.get(), 1)
                # Exhausted accounts contribute zero; missing quotas stay unknown.
                app.quota_cache['0']['data']['groups'][0]['buckets'][0]['remaining'] = 0
                app.update_total_quota()
                self.assertAlmostEqual(app.total_quota_bar.get(), .9)
                self.assertEqual(app.total_weekly_bar.get(), 1)
                app.update()
                self.assertTrue(app.forecast_canvas.winfo_ismapped())
                self.assertFalse(app.total_quota_bar.winfo_ismapped())
                app.quota_cache['0']['data']['groups'][0]['buckets'][1]['remaining'] = 0
                app.update_total_quota()
                app.update()
                self.assertAlmostEqual(app.total_weekly_bar.get(), .9)
                self.assertTrue(app.weekly_forecast_canvas.winfo_ismapped())
                self.assertTrue(app.weekly_forecast_canvas.find_withtag('forecast_time'))
                for item in app.forecast_canvas.find_withtag('forecast_label'):
                    left, top, right, bottom = app.forecast_canvas.bbox(item)
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(right, app.forecast_canvas.winfo_width())
                    self.assertLessEqual(bottom, app.forecast_canvas.winfo_height())
                app.total_forecast = [
                    {'reset': (now + timedelta(hours=1)).isoformat(), 'remaining': .99},
                    {'reset': (now + timedelta(hours=4)).isoformat(), 'remaining': 1}]
                app.draw_total_forecast()
                markers = app.forecast_canvas.find_withtag('forecast_time')
                margin = 3 * app.sidebar._get_widget_scaling()
                span = app.forecast_canvas.winfo_width() - 2 * margin
                coords = app.forecast_canvas.coords(markers[0])
                ratio = ((coords[0] + coords[2]) / 2 - margin) / span
                self.assertAlmostEqual(ratio, .99, delta=.01)
                for label in app.forecast_canvas.find_withtag('forecast_label'):
                    self.assertNotIn('%', app.forecast_canvas.itemcget(label, 'text'))
                app.quota_cache['1'] = {'error': 'offline'}
                app.update_total_quota()
                self.assertAlmostEqual(app.total_quota_bar.get(), 8 / 9)
                self.assertIn('9/10', app.total_quota_title.cget('text'))
                items[0]['disabled'] = True
                app.update_total_quota()
                self.assertEqual(app.total_quota_bar.get(), 1)
                for widgets in app.account_widgets.values():
                    self.assertNotIn('toggle', widgets)
                    self.assertEqual(len(widgets['quotas']), 4)
                    self.assertTrue(widgets['quota_frame'].winfo_ismapped())
                    for key, (label, bar) in widgets['quotas'].items():
                        timer = widgets['countdown'][key]
                        self.assertTrue(bar.winfo_ismapped())
                        self.assertLessEqual(label.winfo_rootx() + label.winfo_width(), bar.winfo_rootx())
                        self.assertLessEqual(bar.winfo_rootx() + bar.winfo_width(), timer.winfo_rootx())
            finally:
                app.close()

    def test_refresh_preserves_widgets_input_focus_and_scroll(self):
        fetch_quota, fetch_models = App.fetch_quota, App.fetch_models
        with patch.object(App, 'connection_settings'), patch.object(App, 'refresh'), patch.object(App, 'fetch_quota'), patch.object(App, 'fetch_models'), patch.object(App, 'start_activity'), patch.object(App, 'queue_policy'):
            app = App()
            if hasattr(app, 'restore_details_job'):
                app.after_cancel(app.restore_details_job)
            try:
                app.controller.preferences = {'labels': {}}
                items = [{'name': str(i), 'email': 'Account ' + str(i), 'disabled': False, 'unavailable': False} for i in range(4)]
                app.model_cache['0'] = ['claude-sonnet-4-5', 'claude-sonnet-4-6']
                app.loaded(items)
                app.update()
                app.rename_entry.insert(0, 'Unsaved name')
                app.rename_entry._entry.focus_force()
                app.detail._parent_canvas.yview_moveto(.6)
                app.account_list._parent_canvas.yview_moveto(.4)
                app.update()
                entry = app.rename_entry
                focus = app.focus_get()
                detail_children = app.detail.winfo_children()
                sidebar_children = app.account_list.winfo_children()
                detail_scroll = app.detail._parent_canvas.yview()
                sidebar_scroll = app.account_list._parent_canvas.yview()
                def work(fn, done, mutation=False):
                    done(fn())
                app.work = work
                app.controller.quotas = lambda a: {'groups': [
                    {'kind': kind, 'name': kind, 'buckets': [
                        {'window': '5h', 'remaining': .25, 'reset': '2026-10-07T00:00:00Z'},
                        {'window': 'weekly', 'remaining': .7}]} for kind in ('gemini', 'claude')],
                    'models': {'claude-sonnet-4-5': {'remaining': .25}}}
                # Exercise the real completion handler, including all sidebar accounts.
                for account in items:
                    fetch_quota(app, account['name'])
                app.controller.models = lambda a: ['claude-sonnet-4-6', 'claude-sonnet-4-5']
                fetch_models(app, '0')
                app.loaded([dict(a) for a in items])
                app.update()
                self.assertIs(app.rename_entry, entry)
                self.assertEqual(entry.get(), 'Unsaved name')
                now = datetime.now(timezone.utc)
                app.quota_cache = {}
                for name, minutes, days in [('0', 22, 6), ('1', 240, 7)]:
                    app.quota_cache[name] = {'data': {'groups': [{'kind': 'gemini', 'name': 'Gemini', 'buckets': [
                        {'window': '5h', 'reset': (now + timedelta(minutes=minutes)).isoformat()},
                        {'window': 'weekly', 'reset': (now + timedelta(days=days)).isoformat()}]}]}}
                    app.update_countdown(name)
                app.update_countdown('0')
                short = app.account_widgets['0']['countdown'][('gemini', '5h')].cget('text_color')
                long = app.account_widgets['1']['countdown'][('gemini', '5h')].cget('text_color')
                self.assertGreater(int(short[3:5], 16), int(short[1:3], 16))
                self.assertGreater(int(long[1:3], 16), int(long[3:5], 16))
                weekly = app.account_widgets['0']['countdown'][('gemini', 'weekly')].cget('text_color')
                self.assertGreater(int(weekly[1:3], 16), int(weekly[3:5], 16))
                # Five days must remain red even with a single account in the pool.
                single = App.reset_color((now + timedelta(days=5, hours=21)).isoformat(), now, (0, 7 * 86400))
                self.assertGreater(int(single[1:3], 16), int(single[3:5], 16))
                app.render_activity()
                app.change_view('Routing statistics')
                app.update()
                self.assertTrue(app.stats_view._parent_frame.winfo_ismapped())
                self.assertFalse(app.detail._parent_frame.winfo_ismapped())
                app.change_view('Account and quotas')
                app.update()
                self.assertTrue(app.detail._parent_frame.winfo_ismapped())
                self.assertIs(app.rename_entry, entry)
                with patch.object(app.controller, 'save'):
                    app.toggle_details()
                    app.update()
                    self.assertTrue(app.details_collapsed)
                    self.assertFalse(app.body.winfo_ismapped())
                    self.assertTrue(app.account_list._parent_frame.winfo_ismapped())
                    self.assertTrue(app.geometry().startswith('280x'))
                    selected = app.selected
                    app.select(items[1])
                    self.assertEqual(app.selected, selected)
                    for widgets in app.account_widgets.values():
                        self.assertEqual(widgets['card'].cget('border_color'), '#344155')
                        self.assertEqual(widgets['button'].cget('fg_color'), '#222a38')
                        self.assertFalse(widgets['button'].cget('hover'))
                    app.toggle_details()
                    app.update()
                    self.assertFalse(app.details_collapsed)
                    self.assertTrue(app.body.winfo_ismapped())
                    self.assertIs(app.rename_entry, entry)
                    self.assertEqual(app.account_widgets[selected]['card'].cget('border_color'), '#739aff')
                self.assertEqual(app.focus_get(), focus)
                self.assertEqual(app.detail.winfo_children(), detail_children)
                self.assertEqual(app.account_list.winfo_children(), sidebar_children)
                self.assertEqual(app.detail._parent_canvas.yview(), detail_scroll)
                self.assertEqual(app.account_list._parent_canvas.yview(), sidebar_scroll)
                self.assertEqual(app.detail_quota_widgets[('gemini', 'weekly')][1].get(), .7)
                self.assertEqual(len(app.detail_quota_widgets), 4)
                self.assertEqual(app.model_widgets, {})
                self.assertEqual(app.account_widgets['1']['quotas'][('claude', '5h')][1].get(), .25)
                # Newly arriving model catalogs only replace their own section.
                app.controller.models = lambda a: ['claude-sonnet-4-5']
                fetch_models(app, '0')
                self.assertIs(app.rename_entry, entry)
                self.assertEqual(entry.get(), 'Unsaved name')
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
