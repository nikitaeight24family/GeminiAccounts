import ctypes
import copy
import queue
import threading
import time
import webbrowser
from pathlib import Path
import os
import sys
import math
import colorsys
from PIL import Image, ImageDraw, ImageTk
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import customtkinter as ctk
from tkinter import messagebox
from tkinter import Canvas, font as tkfont
from backend import Controller, AccountError
from activity import Activity
from routing import rank_accounts, quota_projection
from integrations import Integrations
from model_names import model_name

BG = '#10141d'
PANEL = '#191f2b'
CARD = '#222a38'
TEXT = '#edf2fa'
MUTED = '#9daec4'
ACCENT = '#739aff'
GREEN = '#66d7b0'
SIDEBAR_WIDTH = 280

MODEL_LABELS = {'claude-sonnet-4-5': 'Gemini 3.1 Pro Low', 'claude-haiku-4-5': 'Gemini 3 Flash',
                'claude-sonnet-4-6': 'Claude Sonnet 4.6', 'claude-opus-4-6-thinking': 'Claude Opus 4.6 Thinking'}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('Gemini Accounts')
        icon = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'app.ico'
        if icon.exists():
            self.iconbitmap(str(icon))
        # Use the available desktop height, including Windows display scaling.
        work_area = ctypes.wintypes.RECT()
        available = 760
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work_area), 0):
            available = self._reverse_window_scaling(work_area.bottom - work_area.top) - 48
        self.geometry(f'1120x{max(680, min(available, 1300))}')
        self.minsize(990, 680)
        self.configure(fg_color=BG)
        self.controller = Controller()
        self.model_aliases = self.controller.model_aliases()
        self.integrations = Integrations(self.controller)
        self.provider_icons = self.make_provider_icons()
        self.mailbox = queue.Queue()
        self.items = []
        self.selected = None
        self.model_cache = {}
        self.quota_cache = {}
        self.quota_pending = set()
        self.account_widgets = {}
        self.detail_account = object()
        self.detail_quota_widgets = {}
        self.model_widgets = {}
        self.drawn_models = None
        self.busy = False
        self.pending_login = None
        self.login_url = None
        self.activity = Activity(self.controller.data_dir / 'activity.json')
        self.activity_state = copy.deepcopy(self.activity.state)
        self.activity_started = False
        self.activity_busy = False
        self.activity_rows = {}
        self.policy_busy = False
        self.policy_job = None
        self.policy_rows = []
        self.policy_group = 'gemini'
        self.details_collapsed = False
        self.expanded_geometry = None
        self.closed = False
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=PANEL)
        self.sidebar.grid(row=0, column=0, sticky='nsew')
        self.sidebar.grid_propagate(False)
        self.grid_columnconfigure(0, minsize=round(self.sidebar._apply_widget_scaling(SIDEBAR_WIDTH)))
        sidebar_header = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        sidebar_header.pack(fill='x', padx=16, pady=(3, 4))
        ctk.CTkLabel(sidebar_header, text='✦  Gemini Accounts', height=22, font=('Segoe UI', 18, 'bold'), text_color=TEXT).pack(side='left')
        self.details_toggle = self.button(sidebar_header, '☰', self.toggle_details)
        self.details_toggle.configure(height=26, width=28, font=('Segoe UI', 20), fg_color='transparent')
        self.details_toggle.pack(side='right')
        self.models_button = self.button(sidebar_header, '⚙', self.model_settings)
        self.models_button.configure(height=26, width=24, font=('Segoe UI', 17), fg_color='transparent')
        self.models_button.pack(side='right', padx=(0, 3))
        self.add_button = self.button(self.sidebar, '+  Add Google account', self.add_account, primary=True)
        self.add_button.configure(height=30)
        self.add_button.pack(fill='x', padx=16, pady=(0, 6))
        self.account_list = ctk.CTkScrollableFrame(self.sidebar, fg_color='transparent')
        self.account_list.pack(fill='both', expand=True, padx=12)
        self.account_list._scrollbar.grid_remove()
        self.service = ctk.CTkLabel(self.sidebar, text='Connecting…', text_color=MUTED, font=('Segoe UI', 10), height=14)
        self.service.pack(anchor='w', padx=18)
        self.total_quota_frame = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        self.total_quota_frame.pack(fill='x', padx=18, pady=(0, 5))
        total_header = ctk.CTkFrame(self.total_quota_frame, fg_color='transparent')
        total_header.pack(fill='x')
        self.total_quota_title = ctk.CTkLabel(total_header, text='Gemini · 5h · pooled remaining', height=18, font=('Segoe UI', 11), text_color=TEXT)
        self.total_quota_title.pack(side='left')
        self.total_quota_value = ctk.CTkLabel(total_header, text='—', height=18, font=('Segoe UI', 12, 'bold'), text_color=MUTED)
        self.total_quota_value.pack(side='right')
        self.total_quota_bar = ctk.CTkProgressBar(self.total_quota_frame, height=6, fg_color='#354157', progress_color=GREEN)
        self.total_quota_bar.pack(fill='x', pady=(1, 0))
        self.total_quota_bar.set(0)
        self.total_forecast = []
        self.total_remaining = None
        self.forecast_canvas = Canvas(self.total_quota_frame, height=1, bg=PANEL, highlightthickness=0, borderwidth=0)
        self.forecast_font = tkfont.Font(family='Segoe UI', size=-round(9 * self.sidebar._get_widget_scaling()))
        self.forecast_canvas.bind('<Configure>', lambda event: self.schedule_total_forecast())
        self.forecast_canvas.bind('<Motion>', self.hover_forecast)
        self.forecast_canvas.bind('<Leave>', lambda event: self.forecast_canvas.delete('forecast_hover'))
        weekly_frame = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        weekly_frame.pack(fill='x', padx=18, pady=(0, 6))
        weekly_header = ctk.CTkFrame(weekly_frame, fg_color='transparent')
        weekly_header.pack(fill='x')
        self.total_weekly_title = ctk.CTkLabel(weekly_header, text='Gemini · 1w · pooled remaining',
            height=18, font=('Segoe UI', 11), text_color=TEXT)
        self.total_weekly_title.pack(side='left')
        self.total_weekly_value = ctk.CTkLabel(weekly_header, text='—', height=18,
            font=('Segoe UI', 12, 'bold'), text_color=MUTED)
        self.total_weekly_value.pack(side='right')
        self.total_weekly_bar = ctk.CTkProgressBar(weekly_frame, height=6,
            fg_color='#354157', progress_color=GREEN)
        self.total_weekly_bar.pack(fill='x', pady=(1, 0))
        self.total_weekly_bar.set(0)
        self.total_weekly_forecast = []
        self.weekly_forecast_canvas = Canvas(weekly_frame, height=1, bg=PANEL, highlightthickness=0, borderwidth=0)
        self.weekly_forecast_canvas.bind('<Configure>', lambda event: self.schedule_total_forecast(weekly=True))
        self.weekly_forecast_canvas.bind('<Motion>', lambda event: self.hover_forecast(event, weekly=True))
        self.weekly_forecast_canvas.bind('<Leave>', lambda event: self.weekly_forecast_canvas.delete('forecast_hover'))
        self.body = ctk.CTkFrame(self, fg_color='transparent')
        self.body.grid(row=0, column=1, sticky='nsew', padx=32, pady=28)
        body_header = ctk.CTkFrame(self.body, fg_color='transparent')
        body_header.pack(fill='x')
        ctk.CTkLabel(body_header, text='Saved accounts', font=('Segoe UI', 30, 'bold'), text_color=TEXT).pack(side='left')
        self.button(body_header, 'Connect applications', self.connection_settings).pack(side='right')
        ctk.CTkLabel(self.body, text='Switch accounts while continuing your Claude sessions.', text_color=MUTED, font=('Segoe UI', 14)).pack(anchor='w', pady=(4, 24))
        self.mode_frame = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=14)
        self.mode_frame.pack(fill='x', pady=(0, 18))
        self.mode_label = ctk.CTkLabel(self.mode_frame, text='Loading accounts…', font=('Segoe UI', 14, 'bold'), text_color=TEXT)
        self.mode_label.pack(anchor='w', padx=18, pady=(15, 4))
        self.mode_note = ctk.CTkLabel(self.mode_frame, text='Connected clients use the selected accounts.', text_color=MUTED, font=('Segoe UI', 12))
        self.mode_note.pack(anchor='w', padx=18, pady=(0, 12))
        self.pool_button = self.button(self.mode_frame, 'Use all • automatic routing', lambda: self.action(lambda: self.controller.route(), 'Automatic routing enabled.'))
        self.pool_button.pack(anchor='w', padx=18, pady=(0, 15))
        self.mode_activity = ctk.CTkLabel(self.mode_frame, text='Last request: waiting for proxy data', text_color=MUTED, font=('Segoe UI', 12), anchor='w')
        self.mode_activity.pack(fill='x', padx=18, pady=(0, 10), before=self.pool_button)
        self.detail = ctk.CTkScrollableFrame(self.body, fg_color='transparent')
        self.detail.pack(fill='both', expand=True)
        self.stats_view = ctk.CTkScrollableFrame(self.body, fg_color='transparent')
        self.stats_title = self.label(self.stats_view, 'Automatic routing', 22, bold=True)
        self.stats_strategy = self.label(self.stats_view, 'Starting monitoring…', 13, MUTED)
        self.label(self.stats_view, 'Priority: earliest reset among available accounts', 15, bold=True)
        self.policy_control = ctk.CTkSegmentedButton(self.stats_view, values=['Current model', 'Gemini', 'Claude / GPT'], command=self.set_policy_group)
        self.policy_control.set({'gemini': 'Gemini', 'claude': 'Claude / GPT'}.get(self.controller.preferences.get('reset-group'), 'Current model'))
        self.policy_control.pack(anchor='w', pady=(0, 6))
        self.policy_label = self.label(self.stats_view, 'Loading quotas to rank accounts…', 12, MUTED)
        self.stats_latest = self.label(self.stats_view, 'Last successful request: no data yet', 16, bold=True)
        self.stats_note = self.label(self.stats_view, 'Accounts are identified from completed requests. The proxy does not report the account during generation. Different models may use different accounts.', 12, MUTED)
        self.stats_totals = self.label(self.stats_view, '', 13)
        self.stats_accounts = ctk.CTkFrame(self.stats_view, fg_color='transparent')
        self.stats_accounts.pack(fill='x', pady=(0, 12))
        controls = ctk.CTkFrame(self.stats_view, fg_color='transparent')
        controls.pack(fill='x', pady=(8, 6))
        self.label(controls, 'Requests and account switches', 16, bold=True)
        self.journal_filter = ctk.CTkSegmentedButton(controls, values=['All events', 'Switches', 'Errors'], command=lambda _: self.render_activity())
        self.journal_filter.set('All events')
        self.journal_filter.pack(anchor='w', pady=(0, 8))
        self.stats_journal = ctk.CTkTextbox(self.stats_view, height=300, fg_color=CARD, text_color=TEXT, font=('Segoe UI', 12), wrap='word')
        self.stats_journal.pack(fill='x')
        self.stats_observed = self.label(self.stats_view, '', 12, MUTED)
        self.view_switch = ctk.CTkSegmentedButton(self.body, values=['Account and quotas', 'Routing statistics'], command=self.change_view)
        self.view_switch.set('Account and quotas')
        self.view_switch.pack(before=self.detail._parent_frame, anchor='w', pady=(0, 10))
        self.notice = ctk.CTkLabel(self.body, text='Sign-ins are preserved when the application closes.', text_color=MUTED, font=('Segoe UI', 12), wraplength=660, justify='left')
        self.notice.pack(anchor='w', pady=(12, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.consume)
        self.after(120, lambda: self.refresh(prepare=True))
        self.after(60000, self.periodic_quota)
        self.after(15000, self.tick_countdowns)
        self.after(150, self.animate_active_borders)
        if self.controller.preferences.get('details-collapsed'):
            self.restore_details_job = self.after(180, self.toggle_details)

    def toggle_details(self):
        positions = [(canvas, canvas.yview()[0]) for canvas in
                     (self.account_list._parent_canvas, self.detail._parent_canvas)]
        if self.details_collapsed:
            self.body.grid()
            self.grid_columnconfigure(0, weight=0)
            self.grid_columnconfigure(1, weight=1)
            self.minsize(990, 680)
            self.geometry(self.expanded_geometry or '1120x760')
        else:
            self.expanded_geometry = self.geometry()
            if self.state() == 'zoomed':
                self.state('normal')
                self.update_idletasks()
                self.expanded_geometry = self.geometry()
            self.body.grid_remove()
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)
            self.minsize(SIDEBAR_WIDTH, 500)
            self.geometry(f'{SIDEBAR_WIDTH}x{max(500, int(self._current_height))}')
        self.details_collapsed = not self.details_collapsed
        self.controller.preferences['details-collapsed'] = self.details_collapsed
        self.controller.save()
        def restore_positions():
            if not self.closed:
                for canvas, position in positions:
                    canvas.yview_moveto(position)
        self.after_idle(restore_positions)

    def button(self, parent, text, command, primary=False):
        return ctk.CTkButton(parent, text=text, command=command, height=39, corner_radius=9,
            fg_color=ACCENT if primary else '#303b50', hover_color='#87a8ff' if primary else '#3d4b64',
            text_color='#101728' if primary else TEXT, font=('Segoe UI', 13, 'bold'))

    def label(self, parent, text, size=14, color=TEXT, bold=False):
        obj = ctk.CTkLabel(parent, text=text, font=('Segoe UI', size, 'bold' if bold else 'normal'),
            text_color=color, justify='left', anchor='w', wraplength=660)
        obj.pack(fill='x', anchor='w', pady=(0, 8))
        return obj

    def work(self, fn, done, mutation=False):
        if mutation and self.busy:
            return
        if mutation:
            self.busy = True
            self.add_button.configure(state='disabled')
            self.pool_button.configure(state='disabled')
        def run():
            try:
                result = fn()
                self.mailbox.put((done, result, None, mutation))
            except Exception as exc:
                error = str(exc) if isinstance(exc, AccountError) else 'Could not complete this action. Try reloading the list.'
                self.mailbox.put((done, None, error, mutation))
        threading.Thread(target=run, daemon=True).start()

    def consume(self):
        while not self.mailbox.empty():
            done, result, error, mutation = self.mailbox.get()
            if mutation:
                self.busy = False
                self.add_button.configure(state='disabled' if self.pending_login else 'normal')
                self.pool_button.configure(state='normal')
            if error:
                self.notice.configure(text=error, text_color='#ffbd93')
                self.service.configure(text='●  Needs attention', text_color='#ffbd93')
            else:
                done(result)
        if not self.closed:
            self.after(100, self.consume)

    def refresh(self, prepare=False):
        if self.busy:
            return
        for cached in self.quota_cache.values():
            cached['checked'] = 0
        def load():
            if prepare or not self.controller.key:
                self.controller.prepare()
            return self.controller.accounts()
        self.work(load, self.loaded, mutation=True)

    def loaded(self, items):
        if items and (self.controller.data_dir / 'installation.json').exists() and not self.controller.preferences.get('connections-offered'):
            self.controller.preferences['connections-offered'] = True
            self.controller.save()
            self.after(500, self.connection_settings)
        self.items = items
        self.service.configure(text='●  Connected', text_color=GREEN)
        if self.selected not in {a['name'] for a in items}:
            self.selected = items[0]['name'] if items else None
        enabled = [a for a in items if not a['disabled']]
        if not enabled:
            mode = 'No accounts enabled'
        elif len(enabled) == len(items) and self.controller.preferences.get('mode') != 'single':
            mode = f'Automatic routing • enabled accounts: {len(enabled)}'
        elif len(enabled) == 1:
            mode = 'For Claude: ' + self.display_name(enabled[0])
        else:
            mode = f'Enabled accounts: {len(enabled)} of {len(items)}'
        self.mode_label.configure(text=mode)
        self.draw_account_list()
        if self.detail_account != self.selected:
            self.draw_detail()
        else:
            self.update_detail_account()
        for account in items:
            self.fetch_quota(account['name'])
        self.queue_policy()
        if not self.activity_started:
            self.activity_started = True
            self.start_activity()

    def change_view(self, value):
        self.detail.pack_forget()
        self.stats_view.pack_forget()
        view = self.stats_view if value == 'Routing statistics' else self.detail
        view.pack(fill='both', expand=True, before=self.notice)

    def start_activity(self):
        def enable():
            self.controller.request('/usage-statistics-enabled', 'PUT', {'value': True})
        self.work(enable, lambda _: self.poll_activity())

    def poll_activity(self):
        if self.closed:
            return
        if self.activity_busy:
            self.after(5000, self.poll_activity)
            return
        self.activity_busy = True
        def fetch():
            try:
                accounts, records, strategy = self.controller.activity_snapshot()
                return accounts, copy.deepcopy(self.activity.ingest(records, accounts)), strategy, None, self.controller.quota_wait_status()
            except Exception:
                return None, None, None, 'Cannot reach the proxy. Showing cached data.', {'jobs': []}
        def done(result):
            self.activity_busy = False
            accounts, state, strategy, error, quota_wait = result
            if error:
                self.stats_strategy.configure(text=error, text_color='#ffbd93')
            else:
                self.items = accounts
                self.activity_state = state
                self.activity_strategy = strategy
                self.render_activity()
                self.draw_account_list()
                waiting = [job for job in quota_wait.get('jobs', []) if job.get('state') == 'waiting']
                if waiting:
                    self.service.configure(text=self.quota_wait_text(waiting), text_color='#f7ca70')
                else:
                    self.service.configure(text='●  Connected', text_color=GREEN)
                latest = max(state['latest'].values(), key=lambda e: e['at'], default=None)
                if latest:
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest['at'].replace('Z', '+00:00'))).total_seconds()
                    except (ValueError, TypeError):
                        age = 9999
                    if 0 <= age < 120:
                        self.fetch_quota(latest['name'])
                self.queue_policy()
            if not self.closed:
                self.after(5000, self.poll_activity)
        self.work(fetch, done)

    def set_policy_group(self, value):
        self.controller.preferences['reset-group'] = {'Gemini': 'gemini', 'Claude / GPT': 'claude'}.get(value, 'auto')
        self.controller.save()
        self.queue_policy()

    def target_policy_group(self):
        choice = self.controller.preferences.get('reset-group', 'auto')
        if choice in ('gemini', 'claude'):
            return choice
        latest = sorted(self.activity_state['latest'].values(), key=lambda e: e['at'], reverse=True)
        if latest:
            model = latest[0].get('upstream_model') or self.model_aliases.get(latest[0]['model'], latest[0]['model'])
            if model == 'claude-sonnet-4-5' or model.startswith('gemini'):
                return 'gemini'
            if model.startswith(('claude', 'gpt')):
                return 'claude'
        return 'gemini'

    def queue_policy(self):
        if self.closed:
            return
        if self.policy_job:
            self.after_cancel(self.policy_job)
        self.policy_job = self.after(1200, self.apply_policy)

    def apply_policy(self):
        self.policy_job = None
        if self.policy_busy or self.busy or self.quota_pending:
            self.queue_policy()
            return
        if self.controller.preferences.get('mode') == 'single':
            self.policy_label.configure(text='One account is selected manually. Automatic ranking is paused.')
            return
        group = self.target_policy_group()
        rows = rank_accounts(self.items, self.quota_cache, group)
        title = 'Gemini' if group == 'gemini' else 'Claude / GPT'
        if not rows or all(r['tier'] == 2 for r in rows):
            self.policy_label.configure(text=f'Account ranking for {title}: waiting for fresh Google quota data.')
            return
        if self.policy_rows == rows and self.policy_group == group:
            actual = {a['name']: a.get('priority') for a in self.items}
            if all(actual.get(r['name']) == r['priority'] for r in rows):
                return
        self.policy_busy = True
        def apply():
            try:
                return self.controller.apply_reset_priority(rows), None
            except Exception as exc:
                return False, str(exc) if isinstance(exc, AccountError) else 'Could not apply account priorities.'
        def done(result):
            self.policy_busy = False
            applied, error = result
            if error:
                self.policy_label.configure(text=error, text_color='#ffbd93')
                return
            if not applied:
                self.policy_label.configure(text='Enabled accounts changed. Recalculating priorities.')
                self.queue_policy()
                return
            self.policy_rows, self.policy_group = rows, group
            names = {a['name']: self.display_name(a) for a in self.items}
            lines = [f'Account ranking for {title} • recalculated after quota updates.']
            for index, row in enumerate(rows, 1):
                reset = ' • ' + self.activity_time(row['reset']) if row['reset'] else ''
                lines.append(f"{index}. {names.get(row['name'], row['name'])} — {row['reason']}{reset}")
            lines.append('Proxy priorities are calculated for this group. The last ranking remains active after the application closes.')
            self.policy_label.configure(text='\n'.join(lines), text_color=MUTED)
            self.mode_note.configure(text=f'Earliest-reset priority • {title}. Quotas and errors are handled automatically.')
        self.work(apply, done)

    @staticmethod
    def activity_time(value):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().strftime('%d.%m %H:%M:%S')
        except (ValueError, AttributeError):
            return 'Time unknown'

    def render_activity(self):
        state = self.activity_state
        by_name = {a['name']: a for a in self.items}
        def name(key):
            return self.display_name(by_name[key]) if key in by_name else key or 'Unknown account'
        strategy = getattr(self, 'activity_strategy', 'unknown')
        text = ('Earliest-reset priority • ' + ('Gemini' if self.policy_group == 'gemini' else 'Claude / GPT')) if self.policy_rows else 'Fill one account first → switch when unavailable' if strategy == 'fill-first' else 'Round-robin accounts' if strategy == 'round-robin' else 'Strategy: ' + strategy
        enabled = sum(not a['disabled'] for a in self.items)
        self.stats_strategy.configure(text=f'{text} • enabled accounts: {enabled} • updated every 5 seconds', text_color=MUTED)
        latest = sorted(state['latest'].values(), key=lambda e: e['at'], reverse=True)
        if latest:
            last = latest[0]
            self.stats_latest.configure(text='Last successful request: ' + name(last['name']) + '\n' + model_name(last.get('upstream_model') or last['model'], self.model_aliases) + ' • ' + self.activity_time(last['at']))
            self.mode_activity.configure(text='Last response: ' + name(last['name']) + ' • ' + self.activity_time(last['at']))
        stats = state['stats']
        success = sum(v['success'] for v in stats.values())
        failed = sum(v['failed'] for v in stats.values())
        tokens = sum(v['tokens'] for v in stats.values())
        switches = sum(bool(e['switch']) for e in state['events'])
        self.stats_totals.configure(text=f'Since monitoring started: {success} responses • {failed} errors • {switches} switches in the log • {tokens:,} tokens')
        for key in list(self.activity_rows):
            if key not in by_name:
                self.activity_rows.pop(key).destroy()
        for account in self.items:
            key = account['name']
            if key not in self.activity_rows:
                self.activity_rows[key] = self.label(self.stats_accounts, '', 13)
            own = stats.get(key, {})
            count = own.get('success', 0) + own.get('failed', 0)
            average = own.get('latency_ms', 0) / count / 1000 if count else 0
            status = 'Paused' if account['disabled'] else 'Waiting / restricted' if account.get('unavailable') or account.get('cooldowns') else 'Available'
            self.activity_rows[key].configure(text=f"{name(key)} • {status}\nProxy since startup: {account.get('success') or 0} successful / {account.get('failed') or 0} errors\nObserved: {count} attempts • {own.get('tokens', 0):,} tokens • average {average:.1f} s" + (' • last ' + self.activity_time(own['last']) if own.get('last') else ''))
        mode = self.journal_filter.get()
        events = [e for e in state['events'] if mode == 'All events' or (mode == 'Switches' and e['switch']) or (mode == 'Errors' and e['failed'])]
        lines = []
        for e in reversed(events[-100:]):
            title = 'SWITCH' if e['switch'] else 'ERROR' if e['failed'] else 'RESPONSE'
            route = (name(e['from']) + ' → ' if e['from'] else '') + name(e['name'])
            lines.append(f"{self.activity_time(e['at'])} • {title}\n{route} • {model_name(e.get('upstream_model') or e['model'], self.model_aliases)}\n{e['reason']} • {e['latency_ms'] / 1000:.1f} s • {e['tokens']:,} tokens\n")
        content = '\n'.join(lines) or 'No events yet. New requests will appear automatically.'
        if getattr(self, 'journal_content', None) != content:
            scroll = self.stats_journal.yview()[0]
            self.stats_journal.configure(state='normal')
            self.stats_journal.delete('1.0', 'end')
            self.stats_journal.insert('1.0', content)
            self.stats_journal.configure(state='disabled')
            self.stats_journal.yview_moveto(scroll)
            self.journal_content = content
        self.stats_observed.configure(text='Monitoring since ' + self.activity_time(state['since']) + ' (local time). The log persists after closing; monitoring runs while the application is open. The latest 2000 events are kept.')

    def draw_account_list(self):
        self.update_total_quota()
        accounts = sorted(self.items, key=lambda a: (a.get('access_issue') != 'verification',
            0 if a.get('access_issue') == 'verification' else self.account_reset_order(a['name'])))
        names = [a['name'] for a in accounts]
        layout = [(a['name'], a.get('access_issue') == 'verification') for a in accounts]
        pending_count = sum(pending for _, pending in layout)
        if len(names) < 11:
            self.account_list._scrollbar.grid_remove()
        else:
            self.account_list._scrollbar.grid()
        if getattr(self, 'account_layout', None) != layout and dict(getattr(self, 'account_layout', [])) == dict(layout):
            for widget in self.account_list.winfo_children():
                widget.pack_forget()
            for index, account in enumerate(accounts):
                for header_index, widget, options in self.account_group_widgets:
                    if header_index == index:
                        widget.pack(**options)
                self.account_widgets[account['name']]['card'].pack(fill='x', pady=(0, 1), padx=1)
            self.account_widgets = {name: self.account_widgets[name] for name in names}
            self.account_layout = layout
        if getattr(self, 'account_layout', None) == layout:
            for account in accounts:
                self.update_account_row(account)
            return
        position = self.account_list._parent_canvas.yview()[0]
        for widget in self.account_list.winfo_children():
            widget.destroy()
        self.account_widgets = {}
        self.account_group_widgets = []
        self.account_layout = layout
        for index, account in enumerate(accounts):
            if pending_count and index in (0, pending_count):
                pending = index == 0
                if not pending:
                    separator = ctk.CTkFrame(self.account_list, height=1, fg_color='#43516a')
                    options = {'fill': 'x', 'padx': 5, 'pady': (6, 3)}
                    separator.pack(**options)
                    self.account_group_widgets.append((index, separator, options))
                title = f'Verification required · {pending_count}' if pending else f'Ready accounts · {len(accounts) - pending_count}'
                header = ctk.CTkLabel(self.account_list, text=title, height=19, anchor='w',
                    font=('Segoe UI', 11, 'bold'), text_color='#f7ca70' if pending else MUTED)
                options = {'fill': 'x', 'padx': 6, 'pady': (0, 3)}
                header.pack(**options)
                self.account_group_widgets.append((index, header, options))
            name = account['name']
            card = ctk.CTkFrame(self.account_list, fg_color='#202938', corner_radius=10,
                border_width=1, border_color=ACCENT if name == self.selected else '#344155')
            card.pack(fill='x', pady=(0, 1), padx=1)
            status = self.sidebar_account_status(account)
            button = ctk.CTkButton(card, text=self.account_heading(account),
                height=19, anchor='w', corner_radius=6, fg_color='#303e59' if account['name'] == self.selected else CARD,
                hover_color='#334158', text_color=TEXT, font=('Segoe UI', 12, 'bold'), command=lambda a=account: self.select(a))
            button.pack(fill='x', pady=(1, 0), padx=5)
            countdown = {}
            verification_frame = ctk.CTkFrame(card, fg_color='transparent')
            verification_frame.grid_columnconfigure((0, 3), weight=1)
            verify = self.button(verification_frame, 'Verify', lambda n=name: self.open_verification(n))
            refresh_link = self.button(verification_frame, '↻', lambda n=name: self.refresh_verification_link(n))
            refresh_link.configure(height=22, width=24, font=('Segoe UI', 18))
            refresh_link.grid(row=0, column=1, padx=3)
            copy_link = self.button(verification_frame, '⧉', lambda n=name: self.copy_verification_link(n))
            copy_link.configure(height=22, width=24, font=('Segoe UI Symbol', 15))
            copy_link.grid(row=0, column=2, padx=(0, 3))
            retry = self.button(verification_frame, 'I verified', lambda n=name: self.retry_verification(n))
            for column, action in ((0, verify), (3, retry)):
                action.configure(height=22, width=88, font=('Segoe UI', 11))
                action.grid(row=0, column=column, sticky='ew', padx=1)
            if account.get('access_issue') == 'verification':
                verification_frame.pack(fill='x', padx=5, pady=(0, 3))
            quota_frame = ctk.CTkFrame(card, fg_color='transparent')
            quota_frame.pack(fill='x', padx=5, pady=(0, 1))
            widgets = {'card': card, 'button': button, 'quotas': {}, 'quota_frame': quota_frame, 'countdown': countdown, 'verification_frame': verification_frame,
                       'active_families': ()}
            self.account_widgets[account['name']] = widgets
            groups = self.quota_groups(account['name'])
            for group in groups:
                for bucket in sorted(group['buckets'], key=lambda b: b['window'] != '5h'):
                    remaining = bucket.get('remaining')
                    text = self.sidebar_quota_text(group, bucket)
                    header = ctk.CTkFrame(quota_frame, fg_color='transparent')
                    header.pack(fill='x', padx=3, pady=(3 if group['kind'] == 'claude' and bucket['window'] == '5h' else 0, 0))
                    header.grid_columnconfigure(2, weight=1)
                    icon = ctk.CTkLabel(header, text='', image=self.provider_icons[group['kind']] if bucket['window'] == '5h' else None, height=14, width=14)
                    icon.grid(row=0, column=0, padx=(0, 4))
                    label = ctk.CTkLabel(header, text=text, height=14, width=76, font=('Segoe UI', 11), text_color=self.quota_color(remaining), anchor='w')
                    label.grid(row=0, column=1, sticky='w')
                    reset_label = ctk.CTkLabel(header, text='', height=14, width=68, font=('Segoe UI', 12, 'bold'), text_color=TEXT, anchor='e')
                    reset_label.grid(row=0, column=3, sticky='e', padx=(6, 0))
                    countdown[(group['kind'], bucket['window'])] = reset_label
                    bar = ctk.CTkProgressBar(header, width=35, height=5, fg_color='#354157', progress_color=self.quota_color(remaining))
                    bar.grid(row=0, column=2, sticky='ew', padx=(3, 0))
                    bar.set(remaining if remaining is not None else 0)
                    widgets['quotas'][(group['kind'], bucket['window'])] = (label, bar)
            self.update_countdown(name)
        for account_name in self.account_widgets:
            self.update_countdown(account_name)
        self.after_idle(lambda: self.account_list._parent_canvas.yview_moveto(position))

    def account_heading(self, account):
        marker = '!' if account.get('access_issue') else 'Ⅱ' if account.get('disabled') else '●'
        return marker + '  ' + self.display_name(account)

    def account_reset_order(self, name):
        resets = []
        for group in self.quota_groups(name):
            if group.get('kind') != 'gemini':
                continue
            for bucket in group['buckets']:
                if bucket.get('window') != '5h':
                    continue
                try:
                    reset = datetime.fromisoformat(bucket['reset'].replace('Z', '+00:00'))
                    if reset.tzinfo:
                        resets.append(reset.timestamp())
                except (KeyError, ValueError, TypeError, AttributeError):
                    pass
        return min(resets, default=float('inf'))

    @staticmethod
    def make_provider_icons():
        size = 64
        mask = Image.new('L', (size, size))
        ImageDraw.Draw(mask).polygon([(32, 0), (42, 22), (64, 32), (42, 42), (32, 64), (22, 42), (0, 32), (22, 22)], fill=255)
        gemini = Image.new('RGBA', (size, size))
        for y in range(size):
            for x in range(size):
                ratio = (x + y) / (2 * (size - 1))
                gemini.putpixel((x, y), (round(75 + 140 * ratio), round(157 - 54 * ratio), round(255 - 43 * ratio), mask.getpixel((x, y))))
        claude = Image.new('RGBA', (size, size))
        draw = ImageDraw.Draw(claude)
        for ray in range(12):
            angle = ray * math.pi / 6
            draw.line([(32, 32), (32 + 28 * math.cos(angle), 32 + 28 * math.sin(angle))], fill='#d98b6b', width=5)
        draw.ellipse((25, 25, 39, 39), fill='#d98b6b')
        return {kind: ctk.CTkImage(light_image=bitmap, dark_image=bitmap, size=(14, 14))
                for kind, bitmap in [('gemini', gemini), ('claude', claude)]}

    @staticmethod
    def sidebar_quota_text(group, bucket):
        period = '1w' if bucket['window'] == 'weekly' else '5h'
        remaining = bucket.get('remaining')
        return period + ' · ' + App.quota_percent(remaining)

    @staticmethod
    def quota_percent(remaining):
        if remaining is None:
            return '—'
        if 0 < remaining < .001:
            return '<0,1%'
        return f'{remaining * 100:.1f}'.replace('.', ',') + '%'

    def sidebar_account_status(self, account):
        status = 'Paused' if account['disabled'] else ('Waiting / quota' if account['unavailable'] else 'Available')
        last = max(self.activity_state['latest'].values(), key=lambda e: e['at'], default=None)
        if last and last['name'] == account['name'] and not account['disabled']:
            try:
                moment = datetime.fromisoformat(last['at'].replace('Z', '+00:00')).astimezone()
                status = 'Last response ' + moment.strftime('%H:%M:%S')
            except (ValueError, TypeError):
                pass
        if account.get('access_issue') == 'verification':
            status = 'Google verification required'
        elif account.get('access_issue') == 'login':
            status = 'Sign in again'
        elif account.get('access_issue') == 'denied':
            status = 'Google denied access'
        return status + ' · ' + str(account.get('success') or 0) + ' responses'

    def open_verification(self, name):
        account = next((a for a in self.items if a['name'] == name), None)
        if account and account.get('verification_url'):
            webbrowser.open(account['verification_url'])

    def copy_verification_link(self, name):
        account = next((a for a in self.items if a['name'] == name), None)
        if account and account.get('verification_url'):
            self.clipboard_clear()
            self.clipboard_append(account['verification_url'])
            self.notice.configure(text='Verification link copied.', text_color=GREEN)
        else:
            self.notice.configure(text='Refresh the link using ↻ first.', text_color='#f7ca70')

    def retry_verification(self, name):
        account = next((a for a in self.items if a['name'] == name), None)
        if account:
            self.action(lambda: self.controller.retry_verified_account(account), 'Google accepted the check. Account verified; retry your Claude request.')

    def refresh_verification_link(self, name):
        account = next((a for a in self.items if a['name'] == name), None)
        if not account or self.busy:
            return
        def refresh():
            result = self.controller.refresh_verification_url(account)
            return self.controller.accounts(), result
        def done(result):
            accounts, issue = result
            self.loaded(accounts)
            if issue.get('verification_url'):
                webbrowser.open(issue['verification_url'])
                self.notice.configure(text='A fresh verification link opened in your browser.', text_color=GREEN)
            else:
                self.notice.configure(text='Google accepted the check. Verification is no longer required.', text_color=GREEN)
        self.work(refresh, done, mutation=True)

    def quota_groups(self, name):
        data = self.quota_cache.get(name, {}).get('data', {})
        groups = {g['kind']: g for g in data.get('groups', [])}
        result = []
        for kind, title, model in [('gemini', 'Gemini', 'claude-sonnet-4-5'), ('claude', 'Claude / GPT', 'claude-sonnet-4-6')]:
            group = groups.get(kind, {})
            buckets = {b['window']: b for b in group.get('buckets', [])}
            result.append({'kind': kind, 'name': group.get('name', title), 'buckets': [
                buckets.get('5h', {'window': '5h', **data.get('models', {}).get(model, {})}),
                buckets.get('weekly', {'window': 'weekly'})]})
        return result

    def update_total_quota(self):
        accounts = [a for a in self.items if not a.get('disabled')]
        values = []
        weekly_values = []
        weekly_entries = []
        entries = []
        for account in accounts:
            cached = self.quota_cache.get(account['name'], {})
            if cached.get('error') or cached.get('data', {}).get('summary_error'):
                continue
            for group in self.quota_groups(account['name']):
                if group['kind'] == 'gemini':
                    weekly = next(b for b in group['buckets'] if b['window'] == 'weekly')
                    weekly_value = weekly.get('remaining')
                    if isinstance(weekly_value, (int, float)) and not isinstance(weekly_value, bool) and 0 <= weekly_value <= 1:
                        weekly_values.append(weekly_value)
                        weekly_entries.append({'remaining': weekly_value, 'reset': weekly.get('reset'), 'weekly_remaining': 1})
                    bucket = next(b for b in group['buckets'] if b['window'] == '5h')
                    value = bucket.get('remaining')
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
                        values.append(value)
                        entries.append({'remaining': value, 'reset': bucket.get('reset'),
                            'weekly_remaining': weekly.get('remaining'), 'weekly_reset': weekly.get('reset')})
        # Equal account shares: 100% means every included account is full.
        weekly_remaining = sum(weekly_values) / len(weekly_values) if weekly_values else None
        weekly_title = 'Gemini · 1w · pooled remaining'
        if len(weekly_values) != len(accounts):
            weekly_title = f'Gemini · 1w · data {len(weekly_values)}/{len(accounts)} accounts'
        weekly_color = self.quota_color(weekly_remaining)
        self.total_weekly_title.configure(text=weekly_title)
        self.total_weekly_value.configure(text=self.quota_percent(weekly_remaining), text_color=weekly_color)
        self.total_weekly_bar.configure(progress_color=weekly_color)
        self.total_weekly_bar.set(weekly_remaining if weekly_remaining is not None else 0)
        self.total_weekly_remaining = weekly_remaining
        self.total_weekly_forecast = quota_projection(weekly_entries, exhausted_only=False)
        if self.total_weekly_forecast:
            self.total_weekly_bar.pack_forget()
            if not self.weekly_forecast_canvas.winfo_manager():
                self.weekly_forecast_canvas.pack(fill='x', pady=(1, 0))
            self.draw_total_forecast(weekly=True)
        else:
            self.weekly_forecast_canvas.pack_forget()
            if not self.total_weekly_bar.winfo_manager():
                self.total_weekly_bar.pack(fill='x', pady=(1, 0))
        remaining = sum(values) / len(values) if values else None
        title = 'Gemini · 5h · pooled remaining'
        if len(values) != len(accounts):
            title = f'Gemini · 5h · data {len(values)}/{len(accounts)} accounts'
        color = self.quota_color(remaining)
        self.total_quota_title.configure(text=title)
        self.total_quota_value.configure(text=self.quota_percent(remaining), text_color=color)
        self.total_quota_bar.configure(progress_color=color)
        self.total_quota_bar.set(remaining if remaining is not None else 0)
        self.total_remaining = remaining
        self.total_forecast = quota_projection(entries)
        if self.total_forecast:
            self.total_quota_bar.pack_forget()
            if not self.forecast_canvas.winfo_manager():
                self.forecast_canvas.pack(fill='x', pady=(1, 0))
            self.draw_total_forecast()
        else:
            self.forecast_canvas.pack_forget()
            if not self.total_quota_bar.winfo_manager():
                self.total_quota_bar.pack(fill='x', pady=(1, 0))

    def schedule_total_forecast(self, weekly=False):
        job_attr = 'weekly_forecast_resize_job' if weekly else 'forecast_resize_job'
        if getattr(self, job_attr, None):
            self.after_cancel(getattr(self, job_attr))
        def draw():
            setattr(self, job_attr, None)
            if not self.closed:
                self.draw_total_forecast(weekly=weekly)
        setattr(self, job_attr, self.after(75, draw))

    def draw_total_forecast(self, weekly=False):
        canvas = self.weekly_forecast_canvas if weekly else self.forecast_canvas
        forecast = self.total_weekly_forecast if weekly else self.total_forecast
        total_remaining = self.total_weekly_remaining if weekly else self.total_remaining
        key_attr = 'weekly_forecast_render_key' if weekly else 'forecast_render_key'
        labels_attr = 'weekly_forecast_hover_labels' if weekly else 'forecast_hover_labels'
        if not forecast:
            canvas.delete('all')
            setattr(self, key_attr, None)
            setattr(self, labels_attr, [])
            return
        scale = self.sidebar._get_widget_scaling()
        width = max(1, canvas.winfo_width())
        now = datetime.now(timezone.utc)
        key = (width, scale, total_remaining,
            tuple((point['reset'], point['remaining'], math.ceil((datetime.fromisoformat(point['reset']) - now).total_seconds() / 60))
                  for point in forecast))
        if getattr(self, key_attr, None) == key:
            return
        setattr(self, key_attr, key)
        canvas.delete('all')
        margin = 3 * scale
        track = max(1, width - 2 * margin)
        color = '#8995a8'
        top = 2 * scale
        labels = []
        for point in forecast:
            reset = datetime.fromisoformat(point['reset'])
            minutes = max(0, math.ceil((reset - now).total_seconds() / 60))
            hours, minutes = divmod(minutes, 60)
            text = App.time_until_reset(point['reset'], now, days_only=True) if weekly else f'{hours}h {minutes:02}m'
            text_width = self.forecast_font.measure(text)
            x = margin + track * min(1, max(0, point['remaining']))
            left = x - text_width - 3 * scale
            if left < margin:
                left = x + 3 * scale
            left = max(margin, min(left, width - margin - text_width))
            y = scale
            labels.append((x, left, y, text, text_width))
        height = round(14 * scale)
        canvas.configure(height=height)
        setattr(self, labels_attr, labels)
        # Fill and forecast markers share the pooled quota percentage axis.
        canvas.create_rectangle(margin, top, width - margin, height - top, fill='#293344', outline='')
        remaining = min(1, max(0, total_remaining or 0))
        if remaining > 0:
            canvas.create_rectangle(margin, top, margin + track * remaining, height - top,
                fill=self.quota_color(total_remaining), outline='', tags='quota_remaining')
        label_end = -1
        for x, left, y, text, text_width in labels:
            if left < label_end + 3 * scale:
                continue
            canvas.create_rectangle(left - scale, y, left + text_width + scale, y + self.forecast_font.metrics('linespace'), fill='#293344', outline='')
            canvas.create_text(left, y, text=text, font=self.forecast_font, fill=color, anchor='nw', tags='forecast_label')
            label_end = left + text_width
        for x, left, y, text, text_width in labels:
            canvas.create_rectangle(x - scale, top, x + scale, height - top,
                fill=color, outline='', tags='forecast_time')

    def hover_forecast(self, event, weekly=False):
        canvas = self.weekly_forecast_canvas if weekly else self.forecast_canvas
        canvas.delete('forecast_hover')
        labels = getattr(self, 'weekly_forecast_hover_labels' if weekly else 'forecast_hover_labels', [])
        if not labels:
            return
        scale = self.sidebar._get_widget_scaling()
        x, left, y, text, text_width = min(labels, key=lambda label: abs(label[0] - event.x))
        if abs(x - event.x) <= 8 * scale:
            canvas.create_rectangle(left - scale, y, left + text_width + scale,
                y + self.forecast_font.metrics('linespace'), fill='#293344', outline='', tags='forecast_hover')
            canvas.create_text(left, y, text=text, font=self.forecast_font,
                fill=TEXT, anchor='nw', tags='forecast_hover')

    def update_account_row(self, account):
        widgets = self.account_widgets.get(account['name'])
        if not widgets:
            return
        status = self.sidebar_account_status(account)
        widgets['card'].configure(border_width=1,
            border_color=ACCENT if account['name'] == self.selected else '#344155')
        widgets['button'].configure(text=self.account_heading(account),
            fg_color='#303e59' if account['name'] == self.selected else CARD)
        if account.get('access_issue') == 'verification':
            if not widgets['verification_frame'].winfo_manager():
                widgets['verification_frame'].pack(fill='x', padx=5, pady=(0, 3), after=widgets['button'])
        else:
            widgets['verification_frame'].pack_forget()
        for group in self.quota_groups(account['name']):
            for bucket in group['buckets']:
                label, bar = widgets['quotas'][(group['kind'], bucket['window'])]
                remaining = bucket.get('remaining')
                label.configure(text=self.sidebar_quota_text(group, bucket), text_color=self.quota_color(remaining))
                bar.configure(progress_color=self.quota_color(remaining))
                bar.set(remaining if remaining is not None else 0)
        self.update_countdown(account['name'])

    @staticmethod
    def time_until_reset(value, now=None, days_only=False):
        try:
            reset = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if not reset.tzinfo:
                return '—'
            seconds = (reset - (now or datetime.now(timezone.utc))).total_seconds()
        except (ValueError, AttributeError):
            return '—'
        if days_only:
            return '0d' if seconds <= 0 else '< 1d' if seconds < 86400 else f'{int(seconds // 86400)}d'
        if seconds <= 0:
            return '0m'
        if seconds < 60:
            return '< 1m'
        minutes = int(seconds // 60)
        days, minutes = divmod(minutes, 1440)
        hours, minutes = divmod(minutes, 60)
        if days:
            return f'{days}d {hours}h'
        if hours:
            return f'{hours}h {minutes}m'
        return f'{minutes}m'

    def update_countdown(self, name):
        widgets = self.account_widgets.get(name)
        if not widgets:
            return
        now = datetime.now(timezone.utc)
        # Fixed scales keep long waits red even when they are the earliest in the pool.
        bounds = {'5h': (0, 5 * 3600), 'weekly': (0, 7 * 86400)}
        for group in self.quota_groups(name):
            for bucket in group['buckets']:
                label = widgets['countdown'][(group['kind'], bucket['window'])]
                duration = self.time_until_reset(bucket.get('reset'), now, days_only=bucket['window'] == 'weekly')
                text = duration
                color = self.reset_color(bucket.get('reset'), now, bounds[bucket['window']])
                if label.cget('text') != text or label.cget('text_color') != color:
                    label.configure(text=text, text_color=color)

    @staticmethod
    def reset_color(value, now=None, bounds=None):
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
            seconds = (moment - (now or datetime.now(timezone.utc))).total_seconds()
        except (ValueError, TypeError, AttributeError):
            return MUTED
        if seconds <= 0:
            return '#66e2a7'
        minimum, maximum = bounds or (0, 7 * 86400)
        ratio = min(1, max(0, (seconds - minimum) / (maximum - minimum))) if maximum > minimum else .5
        start, end, fraction = ((102, 226, 167), (245, 197, 107), ratio * 2) if ratio <= .5 else ((245, 197, 107), (255, 68, 85), (ratio - .5) * 2)
        return '#' + ''.join(f'{round(a + (b - a) * fraction):02x}' for a, b in zip(start, end))

    def tick_countdowns(self):
        for name in self.account_widgets:
            self.update_countdown(name)
        self.update_total_quota()
        if not self.closed:
            self.after(15000, self.tick_countdowns)

    @staticmethod
    def model_family(model):
        # These Claude-compatible aliases actually route to Gemini subscriptions.
        if model == 'claude-sonnet-4-5' or model.startswith('gemini'):
            return 'gemini'
        if model.startswith(('claude', 'gpt', 'o1', 'o3', 'o4')):
            return 'claude'
        return None

    @staticmethod
    def quota_wait_text(waiting, now=None):
        now = time.time() if now is None else now
        resets = {}
        for job in waiting:
            family = App.model_family(job.get('upstream_model') or job.get('model', ''))
            if family:
                resets[family] = min(resets.get(family, float('inf')), job['retry_at'])
        labels = []
        for family, title in (('claude', 'Claude'), ('gemini', 'Gemini')):
            if family in resets:
                minutes = math.ceil(max(0, resets[family] - now) / 60)
                duration = f'{minutes // 60}h {minutes % 60:02}m' if minutes >= 60 else f'{minutes}m'
                labels.append(f'until {title} · {duration}')
        return '  /  '.join(labels) or 'Waiting'

    def active_provider_accounts(self):
        enabled = {a['name'] for a in self.items if not a.get('disabled')}
        latest = {}
        for model, event in self.activity_state['latest'].items():
            actual = event.get('upstream_model') or getattr(self, 'model_aliases', {}).get(event.get('model') or model, event.get('model') or model)
            family = self.model_family(actual)
            if family and not event.get('failed') and (family not in latest or event['at'] > latest[family]['at']):
                latest[family] = event
        return {family: event['name'] for family, event in latest.items() if event['name'] in enabled}

    def active_account_names(self):
        return set(self.active_provider_accounts().values())

    def last_account_model(self, name):
        model = self.activity_state.get('stats', {}).get(name, {}).get('last_model')
        if not model:
            candidates = [e for e in self.activity_state.get('events', []) if e.get('name') == name]
            candidates += [e for e in self.activity_state.get('latest', {}).values() if e.get('name') == name]
            last = max(candidates, key=lambda e: e.get('at', ''), default={})
            model = last.get('upstream_model') or last.get('model')
        if not model:
            return ''
        return model_name(model, getattr(self, 'model_aliases', None))

    def draw_active_badges(self, widgets, families, model=''):
        button = widgets['button']
        canvas = button._canvas
        scale = button._get_widget_scaling()
        heading = button.cget('text')
        layout = (families, model, heading, button.winfo_width(), button.winfo_height(), scale)
        if widgets.get('badge_layout') != layout:
            canvas.delete('active_badge')
            images = widgets.setdefault('badge_images', {})
            for index, family in enumerate(reversed(families)):
                size = max(1, round(14 * scale))
                key = (family, size)
                if key not in images:
                    images[key] = ImageTk.PhotoImage(self.provider_icons[family]._dark_image.resize((size, size)), master=self)
                x = button.winfo_width() - (12 + 22 * index) * scale
                y = button.winfo_height() / 2
                canvas.create_rectangle(x - 10 * scale, y - 9 * scale, x + 10 * scale, y + 9 * scale,
                    fill='#334d77' if family == 'gemini' else '#654332', outline='', tags='active_badge')
                canvas.create_image(x, y, image=images[key], tags=('active_badge', 'active_' + family))
            widgets['badge_layout'] = layout
            widgets['active_families'] = families
            canvas.delete('last_model')
            if model:
                font = tkfont.Font(family='Segoe UI', size=-round(9 * scale), weight='bold')
                widgets['last_model_font'] = font
                right = button.winfo_width() - (5 + 22 * len(families)) * scale
                left = right - font.measure(model)
                canvas.create_rectangle(left - 4 * scale, 0, right + 2 * scale, button.winfo_height(),
                    fill=button.cget('fg_color'), outline='', tags='last_model')
                canvas.create_text(right, button.winfo_height() / 2, text=model, anchor='e', font=font,
                    fill='#bac9df', tags='last_model')
                text_font = tkfont.Font(font=button._text_label.cget('font'))
                fitted = heading
                while fitted and text_font.measure(fitted) > left - 14 * scale:
                    fitted = fitted[:-1]
                if fitted != heading and len(fitted) > 2:
                    fitted = fitted[:-2] + '…'
                widgets['fitted_heading'] = fitted
            else:
                widgets['fitted_heading'] = heading
        if button._text_label.cget('text') != widgets.get('fitted_heading', heading):
            button._text_label.configure(text=widgets.get('fitted_heading', heading))
        canvas.tag_raise('active_badge')
        canvas.tag_raise('last_model')

    def draw_rainbow_border(self, widgets, phase):
        card = widgets['card']
        canvas = card._canvas
        size = (card.winfo_width(), card.winfo_height())
        scale = card._get_widget_scaling()
        if size != widgets.get('rainbow_size'):
            canvas.delete('rainbow')
            inset = 1.5 * scale
            x0, y0, x1, y1 = inset, inset, size[0] - inset, size[1] - inset
            radius = 8.5 * scale
            points = []
            for cx, cy, start in [(x0 + radius, y0 + radius, 180), (x1 - radius, y0 + radius, 270),
                                  (x1 - radius, y1 - radius, 0), (x0 + radius, y1 - radius, 90)]:
                for step in range(13):
                    angle = math.radians(start + step * 7.5)
                    points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
            points.append(points[0])
            # Split straight edges too, so every side carries a flowing gradient.
            segments = []
            distance = 0
            for a, b in zip(points, points[1:]):
                length = math.dist(a, b)
                count = max(1, math.ceil(length / (7 * scale)))
                for part in range(count):
                    p = tuple(a[i] + (b[i] - a[i]) * part / count for i in (0, 1))
                    q = tuple(a[i] + (b[i] - a[i]) * (part + 1) / count for i in (0, 1))
                    item = canvas.create_line(*p, *q, width=2.5 * scale, capstyle='round', tags='rainbow')
                    segments.append((item, distance))
                    distance += length / count
            widgets['rainbow_segments'] = [(item, offset / distance) for item, offset in segments]
            widgets['rainbow_size'] = size
        for item, offset in widgets['rainbow_segments']:
            rgb = colorsys.hsv_to_rgb((phase + offset) % 1, .72, 1)
            canvas.itemconfigure(item, fill='#' + ''.join(f'{round(value * 255):02x}' for value in rgb))
        canvas.tag_raise('rainbow')

    def animate_active_borders(self):
        if self.closed:
            return
        providers = self.active_provider_accounts()
        active = set(providers.values())
        for name, widgets in self.account_widgets.items():
            card = widgets['card']
            families = tuple(kind for kind in ('gemini', 'claude') if providers.get(kind) == name)
            self.draw_active_badges(widgets, families, self.last_account_model(name))
            if name in active:
                self.draw_rainbow_border(widgets, (time.monotonic() / 8) % 1)
            elif widgets.pop('rainbow_size', None):
                card._canvas.delete('rainbow')
                widgets.pop('rainbow_segments', None)
        self.after(100, self.animate_active_borders)

    def display_name(self, account):
        return self.controller.preferences.get('labels', {}).get(account['name']) or account.get('email') or 'Google account'

    def select(self, account):
        self.selected = account['name']
        self.loaded(self.items)

    def draw_detail(self):
        position = self.detail._parent_canvas.yview()[0]
        for widget in self.detail.winfo_children():
            widget.destroy()
        self.detail_account = self.selected
        self.detail_quota_widgets = {}
        self.model_widgets = {}
        self.drawn_models = None
        account = next((a for a in self.items if a['name'] == self.selected), None)
        if not account:
            self.label(self.detail, 'Add your first account', 22, bold=True)
            self.label(self.detail, 'Click Add Google account and complete browser sign-in. Your saved account and available models will appear here.', color=MUTED)
            return
        self.detail_heading = self.label(self.detail, self.display_name(account), 22, bold=True)
        if self.display_name(account) != account.get('email') and account.get('email'):
            self.label(self.detail, account['email'], color=MUTED)
        status = 'Sign-in saved • account paused' if account['disabled'] else 'Sign-in saved • enabled for requests'
        self.detail_status = self.label(self.detail, status, color=MUTED)
        self.label(self.detail, 'Remaining quota', 17, bold=True)
        cached = self.quota_cache.get(account['name'])
        self.quota_updated = self.label(self.detail, 'Loading Google quotas…', 12, MUTED)
        self.quota_updated.configure(wraplength=0)
        data = (cached or {}).get('data', {})
        for group in self.quota_groups(account['name']):
            self.label(self.detail, group['name'], 15, bold=True)
            for bucket in sorted(group['buckets'], key=lambda b: b['window'] != '5h'):
                self.detail_quota_widgets[(group['kind'], bucket['window'])] = self.quota_row('Weekly quota' if bucket['window'] == 'weekly' else '5-hour quota', bucket)
        self.label(self.detail, 'Bars show remaining quota: full = 100%. Missing percentages are shown as No data.', 12, MUTED)
        actions = ctk.CTkFrame(self.detail, fg_color='transparent')
        actions.pack(fill='x', pady=(8, 16))
        self.button(actions, 'Use only this account', lambda: self.action(lambda: self.controller.route(account['name']), 'Account selected for Claude.'), primary=True).pack(side='left', padx=(0, 10))
        self.pause_button = self.button(actions, 'Resume' if account['disabled'] else 'Pause', self.pause_selected)
        self.pause_button.pack(side='left')
        rename_frame = ctk.CTkFrame(self.detail, fg_color='transparent')
        rename_frame.pack(fill='x', pady=(0, 20))
        entry = ctk.CTkEntry(rename_frame, placeholder_text='Account label, e.g. Personal', height=36, fg_color=CARD, border_color='#3a465c')
        entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
        entry.insert(0, self.controller.preferences.get('labels', {}).get(account['name'], ''))
        self.rename_entry = entry
        self.button(rename_frame, 'Save label', lambda: self.rename(account, entry.get())).pack(side='left')
        self.unavailable_label = self.label(self.detail, '', color='#ffbd93')
        self.label(self.detail, 'Pausing preserves the sign-in. Switching applies to future requests; an ongoing response may finish on the previous account.', 12, MUTED)
        self.update_detail_account()
        self.after_idle(lambda: self.detail._parent_canvas.yview_moveto(position))

    def quota_row(self, model, quota, parent=None):
        row = ctk.CTkFrame(parent if parent is not None else self.detail, fg_color=CARD, corner_radius=9)
        row.pack(fill='x', pady=5)
        header = ctk.CTkFrame(row, fg_color='transparent')
        header.pack(fill='x', padx=14, pady=(10, 5))
        remaining = (quota or {}).get('remaining')
        color = self.quota_color(remaining)
        ctk.CTkLabel(header, text=MODEL_LABELS.get(model, model), text_color=TEXT, font=('Segoe UI', 13), anchor='w').pack(side='left')
        value = ctk.CTkLabel(header, text='', text_color=color, font=('Segoe UI', 12, 'bold'))
        value.pack(side='right')
        bar = ctk.CTkProgressBar(row, height=9, fg_color='#354157', progress_color=color)
        bar.pack(fill='x', padx=14, pady=(0, 7))
        bar.set(remaining if remaining is not None else 0)
        reset_label = ctk.CTkLabel(row, text='', text_color=MUTED, font=('Segoe UI', 11), anchor='w')
        reset_label.pack(fill='x', padx=14, pady=(0, 8))
        widgets = (value, bar, reset_label)
        self.update_quota_row(widgets, quota)
        return widgets

    def update_quota_row(self, widgets, quota):
        value, bar, reset_label = widgets
        remaining = (quota or {}).get('remaining')
        color = self.quota_color(remaining)
        value.configure(text='No data' if remaining is None else self.quota_percent(remaining) + ' remaining', text_color=color)
        bar.configure(progress_color=color)
        bar.set(remaining if remaining is not None else 0)
        reset = (quota or {}).get('reset')
        label = 'Reset time not provided'
        if reset:
            try:
                date = datetime.fromisoformat(reset.replace('Z', '+00:00')).astimezone()
                label = 'Resets: ' + date.strftime('%b %d at %H:%M') + ' (local time)'
            except (ValueError, KeyError):
                label = 'Reset time not provided'
        reset_label.configure(text=label)

    def update_model_rows(self):
        # Quotas are shown only as four grouped windows.
        pass

    def update_detail_account(self):
        account = next((a for a in self.items if a['name'] == self.selected), None)
        if not account or self.detail_account != self.selected:
            return
        self.detail_heading.configure(text=self.display_name(account))
        self.detail_status.configure(text='Sign-in saved • account paused' if account['disabled'] else 'Sign-in saved • enabled for requests')
        self.pause_button.configure(text='Resume' if account['disabled'] else 'Pause')
        self.unavailable_label.configure(text='The service reported temporary unavailability. Your sign-in is saved; you can select another account.' if account.get('unavailable') else '')
        self.update_detail_quota()

    def pause_selected(self):
        account = next((a for a in self.items if a['name'] == self.selected), None)
        if account:
            self.action(lambda: self.controller.pause(account), 'Account status updated.')

    def update_detail_quota(self):
        cached = self.quota_cache.get(self.selected, {})
        self.quota_updated.configure(text=(('Updated ' + cached['at'].strftime('%H:%M:%S') if cached.get('at') else 'Quota data not received yet') + ' • automatically every minute') if cached else 'Loading Google quotas…')
        data = cached.get('data', {})
        # Keep errors in the status line so refreshing cannot change the layout.
        error = cached.get('error') or data.get('summary_error')
        if error:
            text = error + (' Showing the latest cached data.' if cached.get('at') else '')
            self.quota_updated.configure(text=text[:92] + ('…' if len(text) > 92 else ''), text_color='#ffbd93')
        else:
            self.quota_updated.configure(text_color=MUTED)
        for group in self.quota_groups(self.selected):
            for bucket in group['buckets']:
                self.update_quota_row(self.detail_quota_widgets[(group['kind'], bucket['window'])], bucket)
        for model, widgets in self.model_widgets.items():
            self.update_quota_row(widgets, data.get('models', {}).get(model))

    @staticmethod
    def quota_color(remaining):
        return MUTED if remaining is None else (GREEN if remaining > .3 else '#f5c56b' if remaining > .1 else '#ff8d8d')

    def fetch_quota(self, name):
        if name in self.quota_pending:
            return
        cached = self.quota_cache.get(name)
        if cached and time.monotonic() - cached.get('checked', 0) < 30:
            return
        account = next((a for a in self.items if a['name'] == name), None)
        if not account:
            return
        self.quota_pending.add(name)
        def fetch():
            try:
                data = self.controller.quotas(account)
                last_used = {}
                for model, event in self.activity_state['latest'].items():
                    actual = event.get('upstream_model') or self.model_aliases.get(event.get('model') or model, event.get('model') or model)
                    family = self.model_family(actual)
                    if family and event['name'] == name:
                        try:
                            at = datetime.fromisoformat(event['at'].replace('Z', '+00:00')).timestamp()
                            last_used[family] = max(last_used.get(family, 0), at)
                        except (ValueError, TypeError):
                            pass
                started = self.controller.start_full_quota_windows(account, data, last_used=last_used)
                if any(result['status'] == 200 for result in started):
                    try:
                        data = self.controller.quotas(account)
                    except AccountError:
                        pass
                return data, None
            except AccountError as exc:
                return None, str(exc)
            except Exception:
                return None, 'Could not load quotas. Try again later.'
        def done(result):
            self.quota_pending.discard(name)
            data, error = result
            old = self.quota_cache.get(name, {})
            if data is not None and data.get('summary_error') and old.get('data', {}).get('groups'):
                data['groups'] = old['data']['groups']
                data['summary_error'] += ' Showing the latest cached weekly data from ' + old['at'].strftime('%H:%M:%S') + '.'
            self.quota_cache[name] = {'data': data if data is not None else old.get('data', {}),
                'at': datetime.now().astimezone() if data is not None else old.get('at'),
                'checked': time.monotonic(), 'error': error}
            account = next((a for a in self.items if a['name'] == name), None)
            if account:
                self.draw_account_list()
            for account_name in self.account_widgets:
                self.update_countdown(account_name)
            self.update_total_quota()
            if self.selected == name:
                self.update_detail_quota()
            self.queue_policy()
        self.work(fetch, done)

    def periodic_quota(self):
        if not self.busy:
            for account in self.items:
                self.fetch_quota(account['name'])
        if not self.closed:
            self.after(60000, self.periodic_quota)

    def fetch_models(self, name):
        account = next((a for a in self.items if a['name'] == name), None)
        if not account:
            return
        def done(models):
            self.model_cache[name] = models
            if self.selected == name:
                self.update_model_rows()
        self.work(lambda: self.controller.models(account), done)

    def action(self, fn, message):
        if self.busy:
            return
        def perform():
            fn()
            return self.controller.accounts()
        def done(items):
            self.notice.configure(text=message, text_color=GREEN)
            self.loaded(items)
        self.work(perform, done, mutation=True)

    def model_settings(self):
        if hasattr(self, 'model_window') and self.model_window.winfo_exists():
            self.model_window.lift()
            return
        window = self.model_window = ctk.CTkToplevel(self)
        window.title('Model selection')
        window.geometry('550x395')
        window.configure(fg_color=PANEL)
        window.transient(self)
        self.label(window, 'Choose models', 23, bold=True).pack_configure(padx=24, pady=(20, 8))
        self.label(window, 'Choose Claude and Gemini models independently.\nNew requests use your choice. Ongoing responses keep their model.', 12, MUTED).pack_configure(padx=24, pady=(0, 15))
        controls = ctk.CTkFrame(window, fg_color='transparent')
        controls.pack(fill='x', padx=24)
        controls.grid_columnconfigure(1, weight=1)
        selectors = {}
        options = {}
        current = self.controller.selected_family_models()
        for row, group in enumerate(('claude', 'gemini')):
            ctk.CTkLabel(controls, text='Claude (Antigravity)' if group == 'claude' else 'Gemini', text_color=TEXT, width=145, anchor='w').grid(row=row, column=0, pady=7)
            selector = ctk.CTkOptionMenu(controls, values=['Loading…'], state='disabled', fg_color=CARD)
            selector.grid(row=row, column=1, sticky='ew', pady=7)
            selectors[group] = selector
        codex_path = self.integrations.paths()['codex'][0]
        try:
            managed_codex = '# BEGIN Gemini Accounts managed provider' in codex_path.read_text('utf-8-sig')
        except OSError:
            managed_codex = False
        backups = self.integrations.backups()
        managed_clients = [client for client, paths in self.integrations.paths().items()
                           if any(str(path.resolve()) in backups for path in paths)]
        if managed_codex and 'codex' not in managed_clients:
            managed_clients.append('codex')
        update_codex = ctk.BooleanVar(value=bool(managed_clients))
        ctk.CTkCheckBox(window, text='Update connected client model menus (asks permission)',
            variable=update_codex, state='normal' if managed_clients else 'disabled').pack(anchor='w', padx=24, pady=(16, 10))
        status = ctk.CTkLabel(window, text='Loading the account model catalog…', text_color=MUTED, wraplength=500, justify='left')
        status.pack(anchor='w', padx=24, pady=(0, 10))

        def apply():
            selected = {group: options[group][selector.get()] for group, selector in selectors.items()}
            if update_codex.get():
                paths = '\n'.join(str(p) for client in managed_clients for p in self.integrations.paths()[client])
                if not messagebox.askyesno('Update connected client configurations?',
                    'Model choices will change, and these client files will be configured:\n\n' + paths +
                    '\n\nThe default model and connection settings will change. Original files are backed up. '
                    'Restart clients to apply their updated menus and defaults. Allow these changes?', parent=window):
                    return
            apply_button.configure(state='disabled')
            update_client = bool(update_codex.get())
            def change():
                changed = False
                try:
                    previous_entries = self.controller.request('/oauth-model-alias').get('oauth-model-alias', {}).get('antigravity', [])
                    previous_preferences = copy.deepcopy(self.controller.preferences)
                    aliases = self.controller.set_family_models(selected['gemini'], selected['claude'])
                    changed = True
                    if update_client:
                        self.integrations.apply(managed_clients)
                    return aliases, None
                except Exception as error:
                    if changed:
                        try:
                            self.controller.request('/oauth-model-alias', 'PATCH', {'provider': 'antigravity', 'aliases': previous_entries})
                            self.controller.preferences = previous_preferences
                            self.controller.save()
                        except Exception:
                            return None, 'Client setup failed and model rollback failed. Reopen model selection and check the gateway.'
                    return None, str(error)
            def done(result):
                aliases, error = result
                if not window.winfo_exists():
                    return
                apply_button.configure(state='normal')
                if error:
                    status.configure(text=error, text_color='#ffbd93')
                    return
                self.model_aliases = aliases
                self.activity = Activity(self.controller.data_dir / 'activity.json')
                self.activity_state = copy.deepcopy(self.activity.state)
                status.configure(text='Applied to new gateway requests.' + (' Restart clients for updated menus and defaults.' if update_client else ''), text_color=GREEN)
                self.render_activity()
            self.work(change, done)

        apply_button = self.button(window, 'Apply models', apply, primary=True)
        apply_button.configure(state='disabled')
        apply_button.pack(fill='x', padx=24)
        def load():
            try:
                return self.controller.family_model_choices(), None
            except Exception as error:
                return None, str(error)
        def loaded(result):
            if not window.winfo_exists():
                return
            choices, error = result
            if error:
                status.configure(text=error, text_color='#ffbd93')
                return
            if not choices['claude'] or not choices['gemini']:
                status.configure(text='The account catalog must include both Claude and Gemini models.', text_color='#ffbd93')
                return
            for group in ('claude', 'gemini'):
                options[group] = {}
                for model in choices[group]:
                    label = model_name(model, {})
                    if label in options[group]:
                        label += ' (' + model + ')'
                    options[group][label] = model
                selectors[group].configure(values=list(options[group]), state='normal')
                selected_label = next((label for label, model in options[group].items() if model == current.get(group)), next(iter(options[group])))
                selectors[group].set(selected_label)
            apply_button.configure(state='normal')
            status.configure(text='Claude uses the Antigravity Claude quota. Gemini uses the Gemini quota.', text_color=MUTED)
        self.work(load, loaded)

    def connection_settings(self):
        if hasattr(self, 'connection_window') and self.connection_window.winfo_exists():
            self.connection_window.lift()
            return
        window = self.connection_window = ctk.CTkToplevel(self)
        window.title('Application connections')
        window.geometry('620x480')
        window.configure(fg_color=PANEL)
        window.transient(self)
        ctk.CTkLabel(window, text='Set up connections', font=('Segoe UI', 23, 'bold'), text_color=TEXT).pack(anchor='w', padx=24, pady=(22, 12))
        ctk.CTkLabel(window, text='Choose applications. We will configure the local connection\nand back up your original configurations for restoration.', justify='left', text_color=MUTED).pack(anchor='w', padx=24)
        detected = self.integrations.detected()
        choices = {}
        for client, title in [('claude_desktop', 'Claude Desktop · Code tab'), ('codex', 'Codex Desktop and CLI'), ('claude_cli', 'Claude Code CLI')]:
            value = ctk.BooleanVar(value=detected[client])
            choices[client] = value
            ctk.CTkCheckBox(window, text=title + ('' if detected[client] else ' · not detected'), variable=value).pack(anchor='w', padx=26, pady=12)
        status = ctk.CTkLabel(window, text='Client sessions, projects and sign-ins are preserved.', text_color=MUTED, wraplength=560, justify='left')
        status.pack(anchor='w', padx=24, pady=8)
        def apply():
            clients = [name for name, value in choices.items() if value.get()]
            if not clients:
                status.configure(text='Choose at least one application.', text_color='#f7ca70')
                return
            paths = '\n'.join(str(p) for name in clients for p in self.integrations.paths()[name])
            warning = ('These configuration files will be changed:\n\n' + paths +
                       '\n\nRequests from selected applications will use Gemini Accounts. '
                       'Connection settings and the default model will change. '
                       'Original files will be saved in a protected backup. '
                       'Already running clients will need a restart.\n\nAllow these changes?')
            if not messagebox.askyesno('Allow application setup?', warning, parent=window):
                return
            apply_button.configure(state='disabled')
            def done(_):
                apply_button.configure(state='normal')
                status.configure(text='Connections configured. Launch CLI clients as usual.', text_color=GREEN)
                desktops = [name for name in clients if name in ('claude_desktop', 'codex')]
                if desktops and messagebox.askyesno('Apply settings now?', 'Restart running Claude / Codex clients to apply connections? This interrupts current work. Saved sessions are preserved.', parent=window):
                    self.work(lambda: self.integrations.restart_desktop(desktops), lambda _: status.configure(text='Applications restarted with the new connection.', text_color=GREEN))
            def perform():
                try:
                    return self.integrations.apply(clients), None
                except Exception as error:
                    return None, str(error)
            def applied(result):
                configured, error = result
                if error:
                    apply_button.configure(state='normal')
                    status.configure(text='Setup failed: ' + error, text_color='#f7ca70')
                else:
                    done(configured)
            self.work(perform, applied, mutation=True)
        apply_button = self.button(window, 'Configure selected applications', apply, primary=True)
        apply_button.pack(fill='x', padx=24, pady=(8, 12))
        def restore():
            if not messagebox.askyesno('Restore previous settings?', 'Client configurations will be restored to their state before the first connection. Later edits to these files will also be replaced by the backup. Gemini Accounts preferences will return to defaults. Google sign-ins will be preserved.\n\nRestore settings?', parent=window):
                return
            def reset():
                count = self.integrations.restore()
                self.controller.preferences = {'labels': {}, 'mode': 'pool', 'selected': None, 'connections-offered': True}
                self.controller.save()
                return count
            def done(count):
                status.configure(text=f'Original configurations restored: {count}. Restart running clients.', text_color=GREEN)
                if messagebox.askyesno('Apply restoration now?', 'Restart running Claude / Codex? Current work will be interrupted; saved sessions are preserved.', parent=window):
                    self.work(lambda: self.integrations.restart_desktop(['claude_desktop', 'codex']), lambda _: status.configure(text='Applications restarted with original settings.', text_color=GREEN))
            self.work(reset, done, mutation=True)
        self.button(window, 'Restore previous settings / reset preferences', restore).pack(fill='x', padx=24)

    def rename(self, account, label):
        try:
            self.controller.rename(account['name'], label)
            self.loaded(self.items)
        except OSError:
            self.notice.configure(text='Could not save the account label.', text_color='#ffbd93')

    def add_account(self):
        if self.busy or self.pending_login:
            return
        self.work(self.controller.begin_login, self.login_started, mutation=True)

    def login_started(self, result):
        self.login_url, state = result
        self.pending_login = (state, time.monotonic())
        self.add_button.configure(state='disabled')
        self.notice.configure(text='Choose your Google account in the browser and complete sign-in. It will appear here automatically.', text_color=ACCENT)
        self.login_window = ctk.CTkToplevel(self)
        self.login_window.title('Add account')
        self.login_window.geometry('480x260')
        self.login_window.resizable(False, False)
        self.login_window.configure(fg_color=PANEL)
        self.login_window.transient(self)
        ctk.CTkLabel(self.login_window, text='Complete Google sign-in', font=('Segoe UI', 22, 'bold'), text_color=TEXT).pack(pady=(26, 10))
        ctk.CTkLabel(self.login_window, text='Choose an account in the opened browser.\nThe saved sign-in will appear in the list automatically.', font=('Segoe UI', 13), text_color=MUTED).pack(pady=8)
        self.button(self.login_window, 'Reopen sign-in page', lambda: webbrowser.open(self.login_url)).pack(pady=14)
        ctk.CTkLabel(self.login_window, text='Waiting for sign-in… You can close this window.', text_color=MUTED, font=('Segoe UI', 12)).pack()
        webbrowser.open(self.login_url)
        self.after(1800, self.poll_login)

    def poll_login(self):
        if not self.pending_login or self.closed:
            return
        state, started = self.pending_login
        if time.monotonic() - started > 310:
            self.finish_login('Sign-in timed out. Click Add Google account again.', False)
            return
        def poll():
            try:
                return self.controller.login_status(state)
            except AccountError:
                return {'status': 'wait'}
        def done(result):
            if result.get('status') == 'ok':
                self.finish_login('Account saved. You can select it for Claude.', True)
            elif result.get('status') == 'error':
                self.finish_login('Google sign-in did not finish. Try adding the account again.', False)
            else:
                self.after(1800, self.poll_login)
        self.work(poll, done)

    def finish_login(self, message, success):
        self.pending_login = None
        self.login_url = None
        self.add_button.configure(state='normal')
        if hasattr(self, 'login_window') and self.login_window.winfo_exists():
            self.login_window.destroy()
        self.notice.configure(text=message, text_color=GREEN if success else '#ffbd93')
        if success:
            def reconcile():
                results = self.controller.reconcile_new_login()
                return results, self.controller.accounts()
            def done(result):
                results, items = result
                self.loaded(items)
                pending = next((r for r in results if r.get('access_issue') == 'verification'), None)
                error = next((r for r in results if r.get('status') == 'error'), None)
                if pending:
                    self.notice.configure(text='Google requires verification of this account. Opening the page; controls are at the top of the list.', text_color='#f7ca70')
                    if pending.get('verification_url'):
                        webbrowser.open(pending['verification_url'])
                elif error:
                    self.notice.configure(text=error['message'], text_color='#ffbd93')
                else:
                    self.notice.configure(text='Account verified and added to automatic routing.' if self.controller.preferences.get('mode') != 'single' else 'Account verified. Another account is currently selected manually.', text_color=GREEN)
            self.work(reconcile, done, mutation=True)

    def close(self):
        self.closed = True
        self.destroy()


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('GeminiAccounts.Desktop')
    ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.windll.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\GeminiAccountsDesktop')
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, 'Gemini Accounts is already open. Find its window in the taskbar.', 'Gemini Accounts', 0)
        return
    ctk.set_appearance_mode('dark')
    try:
        App().mainloop()
    finally:
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    main()
