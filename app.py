import ctypes
import copy
import json
import queue
import threading
import time
import webbrowser
import urllib.parse
from pathlib import Path
import os
import sys
import math
import colorsys
import re
import base64
import io
from PIL import Image, ImageDraw, ImageTk
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ui_style import ctk, Canvas, UIStyle, localized_messagebox as messagebox, localized_simpledialog as simpledialog
import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont
from backend import Controller, AccountError
from account_status import account_status, google_account_status, safe_detail, status_details
from brand_icons import ANTIGRAVITY_PNG, GITHUB_PNG
from omni_brand import omni_icon
from quota_dots import quota_dot
from quota_slider import QuotaLimitBar
from quota_limits import quota_floor, blocked_families, sync_quota_limits
from activity import Activity
from token_capacity import TokenCapacity
from harbor_activity import HarborActivity, key_id, key_label
from routing import rank_accounts, quota_projection, quota_entry
from chatgpt_routing import is_free_account
from integrations import Integrations
from tokenharbor import TokenHarbor
from chatgpt_auth import ChatGPTAuth
from chatgpt_oauth_pending import PendingChatGPTLogins
from claude_ui import ClaudeSupport, ClaudePanel
from provider_ui import ProviderSupport, GrokPanel
from model_names import model_name
from telegram_notifications import TelegramBot, TelegramError

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


class App(ProviderSupport, ClaudeSupport, ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title('Omni')
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
        self.telegram_bot = TelegramBot(self.controller.data_dir / 'telegram-bot-token.bin')
        self._telegram_status_initialized = set()
        self.chatgpt_pending_store = PendingChatGPTLogins(self.controller.data_dir / 'chatgpt-oauth-pending.json')
        self.ui_style = UIStyle(self, self.controller.preferences)
        self.configure(fg_color=BG)
        self.visible_services = self.controller.preferences.get('visible-services', {})
        self.model_aliases = self.controller.model_aliases()
        self.integrations = Integrations(self.controller)
        self.provider_icons = self.make_provider_icons()
        self.playback_icons = self.make_playback_icons()
        self.mailbox = queue.Queue()
        self.items = []
        self.selected = None
        self.model_cache = {}
        self.quota_cache = {}
        self.quota_pending = set()
        self.quota_render_job = None
        self.account_widgets = {}
        self.detail_account = object()
        self.detail_quota_widgets = {}
        self.model_widgets = {}
        self.drawn_models = None
        self.busy = False
        self.pending_login = None
        self.pending_chatgpt_login = None
        self.chatgpt_login_polling = set()
        self._activate_chatgpt_login(self.chatgpt_pending_store.all()[0]['state'] if self.chatgpt_pending_store.all() else None)
        self.pending_claude_login = None
        self.pending_grok_login = None
        self.model_route_error = None
        self.login_url = None
        self.activity = Activity(self.controller.data_dir / 'activity.json')
        self.token_capacity = TokenCapacity(self.controller.data_dir / 'token-capacity.json')
        self.harbor_activity = HarborActivity(self.controller.data_dir / 'tokenharbor-activity.json')
        self.activity_state = copy.deepcopy(self.activity.state)
        self.recent_account_models = self.latest_models_by_account(self.activity_state)
        self.activity_started = False
        self.activity_busy = False
        self.gateway_jobs = []
        self.gateway_jobs_checked = 0
        self.tokenharbor_collapsed = self.controller.preferences.get('tokenharbor-collapsed', True)
        self.chatgpt_collapsed = self.controller.preferences.get('chatgpt-collapsed', True)
        self.chatgpt_free_collapsed = self.controller.preferences.get('chatgpt-free-collapsed', True)
        self.google_accounts_collapsed = self.controller.preferences.get('google-accounts-collapsed', False)
        self.chatgpt_items = []
        self.chatgpt_rendered_items = {}
        self.chatgpt_quota_pending = set()
        self.chatgpt_refresh_pending = False
        self.claude_items = []
        self.grok_items = []
        self.api_items = []
        self.hide_account_names = self.controller.preferences.get('hide-account-names', False)
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
        self.sidebar.pack_propagate(False)
        self.grid_columnconfigure(0, minsize=round(self.sidebar._apply_widget_scaling(SIDEBAR_WIDTH)))
        sidebar_header = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        sidebar_header.pack(fill='x', padx=16, pady=(3, 4))
        self.omni_icon = ctk.CTkImage(light_image=omni_icon(), dark_image=omni_icon(), size=(24, 24))
        ctk.CTkLabel(sidebar_header, text='Omni', image=self.omni_icon, compound='left', height=22,
                     font=('Segoe UI', 18, 'bold'), text_color=TEXT).pack(side='left')
        self.details_toggle = self.button(sidebar_header, '☰', self.toggle_details)
        self.details_toggle.configure(height=26, width=28, font=('Segoe UI', 20), fg_color='transparent')
        self.details_toggle.pack(side='right')
        self.settings_button = self.button(sidebar_header, '⚙', self.open_display_settings)
        self.settings_button.configure(height=26, width=28, font=('Segoe UI', 20), fg_color='transparent')
        self.settings_button.pack(side='right', padx=(0, 4))
        self.window_pinned = bool(self.controller.preferences.get('window-pinned', False))
        self.pin_button = self.button(sidebar_header, '', self.toggle_window_pin)
        self.pin_button.configure(width=24, height=26, corner_radius=4, image=self.playback_icons['pin'],
                                  fg_color=ACCENT if self.window_pinned else 'transparent')
        self.pin_button.pack(side='right', padx=(0, 2))
        self.attach_tooltip(self.pin_button, lambda: 'Unpin window' if self.window_pinned else 'Keep window on top')
        self.attributes('-topmost', self.window_pinned)
        self.add_button = self.add_chatgpt_button = self.add_claude_button = None
        self.add_grok_button = self.add_tokenharbor_button = None
        self.privacy_icons = {}
        for hidden in (False, True):
            icon = Image.new('RGBA', (64, 64))
            draw = ImageDraw.Draw(icon)
            if hidden:
                draw.arc((5, 7, 59, 41), start=0, end=180, fill=TEXT, width=5)
                for lash in ((15, 35, 10, 43), (32, 41, 32, 51), (49, 35, 54, 43)):
                    draw.line(lash, fill=TEXT, width=4)
            else:
                draw.ellipse((5, 17, 59, 47), outline=TEXT, width=5)
                draw.ellipse((23, 23, 41, 41), fill=TEXT)
            light_icon = Image.new('RGBA', icon.size, '#243047')
            light_icon.putalpha(icon.getchannel('A'))
            self.privacy_icons[hidden] = ctk.CTkImage(light_image=light_icon, dark_image=icon, size=(21, 21))
        self.privacy_toggle = self.button(sidebar_header, '', self.toggle_account_names)
        self.privacy_toggle.configure(width=28, height=26, image=self.privacy_icons[self.hide_account_names],
                                      fg_color='#303e59')
        self.privacy_toggle.pack(side='left', padx=(5, 0))
        self.sidebar_footer = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        self.sidebar_footer.pack(side='bottom', fill='x')
        self.account_list = ctk.CTkScrollableFrame(self.sidebar, fg_color='transparent')
        self.account_list.pack(fill='both', expand=True, padx=2)
        self.account_list._scrollbar.grid(padx=0, pady=0)
        self.account_list._parent_canvas.grid_configure(padx=0, pady=0)
        self.chatgpt_accounts = ctk.CTkFrame(self.account_list, fg_color='transparent')
        self.chatgpt_free_accounts = ctk.CTkFrame(self.account_list, fg_color='transparent')
        # Zero-height anchor keeps the two OpenAI groups above Gemini inside
        # the same scrollable canvas without changing their incremental layout.
        self.sidebar_spacer = ctk.CTkFrame(self.account_list, height=0, fg_color='transparent')
        self.sidebar_spacer.pack(fill='x')
        self.tokenharbor_accounts = ctk.CTkFrame(self.sidebar_footer, fg_color='transparent')
        self.google_accounts_header = self.button(self.account_list, '', self.toggle_google_accounts)
        self.google_accounts_header.configure(image=self.provider_icons['antigravity'], compound='left', height=27, anchor='w',
                                              font=('Segoe UI', 11, 'bold'), fg_color='#303b50')
        self.google_accounts_header.pack(fill='x', padx=1, pady=(0, 2))
        self.google_compact = self.make_quota_dots(self.google_accounts_header, ('G 5h', 'G 1w', 'C 5h', 'C 1w'))
        self.google_accounts_content = ctk.CTkFrame(self.account_list, fg_color='transparent')
        self.google_accounts_content.pack(fill='x', padx=0)
        self.draw_chatgpt_accounts()
        self.service = ctk.CTkLabel(self.sidebar_footer, text='Connecting…', text_color=MUTED, font=('Segoe UI', 10), height=14)
        self.service.pack(anchor='w', padx=18)
        self.pool_summary_groups = {}
        google_summary = self.create_pool_summary('google', 'Google Gemini')
        self.total_quota_frame = ctk.CTkFrame(google_summary, fg_color='transparent')
        self.total_quota_frame.pack(fill='x', pady=(0, 5))
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
        weekly_frame = ctk.CTkFrame(google_summary, fg_color='transparent')
        weekly_frame.pack(fill='x', pady=(0, 6))
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
        openai_summary = self.create_pool_summary('openai', 'OpenAI')
        self.openai_pool_widgets = {}
        self.openai_forecasts = {}
        self.openai_forecast_canvases = {}
        for window in ('5h', '1w'):
            row = ctk.CTkFrame(openai_summary, fg_color='transparent')
            row.pack(fill='x', pady=(0, 6))
            header = ctk.CTkFrame(row, fg_color='transparent')
            header.pack(fill='x')
            title = ctk.CTkLabel(header, text=f'{window} · pooled remaining', height=18,
                font=('Segoe UI', 11), text_color=TEXT)
            title.pack(side='left')
            value = ctk.CTkLabel(header, text='—', height=18, font=('Segoe UI', 12, 'bold'), text_color=MUTED)
            value.pack(side='right')
            bar = ctk.CTkProgressBar(row, height=6, fg_color='#354157', progress_color=GREEN)
            bar.pack(fill='x', pady=(1, 0))
            bar.set(0)
            self.openai_pool_widgets[window] = (title, value, bar)
            canvas = Canvas(row, height=1, bg=PANEL, highlightthickness=0, borderwidth=0)
            self.openai_forecast_canvases[window] = canvas
            canvas.bind('<Configure>', lambda event, w=window: self.schedule_total_forecast(openai_window=w))
            canvas.bind('<Motion>', lambda event, w=window: self.hover_forecast(event, openai_window=w))
            canvas.bind('<Leave>', lambda event, c=canvas: c.delete('forecast_hover'))
        self.tokenharbor_accounts.pack(fill='x', padx=12, pady=(3, 5))
        self.apply_service_visibility()
        self.body = ctk.CTkFrame(self, fg_color='transparent')
        self.body.grid(row=0, column=1, sticky='nsew', padx=32, pady=28)
        body_header = ctk.CTkFrame(self.body, fg_color='transparent')
        body_header.pack(fill='x')
        ctk.CTkLabel(body_header, text='Saved accounts', font=('Segoe UI', 30, 'bold'), text_color=TEXT).pack(side='left')
        self.button(body_header, 'Connect applications', self.connection_settings).pack(side='right')
        github = Image.open(io.BytesIO(base64.b64decode(GITHUB_PNG))).convert('RGBA')
        github_light = Image.new('RGBA', github.size, '#243047')
        github_light.putalpha(github.getchannel('A'))
        self.github_icon = ctk.CTkImage(light_image=github_light, dark_image=github, size=(22, 22))
        self.github_release_button = self.button(body_header, '', self.open_github_release)
        self.github_release_button.configure(image=self.github_icon, width=39, height=39, fg_color='transparent')
        self.github_release_button.pack(side='right', padx=(0, 10))
        ctk.CTkLabel(self.body, text='Switch accounts while continuing your Claude sessions.', text_color=MUTED, font=('Segoe UI', 14)).pack(anchor='w', pady=(4, 24))
        self.mode_frame = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=14)
        self.mode_frame.pack(fill='x', pady=(0, 18))
        self.mode_label = ctk.CTkLabel(self.mode_frame, text='Loading accounts…', font=('Segoe UI', 14, 'bold'), text_color=TEXT)
        self.mode_label.pack(anchor='w', padx=12, pady=(8, 2))
        self.mode_note = ctk.CTkLabel(self.mode_frame, text='Connected clients use the selected accounts.', text_color=MUTED, font=('Segoe UI', 12))
        self.mode_note.pack(anchor='w', padx=12, pady=(0, 3))
        self.pool_button = self.button(self.mode_frame, 'Use all • automatic routing', lambda: self.action(lambda: self.controller.route(), 'Automatic routing enabled.'))
        self.pool_button.configure(height=25, width=132, font=('Segoe UI', 11, 'bold'))
        self.pool_button.pack(anchor='w', padx=12, pady=(0, 8))
        self.mode_activity = ctk.CTkLabel(self.mode_frame, text='Last request: waiting for proxy data', text_color=MUTED, font=('Segoe UI', 12), anchor='w')
        self.mode_activity.pack(fill='x', padx=12, pady=(0, 4), before=self.pool_button)
        self.detail = ctk.CTkScrollableFrame(self.body, fg_color='transparent')
        self.detail.pack(fill='both', expand=True)
        self.display_settings = ctk.CTkScrollableFrame(self.body, fg_color='transparent')
        self.draw_display_settings()
        self.stats_view = ctk.CTkScrollableFrame(self.body, fg_color='transparent')
        self.stats_title = self.label(self.stats_view, 'Automatic routing', 22, bold=True)
        self.button(self.stats_view, 'Save diagnostic log…', self.save_diagnostic_log).pack(anchor='w', pady=(0, 10))
        self.button(self.stats_view, 'Send diagnostic log…', self.send_diagnostic_log).pack(anchor='w', pady=(0, 10))
        self.update_button = self.button(self.stats_view, 'Check for updates', self.check_for_updates)
        self.update_button.pack(anchor='w', pady=(0, 10))
        self.available_update = None
        self.pending_update = None
        self.stats_strategy = self.label(self.stats_view, 'Starting monitoring…', 13, MUTED)
        self.label(self.stats_view, 'Priority: earliest reset among available accounts', 15, bold=True)
        self.policy_control = ctk.CTkSegmentedButton(self.stats_view, values=['Current model', 'Gemini', 'Claude / GPT'], command=self.set_policy_group)
        self.policy_control.set({'gemini': 'Gemini', 'claude': 'Claude / GPT'}.get(self.controller.preferences.get('reset-group'), 'Current model'))
        self.policy_control.pack(anchor='w', pady=(0, 6))
        self.policy_label = self.label(self.stats_view, 'Loading quotas to rank accounts…', 12, MUTED)
        self.stats_latest = self.label(self.stats_view, 'Last successful request: no data yet', 16, bold=True)
        self.stats_note = self.label(self.stats_view, 'Accounts are identified from completed requests. The proxy does not report the account during generation. Different models may use different accounts.', 12, MUTED)
        self.stats_totals = self.label(self.stats_view, '', 13)
        calculator = ctk.CTkFrame(self.stats_view, fg_color=CARD, corner_radius=8, height=1)
        calculator.pack(fill='x', pady=(4, 10))
        self.label(calculator, 'Token capacity calculator', 15, bold=True)
        calculator_controls = ctk.CTkFrame(calculator, fg_color='transparent', height=1)
        calculator_controls.pack(fill='x', padx=8)
        self.capacity_model = ctk.CTkOptionMenu(calculator_controls, values=['No observations yet'],
                                              command=lambda _: self.render_token_capacity(), width=280)
        self.capacity_model.pack(side='left')
        self.capacity_percent = ctk.CTkEntry(calculator_controls, width=55, height=28)
        self.capacity_percent.insert(0, '100')
        self.capacity_percent.pack(side='left', padx=(8, 3))
        self.capacity_percent.bind('<KeyRelease>', lambda _: self.render_token_capacity())
        self.label(calculator_controls, '% of quota', 12)
        self.capacity_result = self.label(calculator, 'Insufficient data', 13)
        self.label(calculator, 'Estimate from observed tokens and quota changes. Mixed-model intervals and resets are excluded. External usage can affect accuracy.', 11, MUTED)
        self.capacity_options = {}
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
        self.view_switch = ctk.CTkSegmentedButton(self.body, values=['Account and quotas', 'Routing statistics', 'Display settings'], command=self.change_view)
        self.view_switch.set('Account and quotas')
        self.view_switch.pack(before=self.detail._parent_frame, anchor='w', pady=(0, 10))
        self.notice = ctk.CTkLabel(self.body, text='Sign-ins are preserved when the application closes.', text_color=MUTED, font=('Segoe UI', 12), wraplength=660, justify='left')
        self.notice.pack(anchor='w', pady=(12, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.claude_panel = ClaudePanel(self)
        self.grok_panel = GrokPanel(self)
        self.initialize_api_cards()
        self.draw_tokenharbor_accounts()
        self.after_idle(lambda: self.after_idle(self.show_saved_window))
        self.position_save_job = None
        self.bind('<Configure>', self.schedule_window_position_save, add='+')
        self.after(100, self.consume)
        self.after(120, lambda: self.refresh(prepare=True))
        self.after(60000, self.periodic_quota)
        self.after(15000, self.tick_countdowns)
        self.after(500, self.animate_active_borders)
        self.after(33, self.animate_border_colors)
        self.after(200, self.poll_gateway_jobs)
        self.after(30000, self.check_for_updates)
        if self.pending_chatgpt_login:
            self.after(700, self.resume_chatgpt_login)
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
        for account in self.items:
            widgets = self.account_widgets.get(account['name'])
            if widgets:
                self.update_selection_style(account, widgets)
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

    def open_github_release(self):
        from updater import REPO
        webbrowser.open('https://github.com/' + REPO + '/releases/latest')

    def open_display_settings(self):
        if getattr(self, 'restore_details_job', None):
            self.after_cancel(self.restore_details_job)
            self.restore_details_job = None
        if self.details_collapsed:
            self.toggle_details()
        self.view_switch.set('Display settings')
        self.change_view('Display settings')

    def make_quota_limit_bar(self, parent, name, group, window, **kwargs):
        return QuotaLimitBar(parent, floor=quota_floor(self.controller.preferences, name, group, window),
            command=lambda value: self.set_quota_floor(name, group, window, value), **kwargs)

    def set_quota_floor(self, name, group, window, value):
        self.controller.preferences.setdefault('quota-floors', {}).setdefault(name, {}).setdefault(group, {})[window] = value
        self.controller.save()
        if group == 'claude-native':
            self.claude_panel.render()
            self.refresh_claude_accounts()
        elif group == 'openai':
            self.draw_chatgpt_accounts()
            self.refresh_chatgpt_accounts()
        else:
            self.draw_account_list()
            if self.selected == name:
                self.update_detail_quota()
            account = next((item for item in self.items if item['name'] == name), None)
            if account:
                groups = self.quota_groups(name)
                self.work(lambda: sync_quota_limits(self.controller, account, groups),
                          lambda _: self.fetch_quota(name))
        self.notice.configure(text=f'Quota reserve: {value}%', text_color=MUTED)

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
            self.set_provider_login_buttons(False)
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
                self.set_provider_login_buttons(True)
                self.pool_button.configure(state='normal')
            if error:
                self.notice.configure(text=self.redact_private_text(error), text_color='#ffbd93')
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
            if prepare:
                try:
                    self.integrations.reconcile_desktop_routes()
                except (AccountError, OSError, ValueError) as error:
                    self.model_route_error = str(error)
            return self.controller.accounts()
        self.work(load, self.loaded, mutation=True)

    def loaded(self, items):
        if items and (self.controller.data_dir / 'installation.json').exists() and not self.controller.preferences.get('connections-offered'):
            self.controller.preferences['connections-offered'] = True
            self.controller.save()
            self.after(500, self.connection_settings)
        self.items = items
        if 'gemini' not in self._telegram_status_initialized:
            self._telegram_google_bootstrap = {account.get('name') for account in items if account.get('name')}
        self.observe_account_statuses('gemini', items)
        self.service.configure(text='●  Connected', text_color=GREEN)
        if self.model_route_error:
            self.notice.configure(text=self.model_route_error, text_color='#ffbd93')
        if self.selected not in {a['name'] for a in items}:
            self.selected = items[0]['name'] if items else None
        self.update_mode_label()
        self.draw_account_list()
        self.refresh_chatgpt_accounts()
        self.refresh_claude_accounts()
        self.refresh_grok_accounts()
        self.refresh_api_accounts()
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

    def update_mode_label(self):
        items = self.routing_accounts()
        enabled = [a for a in items if not a.get('disabled')]
        if not enabled:
            mode = 'No accounts enabled'
        elif len(enabled) == len(items) and self.controller.preferences.get('mode') != 'single':
            mode = f'Automatic routing • enabled accounts: {len(enabled)}'
        elif len(enabled) == 1:
            mode = 'For Claude: ' + self.display_name(enabled[0])
        else:
            mode = f'Enabled accounts: {len(enabled)} of {len(items)}'
        self.mode_label.configure(text=mode)

    def routing_accounts(self):
        return list({a['name']: a for field in ('items', 'chatgpt_items', 'claude_items', 'grok_items', 'api_items')
                     for a in getattr(self, field, [])}.values())

    def uptime_status(self, widget, account, text):
        from account_uptime import update_uptime
        states = self.controller.preferences.setdefault('account-uptime', {})
        duration, changed = update_uptime(states, account, time.time())
        if changed:
            self.controller.save()
        widget.uptime_account = account
        widget.uptime_base = text
        return text + ' · ' + duration

    def tick_account_uptimes(self):
        rows = list(getattr(self, 'chatgpt_widgets', {}).values()) + list(getattr(self, 'account_widgets', {}).values())
        rows += list(getattr(self, 'api_rows', {}).values())
        for panel in ('claude_panel', 'grok_panel'):
            rows += list(getattr(getattr(self, panel, None), 'rows', {}).values())
        widgets = [row.get('status') or row.get('state') for row in rows]
        widgets += [row[1] for row in getattr(self, 'tokenharbor_rows', {}).values()]
        for widget in widgets:
            if widget is not None and hasattr(widget, 'uptime_account'):
                text = self.uptime_status(widget, widget.uptime_account, widget.uptime_base)
                if widget.cget('text') != text:
                    widget.configure(text=text)

    def refresh_chatgpt_accounts(self):
        if not self.controller.key or self.closed or self.chatgpt_refresh_pending:
            return
        self.chatgpt_refresh_pending = True
        def progress(account):
            self.mailbox.put((self.publish_chatgpt_quota, account, None, False))
        def load():
            try:
                return ChatGPTAuth(self.controller).accounts_with_quotas(maintain_pool=True, on_quota=progress)
            finally:
                self.mailbox.put((self.finish_chatgpt_refresh, None, None, False))
        self.work(load, self.set_chatgpt_accounts)

    def finish_chatgpt_refresh(self, _result):
        self.chatgpt_refresh_pending = False

    def publish_chatgpt_quota(self, account):
        if self.closed:
            return
        rows = [item for item in self.chatgpt_items if item['name'] != account['name']]
        self.set_chatgpt_accounts(rows + [account])

    def refresh_new_chatgpt_accounts(self):
        """Discover newly connected accounts without rechecking the whole pool."""
        if not self.controller.key or self.closed:
            return
        def load():
            return ChatGPTAuth(self.controller).accounts()
        def done(accounts):
            if self.closed:
                return
            previous = {item['name']: item for item in self.chatgpt_items}
            additions = []
            merged = []
            for fresh in accounts:
                old = previous.get(fresh['name'])
                if old is None:
                    item = dict(fresh)
                    additions.append(item)
                else:
                    # This is a discovery pass after login, not a refresh of
                    # the existing pool. Keep existing card data byte-for-byte
                    # so adding one account cannot churn the other rows.
                    item = dict(old)
                merged.append(item)
            self.set_chatgpt_accounts(merged)
            for item in additions:
                self.fetch_chatgpt_account_quota(item)
        self.work(load, done)

    def fetch_chatgpt_account_quota(self, account):
        name = account['name'] if isinstance(account, dict) else account
        if name in getattr(self, 'chatgpt_quota_pending', set()):
            return
        current = next((item for item in self.chatgpt_items if item['name'] == name), None)
        account = dict(account if isinstance(account, dict) else current or {})
        if not account or not account.get('auth_index'):
            return
        self.chatgpt_quota_pending = getattr(self, 'chatgpt_quota_pending', set())
        self.chatgpt_quota_pending.add(name)
        def load():
            try:
                return ChatGPTAuth(self.controller).quota(account), None
            except (AccountError, ValueError, TypeError) as error:
                return None, str(error)
        def done(result):
            self.chatgpt_quota_pending.discard(name)
            quota, error = result
            rows = []
            for item in self.chatgpt_items:
                updated = dict(item)
                if item['name'] == name:
                    if quota is not None:
                        updated['quota'] = quota
                        if quota.get('plan_type'):
                            updated['plan_type'] = quota['plan_type']
                    elif error:
                        updated['quota'] = {'windows': [], 'error': error}
                rows.append(updated)
            if quota and not error:
                self.observe_token_capacity(name, 'OpenAI', quota.get('plan_type') or account.get('plan_type') or 'unknown',
                                            ChatGPTAuth.quota_limit_groups(quota))
            self.set_chatgpt_accounts(rows)
        self.work(load, done)

    def set_chatgpt_accounts(self, accounts):
        previous = {item['name']: item for item in self.chatgpt_items}
        merged = []
        for item in accounts:
            old = previous.get(item['name'], {})
            quota = item.get('quota')
            if quota is not None and not quota.get('error'):
                self.observe_token_capacity(item['name'], 'OpenAI', quota.get('plan_type') or item.get('plan_type') or 'unknown',
                                            ChatGPTAuth.quota_limit_groups(quota))
            cached = old.get('quota') or {}
            if quota is None:
                if cached:
                    item['quota'] = cached
            elif quota.get('error') and not quota.get('windows') and cached.get('windows'):
                item['quota'] = {**cached, 'error': quota['error']}
            if not item.get('plan_type') and old.get('plan_type'):
                item['plan_type'] = old['plan_type']
            merged.append(item)
        rendered = getattr(self, 'chatgpt_rendered_items', {})
        widgets = getattr(self, 'chatgpt_widgets', {})
        changed_names = {item['name'] for item in merged
                         if item['name'] not in previous or item['name'] not in widgets
                         or rendered.get(item['name']) != item}
        self.chatgpt_rendered_items = {item['name']: copy.deepcopy(item) for item in merged}
        self.chatgpt_items = merged
        self.observe_account_statuses('openai', merged)
        self.draw_chatgpt_accounts(changed_names=changed_names)
        self.update_openai_pool_quota()
        self.update_mode_label()

    def remove_chatgpt_account(self, name):
        account = next((a for a in self.chatgpt_items if a['name'] == name), None)
        if not account or not messagebox.askyesno('Remove account?',
                'Remove ' + self.display_name(account, 'OpenAI') + ' from Omni?', parent=self):
            return
        def remove():
            self.controller.request('/auth-files?' + urllib.parse.urlencode({'name': name}), 'DELETE')
            for field in ('account-priorities', 'quota-floors', 'labels'):
                self.controller.preferences.get(field, {}).pop(name, None)
            self.controller.save()
            accounts = ChatGPTAuth(self.controller).accounts()
            if any(a['name'] == name for a in accounts):
                raise AccountError('The gateway did not confirm account removal. Refresh the list.')
            return accounts
        self.work(remove, self.set_chatgpt_accounts, mutation=True)

    def observe_token_capacity(self, name, provider, plan, groups):
        models = self.activity_state.get('model_tokens', {}).get(name, {})
        for group in groups:
            family = group['kind']
            selected = {model: tokens for model, tokens in models.items()
                        if provider != 'Google' or self.model_family(model) == family}
            self.token_capacity.observe(name, provider, plan, [group], selected)
        self.render_token_capacity()

    def render_token_capacity(self):
        if not hasattr(self, 'capacity_result'):
            return
        options = {}
        for row in self.token_capacity.rows():
            title = f"{row['provider']} · {row['plan']} · {row['model']}"
            options.setdefault(title, {})[row['window']] = row
        if options != self.capacity_options:
            current = self.capacity_model.get()
            self.capacity_options = options
            values = list(options) or ['No observations yet']
            self.capacity_model.configure(values=values)
            if current not in values:
                self.capacity_model.set(values[0])
        try:
            percent = float(self.capacity_percent.get().replace(',', '.'))
            if not math.isfinite(percent) or not 0 <= percent <= 100:
                raise ValueError
        except ValueError:
            self.capacity_result.configure(text='Enter a percentage from 0 to 100')
            return
        windows = self.capacity_options.get(self.capacity_model.get(), {})
        lines = []
        for window, label in (('5h', '5h'), ('weekly', '1w')):
            row = windows.get(window)
            if not row or not row['ready']:
                text = self.ui_style.text('Insufficient data')
                if row:
                    text += f" · {row['samples']}/3 " + self.ui_style.text('samples')
            else:
                estimate = round(row['capacity'] * percent / 100)
                text = f"≈ {estimate:,} " + self.ui_style.text('tokens')
                text += f" · {row['samples']} " + self.ui_style.text('samples')
                text += f" · {row['used']*100:.1f}% " + self.ui_style.text('observed usage')
            lines.append(f'{label}: {text}')
        self.capacity_result.configure(text='\n'.join(lines))

    def draw_chatgpt_accounts(self, changed_names=None):
        rows = sorted(self.chatgpt_items, key=lambda item: (self.account_empty_quota(item), self.account_problem_rank(item),
                      -self.account_priority(item),
                      item.get('email') or item.get('name') or ''))
        free_rows = [item for item in rows if is_free_account(item)]
        paid_rows = [item for item in rows if not is_free_account(item)]
        widgets = getattr(self, 'chatgpt_widgets', {})
        self.chatgpt_widgets = widgets
        names = {item['name'] for item in rows}
        for name in list(widgets):
            if name not in names:
                widgets.pop(name)['card'].destroy()
        if not self.provider_visible('openai'):
            self.chatgpt_accounts.pack_forget()
            self.chatgpt_free_accounts.pack_forget()
            return
        if not rows and not self.provider_api_count('openai'):
            self._chatgpt_order = None
            self.chatgpt_accounts.pack_forget()
            self.chatgpt_free_accounts.pack_forget()
            return
        anchor = self.google_accounts_header if getattr(self, 'google_accounts_header', None) and self.google_accounts_header.winfo_manager() else self.sidebar_spacer
        def section(frame, header_name, compact_name, title, count, collapsed, command):
            if not frame.winfo_manager():
                options = {'fill': 'x', 'padx': 0, 'pady': (0, 3)}
                if anchor.winfo_manager():
                    options['before'] = anchor
                frame.pack(**options)
            header = getattr(self, header_name, None)
            if header is None:
                header = self.button(frame, '', command)
                header.configure(image=self.provider_icons['openai'], compound='left', height=27, anchor='w', font=('Segoe UI', 11, 'bold'), fg_color='#303b50')
                header.pack(fill='x', padx=1, pady=(1, 2))
                setattr(self, header_name, header)
            header.configure(text=('▸' if collapsed else '▾') + f'  {title} · {count}pcs')
            compact = getattr(self, compact_name, None)
            if compact is None:
                compact = self.make_quota_dots(header, ('5h', '1w'))
                setattr(self, compact_name, compact)
            self.show_quota_dots(compact, collapsed, after=header)
            return header
        if paid_rows or self.provider_api_count('openai'):
            section(self.chatgpt_accounts, 'chatgpt_header', 'chatgpt_compact', 'ChatGPT', len(paid_rows) + self.provider_api_count('openai'), self.chatgpt_collapsed, self.toggle_chatgpt_accounts)
        else:
            self.chatgpt_accounts.pack_forget()
        if free_rows:
            section(self.chatgpt_free_accounts, 'chatgpt_free_header', 'chatgpt_free_compact', 'ChatGPT Free', len(free_rows), self.chatgpt_free_collapsed, self.toggle_chatgpt_free_accounts)
        else:
            self.chatgpt_free_accounts.pack_forget()
        self.update_compact_quotas()
        for item in rows:
            name = item['name']
            frame = self.chatgpt_free_accounts if is_free_account(item) else self.chatgpt_accounts
            if name in widgets and widgets[name]['card'].master is not frame:
                widgets.pop(name)['card'].destroy()
            if name not in widgets:
                card = ctk.CTkFrame(frame, height=1, fg_color='#202938', corner_radius=8, border_width=1, border_color='#344155')
                def label(height=17, color=MUTED):
                    return ctk.CTkLabel(card, text='', height=height, anchor='w', font=('Segoe UI', 10), text_color=color)
                heading_row = ctk.CTkFrame(card, fg_color='transparent')
                heading_row.pack(fill='x', padx=8, pady=(6, 0))
                heading_row.grid_columnconfigure(0, weight=1)
                heading = ctk.CTkLabel(heading_row, text='', localize=False, width=1, height=20, anchor='w', text_color=TEXT)
                heading.configure(font=('Segoe UI', 11), image=self.provider_icons['openai'], compound='left')
                heading.grid(row=0, column=0, sticky='ew')
                self.bind_account_rename(heading, name, 'OpenAI')
                controls = ctk.CTkFrame(heading_row, fg_color='transparent', height=20, width=1)
                controls.grid(row=0, column=2, sticky='e')
                pause = self.account_pause_button(controls, name, 'openai')
                pause.pack(side='right')
                remove = self.button(controls, '×', lambda n=name: self.remove_chatgpt_account(n))
                remove.configure(width=18, height=18, font=('Segoe UI', 12), fg_color='transparent')
                remove.pack(side='right')
                self.attach_tooltip(remove, 'Remove account')
                model = ctk.CTkLabel(heading_row, text='', width=1, height=20, font=('Segoe UI', 9, 'bold'), text_color='#bac9df')
                model.grid(row=0, column=1, sticky='e', padx=(4, 0))
                status_row = ctk.CTkFrame(card, fg_color='transparent')
                status_row.pack(fill='x', padx=8, pady=(0, 3))
                priority = self.make_priority_counter(controls, item, 'openai')
                plan = ctk.CTkLabel(status_row, text='', height=17, width=1, corner_radius=5,
                                    fg_color='#264268', text_color=TEXT, font=('Segoe UI', 9, 'bold'))
                plan.pack(side='left', padx=(0, 5))
                status = ctk.CTkLabel(status_row, text='', height=17, anchor='w', font=('Segoe UI', 10), text_color=MUTED)
                status.pack(side='left', fill='x', expand=True)
                self.attach_tooltip(status, lambda n=name: str(next((a.get('success', 0) for a in self.chatgpt_items if a['name'] == n), 0)) + ' responses')
                windows = ctk.CTkFrame(card, height=1, fg_color='transparent')
                missing_window = ctk.CTkLabel(windows, text='5h: Not provided by OpenAI', height=15,
                                             anchor='w', font=('Segoe UI', 10), text_color=MUTED)
                # Leave the card border visible beside the quota rows.
                windows.pack(fill='x', padx=6, pady=(0, 6))
                reset_row = ctk.CTkFrame(controls, fg_color='transparent', height=18, width=18)
                reset_row.pack_propagate(False)
                credits = ctk.CTkLabel(reset_row, text='', width=1, height=15, anchor='w',
                                       font=('Segoe UI', 10), text_color=MUTED)
                # Reset count is included in the icon button; no separate credit row.
                reset_button = self.button(reset_row, '', lambda: None)
                reset_button.configure(height=17, width=18, corner_radius=1, font=('Segoe UI', 13),
                                       fg_color='transparent', image=self.playback_icons['reset'], compound='left', border_spacing=0)
                reset_details = ctk.CTkLabel(self, text='', height=24, corner_radius=5,
                                            fg_color='#303b50', font=('Segoe UI', 10), text_color=TEXT)
                widgets[name] = {'card': card, 'heading': heading, 'pause': pause, 'remove': remove, 'model': model, 'status': status, 'plan': plan, 'priority': priority,
                    'windows_frame': windows, 'windows': {}, 'missing_window': missing_window, 'credits': credits, 'reset_row': reset_row,
                    'reset_details': reset_details, 'reset_button': reset_button, 'reset_buttons': [reset_button],
                    'error': label(15)}
                def hide_reset_tip(event=None, tip=reset_details):
                    tip.place_forget()
                def show_reset_tip(event=None, tip=reset_details, target=reset_button):
                    if not tip.cget('text'):
                        return
                    x = target.winfo_rootx() - self.winfo_rootx()
                    y = target.winfo_rooty() - self.winfo_rooty()
                    tip.place(x=tip._reverse_widget_scaling(x), y=tip._reverse_widget_scaling(y), anchor='sw')
                    tip.lift()
                reset_button.bind('<Enter>', show_reset_tip, add='+')
                reset_button.bind('<Leave>', hide_reset_tip, add='+')
                reset_button.bind('<Button-1>', hide_reset_tip, add='+')
                card.bind('<Destroy>', lambda event, tip=reset_details, owned=card:
                          tip.destroy() if event.widget is owned and tip.winfo_exists() else None, add='+')
            if changed_names is None or name in changed_names or name not in widgets:
                self.update_chatgpt_row(item)
        order = tuple(item['name'] for item in paid_rows)
        free_order = tuple(item['name'] for item in free_rows)
        # Keep the legacy first two tuple positions stable for diagnostics and
        # existing integrations; append the free-section state after them.
        state = (self.chatgpt_collapsed, order, self.chatgpt_free_collapsed, free_order)
        old_state = getattr(self, '_chatgpt_order', None)
        if old_state != state:
            def ordered_subsequence(old, new):
                iterator = iter(new)
                return all(any(candidate == name for candidate in iterator) for name in old)

            incremental = (old_state is not None and old_state[0] == state[0] and old_state[2] == state[2]
                           and ordered_subsequence(old_state[1], order)
                           and ordered_subsequence(old_state[3], free_order))
            if incremental:
                for old_order, new_order, collapsed in ((old_state[1], order, self.chatgpt_collapsed),
                                                        (old_state[3], free_order, self.chatgpt_free_collapsed)):
                    if collapsed:
                        continue
                    old_names = set(old_order)
                    for index, name in enumerate(new_order):
                        if name in old_names:
                            continue
                        next_card = next((widgets[next_name]['card'] for next_name in new_order[index + 1:]
                                          if next_name in old_names and widgets[next_name]['card'].winfo_manager()), None)
                        options = {'fill': 'x', 'padx': 1, 'pady': (0, 2)}
                        if next_card is not None:
                            options['before'] = next_card
                        widgets[name]['card'].pack(**options)
            else:
                for row in widgets.values():
                    row['card'].pack_forget()
                if not self.chatgpt_collapsed:
                    for name in order:
                        widgets[name]['card'].pack(fill='x', padx=1, pady=(0, 2))
                if not self.chatgpt_free_collapsed:
                    for name in free_order:
                        widgets[name]['card'].pack(fill='x', padx=1, pady=(0, 2))
            self._chatgpt_order = state
        self.place_quota_rest_stop(self.chatgpt_accounts, paid_rows, widgets, self.chatgpt_collapsed)
        self.place_quota_rest_stop(self.chatgpt_free_accounts, free_rows, widgets, self.chatgpt_free_collapsed)

    def place_quota_rest_stop(self, parent, accounts, rows, collapsed=False):
        separator = getattr(parent, 'quota_rest_separator', None)
        empty = [a for a in accounts if self.account_empty_quota(a)]
        if separator is None and empty:
            separator = ctk.CTkFrame(parent, fg_color='transparent', height=22)
            ctk.CTkFrame(separator, height=1, fg_color='#43516a').pack(fill='x', pady=(3, 2))
            ctk.CTkLabel(separator, text='Quota empty · rest stop', height=16,
                         font=('Segoe UI', 10), text_color=MUTED).pack(anchor='w', padx=4)
            parent.quota_rest_separator = separator
        if separator is None:
            return
        if not empty or collapsed:
            separator.pack_forget()
            return
        target = rows[empty[0]['name']]['card']
        if target.winfo_manager():
            packed = parent.pack_slaves()
            index = packed.index(target)
            if index == 0 or packed[index - 1] is not separator:
                separator.pack(fill='x', before=target, padx=1)

    @staticmethod
    def chatgpt_plan_name(item):
        plan = ((item.get('quota') or {}).get('plan_type') or item.get('plan_type') or
                (item.get('id_token') or {}).get('plan_type'))
        if not isinstance(plan, str) or not plan.strip():
            return 'Plan unknown'
        plan = plan.strip().lower()
        names = {'free': 'Free', 'plus': 'Plus', 'pro': 'Pro', 'team': 'Team',
                 'business': 'Business', 'enterprise': 'Enterprise', 'edu': 'Edu', 'go': 'Go'}
        return names.get(plan, plan.replace('_', ' ').title()[:32])

    def update_chatgpt_row(self, item):
        row = self.chatgpt_widgets[item['name']]
        row['heading'].configure(text=self.display_name(item, 'OpenAI'))
        self.update_pause_button(row['pause'], item.get('disabled'))
        status, severity, reason = account_status(item)
        if severity != 'error' and 'openai' in blocked_families(self.controller.preferences, item['name'], ChatGPTAuth.quota_limit_groups(item.get('quota') or {})):
            status, severity = 'Reserve reached', 'warning'
        row['plan'].configure(text=' ' + self.chatgpt_plan_name(item) + ' ')
        self.update_priority_counter(row['priority'], item)
        color = {'error': '#ff6b7a', 'warning': '#f7ca70', 'normal': GREEN, 'muted': MUTED}[severity]
        row['status'].configure(text=self.uptime_status(row['status'], item, f'{status} · {item.get("success") or 0} resp.'), text_color=color,
                                wraplength=0, justify='left')
        quota = item.get('quota') or {}
        keys = set()
        for window in quota.get('windows', []):
            key = window['label']
            keys.add(key)
            if key not in row['windows']:
                line = ctk.CTkFrame(row['windows_frame'], fg_color='transparent')
                line.pack(fill='x', padx=8, pady=(0, 2))
                label = ctk.CTkLabel(line, text='', width=75, height=15, anchor='w', font=('Segoe UI', 10))
                label.pack(side='left')
                bar = self.make_quota_limit_bar(line, item['name'], 'openai',
                    'weekly' if key == '1w' else '5h', width=75, height=6)
                bar.pack(side='left', padx=(1, 5))
                timer = ctk.CTkLabel(line, text='', height=15, anchor='e', font=('Segoe UI', 10), text_color=MUTED)
                timer.pack(side='right')
                row['windows'][key] = (line, label, bar, timer)
            line, label, bar, timer = row['windows'][key]
            if not line.winfo_manager():
                line.pack(fill='x', padx=8, pady=(0, 2))
            color = self.quota_color(window['remaining'] / 100)
            label.configure(text=f'{key} · {window["remaining"]:.0f}%', text_color=color)
            bar.configure(progress_color=color)
            bar.set(window['remaining'] / 100)
            bar.set_floor(quota_floor(self.controller.preferences, item['name'], 'openai', 'weekly' if key == '1w' else '5h'))
        for key, (line, *_) in row['windows'].items():
            if key not in keys:
                line.pack_forget()
        if keys and '5h' not in keys:
            if not row['missing_window'].winfo_manager():
                row['missing_window'].pack(fill='x', padx=8, pady=(0, 2), before=row['windows'][next(iter(keys))][0])
        else:
            row['missing_window'].pack_forget()
        if keys:
            if not row['windows_frame'].winfo_manager():
                row['windows_frame'].pack(fill='x', padx=6, pady=(0, 6), before=row['error'] if row['error'].winfo_manager() else None)
        else:
            row['windows_frame'].pack_forget()
        def show(widget, text=None, pady=(0, 2)):
            if text is not None:
                widget.configure(text=text)
            if not widget.winfo_manager():
                widget.pack(fill='x', padx=8, pady=pady)
        credits = quota.get('reset_credits') or len(quota.get('reset_options') or [])
        if isinstance(credits, (int, float)) and credits > 0:
            row['reset_button'].configure(text='')
            row['reset_row'].configure(width=18 * int(credits))
            if not row['reset_row'].winfo_manager():
                row['reset_row'].pack(side='right', padx=(0, 2))
        else:
            row['reset_row'].pack_forget()
        options = quota.get('reset_options') or []
        if options and not item.get('disabled'):
            expiry = min((entry['expires_at'] for entry in options if entry.get('expires_at')), default=None)
            details = 'One available usage reset'
            if expiry:
                details += ' · earliest expiry ' + self.activity_time(expiry)
            row['reset_details'].configure(text=details)
            row['reset_button'].configure(command=lambda account=item: self.confirm_chatgpt_reset(account),
                                          state='disabled' if self.busy else 'normal')
            if not row['reset_button'].winfo_manager():
                row['reset_button'].pack(side='left')
        else:
            row['reset_details'].place_forget()
            credits = quota.get('reset_credits')
            if options or isinstance(credits, (int, float)) and credits > 0:
                row['reset_button'].configure(state='disabled')
                if not row['reset_button'].winfo_manager():
                    row['reset_button'].pack(side='left')
                row['reset_details'].configure(text='Reset unavailable while the current quota window is full.'
                     if any(w.get('label') == '5h' and w.get('remaining') == 100 for w in quota.get('windows', []))
                     else 'OpenAI does not allow this reset right now.')
            else:
                row['reset_button'].pack_forget()
        count = int(credits) if isinstance(credits, (int, float)) and credits > 0 else 0
        while len(row['reset_buttons']) < count:
            button = self.button(row['reset_row'], '', lambda account=item: self.confirm_chatgpt_reset(account))
            button.configure(height=17, width=18, corner_radius=1, fg_color='transparent',
                             image=self.playback_icons['reset'], border_spacing=0)
            self.attach_tooltip(button, lambda r=row: r['reset_details'].cget('text'))
            row['reset_buttons'].append(button)
        for index, button in enumerate(row['reset_buttons']):
            if index < count:
                button.configure(text='', state=row['reset_button'].cget('state'),
                                 command=lambda account=item: self.confirm_chatgpt_reset(account),
                                 image=self.playback_icons['reset-rainbow'][0])
                if not button.winfo_manager():
                    button.pack(side='left')
            else:
                button.pack_forget()
        quota_error = quota.get('error') or ('Quota not loaded yet' if not quota.get('windows') and not item.get('disabled') else '')
        error = status_details(status, reason, quota_error)
        row['error'].configure(text_color=color if reason else MUTED, wraplength=230, justify='left')
        if error:
            show(row['error'], self.redact_private_text(error), pady=(0, 6))
        else:
            row['error'].pack_forget()
        self.update_chatgpt_countdowns(item)

    def update_chatgpt_countdowns(self, item):
        row = getattr(self, 'chatgpt_widgets', {}).get(item['name'])
        if not row:
            return
        for window in (item.get('quota') or {}).get('windows', []):
            widgets = row['windows'].get(window['label'])
            if not widgets:
                continue
            try:
                reset = datetime.fromtimestamp(window.get('reset_at'), timezone.utc).isoformat()
                countdown = self.time_until_reset(reset)
            except (ValueError, TypeError, OverflowError, OSError):
                countdown = '—'
            if widgets[3].cget('text') != countdown:
                widgets[3].configure(text=countdown)

    def toggle_chatgpt_accounts(self):
        self.chatgpt_collapsed = not self.chatgpt_collapsed
        self.controller.preferences['chatgpt-collapsed'] = self.chatgpt_collapsed
        self.controller.save()
        self.draw_chatgpt_accounts()
        self.refresh_api_accounts(use_cache=True)

    def toggle_chatgpt_free_accounts(self):
        self.chatgpt_free_collapsed = not self.chatgpt_free_collapsed
        self.controller.preferences['chatgpt-free-collapsed'] = self.chatgpt_free_collapsed
        self.controller.save()
        self.draw_chatgpt_accounts()
        self.refresh_api_accounts(use_cache=True)

    def confirm_chatgpt_reset(self, account):
        if self.busy:
            return
        email = self.display_name(account, 'OpenAI')
        details = 'ChatGPT will apply one available usage reset.'
        if not messagebox.askyesno('Use ChatGPT reset',
            f'Use one reset credit for {email}?\n\n{details}\n\nThis action cannot be undone.', parent=self):
            return
        def done(windows):
            self.notice.configure(text=f'ChatGPT usage reset applied for {self.display_name(account, "OpenAI")} ({windows} windows).',
                                  text_color=GREEN)
            self.refresh_chatgpt_accounts()
        self.work(lambda: ChatGPTAuth(self.controller).use_reset_credit(account),
                  done, mutation=True)

    def add_chatgpt_account(self):
        self.provider_login_menu('OpenAI')

    def import_chatgpt_file(self):
        path = filedialog.askopenfilename(parent=self, title='Choose ChatGPT auth.json',
                                          filetypes=[('JSON files', '*.json')])
        if not path:
            return
        def done(result):
            email, accounts = result
            self.chatgpt_collapsed = False
            self.controller.preferences['chatgpt-collapsed'] = False
            self.controller.save()
            self.set_chatgpt_accounts(accounts)
            account = next((item for item in accounts if item.get('email') == email), {'name': email, 'email': email})
            self.fetch_chatgpt_account_quota(account)
            self.notice.configure(text='ChatGPT account connected: ' + self.display_name(account, 'OpenAI') + '. Choose an available GPT model in your connected application.',
                                  text_color=GREEN)
            self.refresh_new_chatgpt_accounts()
        self.work(lambda: ChatGPTAuth(self.controller).import_file(path), done, mutation=True)

    def sign_in_chatgpt(self):
        if self.busy:
            return
        self.work(lambda: ChatGPTAuth(self.controller).begin_login(), self.chatgpt_login_started, mutation=True)

    def _activate_chatgpt_login(self, state):
        record = self.chatgpt_pending_store.get(state) if state else None
        if not record:
            self.pending_chatgpt_login = None
            self.chatgpt_login_url = None
            return
        age = max(0, time.time() - record['created_at'])
        self.pending_chatgpt_login = (state, time.monotonic() - age)
        self.chatgpt_login_url = record['url']

    def resume_chatgpt_login(self):
        records = self.chatgpt_pending_store.all()
        self.set_provider_login_buttons(True)
        if not records or self.closed:
            self._activate_chatgpt_login(None)
            return
        self._activate_chatgpt_login(records[0]['state'])
        self._show_chatgpt_login_window()
        self.chatgpt_callback_status.configure(
            text=f'{len(records)} ChatGPT sign-in attempt(s) are still active. Old callback links are accepted until they expire.',
            text_color=ACCENT)
        self.poll_chatgpt_login()

    def chatgpt_login_started(self, result):
        url, state = result
        self.chatgpt_pending_store.add(state, url)
        self._activate_chatgpt_login(state)
        # A previous accepted/failed login may have left the one-use callback
        # guard set while the gateway was waiting for OAuth confirmation.
        self.chatgpt_callback_busy = False
        self.set_provider_login_buttons(True)
        self.notice.configure(text='Copy the sign-in link or open it manually in your browser. The account will appear here automatically.',
                              text_color=ACCENT)
        self._show_chatgpt_login_window()

    def _show_chatgpt_login_window(self):
        if hasattr(self, 'chatgpt_login_window') and self.chatgpt_login_window.winfo_exists():
            self.chatgpt_login_window.destroy()
        self.chatgpt_login_window = ctk.CTkToplevel(self)
        self.chatgpt_login_window.title('ChatGPT sign-in')
        self.chatgpt_login_window.geometry('500x370')
        self.chatgpt_login_window.resizable(False, False)
        self.chatgpt_login_window.configure(fg_color=PANEL)
        self.chatgpt_login_window.transient(self)
        ctk.CTkLabel(self.chatgpt_login_window, text='Complete ChatGPT sign-in',
                     font=('Segoe UI', 21, 'bold'), text_color=TEXT).pack(pady=(22, 8))
        ctk.CTkLabel(self.chatgpt_login_window,
                     text='Sign in in any browser profile. If localhost is blocked,\ncopy the callback URL or authorization code back here.',
                     font=('Segoe UI', 12), text_color=MUTED, justify='center').pack(pady=(0, 8))
        link_controls = ctk.CTkFrame(self.chatgpt_login_window, fg_color='transparent')
        link_controls.pack(pady=(0, 8))
        self.button(link_controls, 'Open browser', lambda: webbrowser.open(self.chatgpt_login_url)).pack(side='left', padx=(0, 6))
        self.chatgpt_copy_link_button = self.button(link_controls, 'Copy sign-in link', self.copy_chatgpt_login_link)
        self.chatgpt_copy_link_button.pack(side='left')
        ctk.CTkLabel(self.chatgpt_login_window, text='Paste the full callback address or enter only the code:',
                     font=('Segoe UI', 11), text_color=MUTED).pack(pady=(0, 3))
        callback_row = ctk.CTkFrame(self.chatgpt_login_window, fg_color='transparent')
        callback_row.pack(fill='x', padx=20, pady=(0, 6))
        self.chatgpt_callback_entry = ctk.CTkEntry(callback_row,
            placeholder_text='http://localhost:1455/auth/callback?... or code', height=30)
        self.chatgpt_callback_entry.pack(side='left', fill='x', expand=True)
        self.chatgpt_paste_callback_button = self.button(callback_row, 'Paste', self.paste_chatgpt_callback)
        self.chatgpt_paste_callback_button.configure(width=58, height=30)
        self.chatgpt_paste_callback_button.pack(side='right', padx=(6, 0))
        self.chatgpt_callback_entry.bind('<Control-KeyPress>', self.chatgpt_callback_paste_key, add='+')
        self.chatgpt_callback_entry.bind('<Return>', lambda _: self.submit_chatgpt_callback())
        self.chatgpt_callback_button = self.button(self.chatgpt_login_window, 'Complete sign-in', self.submit_chatgpt_callback)
        self.chatgpt_callback_button.configure(height=28)
        self.chatgpt_callback_button.pack(pady=(0, 5))
        self.chatgpt_callback_status = ctk.CTkLabel(self.chatgpt_login_window, text='Waiting for sign-in…',
                     text_color=MUTED, font=('Segoe UI', 11), wraplength=460)
        self.chatgpt_callback_status.pack(fill='x', padx=20, pady=(0, 3))
        self.button(self.chatgpt_login_window, 'Cancel sign-in', self.cancel_chatgpt_login).pack()
        self.after(1800, self.poll_chatgpt_login)

    def copy_chatgpt_login_link(self):
        if getattr(self, 'chatgpt_login_url', None):
            self.clipboard_clear()
            self.clipboard_append(self.chatgpt_login_url)
            self.chatgpt_callback_status.configure(text='Link copied. Open it in your browser profile.', text_color=GREEN)

    def submit_chatgpt_callback(self):
        if not self.pending_chatgpt_login or getattr(self, 'chatgpt_callback_busy', False):
            return
        value = self.chatgpt_callback_entry.get().strip()
        if not value:
            self.chatgpt_callback_status.configure(text='Paste the callback address or authorization code.', text_color='#ffbd93')
            return
        callback_state = ChatGPTAuth.callback_state(value)
        state = callback_state or self.pending_chatgpt_login[0]
        if not callback_state and not self.chatgpt_pending_store.get(state):
            self.chatgpt_callback_status.configure(
                text='This callback does not match a saved active sign-in, or that sign-in has expired.',
                text_color='#ffbd93')
            return
        self.chatgpt_callback_busy = True
        self.chatgpt_callback_button.configure(state='disabled')
        self.chatgpt_callback_status.configure(text='Completing sign-in…', text_color=MUTED)
        def submit():
            try:
                return ChatGPTAuth(self.controller).complete_login(value, state), None
            except AccountError as error:
                return None, str(error)
        def done(result):
            answer, error = result
            if error:
                self.chatgpt_callback_busy = False
                self.chatgpt_callback_status.configure(text=error, text_color='#ffbd93')
                self.chatgpt_callback_button.configure(state='normal')
            else:
                if not self.chatgpt_pending_store.get(state):
                    # The gateway is authoritative for older attempts created
                    # before Omni began persisting pending states.
                    self.chatgpt_pending_store.add(state, '')
                    self._activate_chatgpt_login(state)
                self.chatgpt_callback_entry.delete(0, 'end')
                self.chatgpt_callback_status.configure(text='Code accepted. Waiting for ChatGPT confirmation…', text_color=GREEN)
                self.after(1800, self.poll_chatgpt_login)
        self.work(submit, done)

    def chatgpt_callback_paste_key(self, event):
        if event.keycode == 86 or str(event.keysym).lower() == 'v':
            self.paste_chatgpt_callback()
            return 'break'

    def paste_chatgpt_callback(self):
        if getattr(self, 'chatgpt_callback_busy', False):
            return
        try:
            value = self.clipboard_get().strip()
        except tk.TclError:
            self.chatgpt_callback_status.configure(text='Clipboard is empty or unavailable.', text_color='#ffbd93')
            return
        self.chatgpt_callback_entry.delete(0, 'end')
        self.chatgpt_callback_entry.insert(0, value)
        self.chatgpt_callback_entry.focus_set()
        self.chatgpt_callback_status.configure(text='Callback pasted. Click Complete sign-in.', text_color=TEXT)

    def poll_chatgpt_login(self):
        if self.closed:
            return
        records = self.chatgpt_pending_store.all()
        if not records:
            had_pending = bool(self.pending_chatgpt_login)
            self._activate_chatgpt_login(None)
            if had_pending:
                self.chatgpt_callback_busy = False
                if hasattr(self, 'chatgpt_login_window') and self.chatgpt_login_window.winfo_exists():
                    self.chatgpt_login_window.destroy()
                self.set_provider_login_buttons(True)
                self.notice.configure(text='The saved ChatGPT sign-in link expired. Start a new sign-in.',
                                      text_color='#ffbd93')
            return
        record = next((row for row in records if row['state'] not in self.chatgpt_login_polling), None)
        if not record:
            self.after(1800, self.poll_chatgpt_login)
            return
        state = record['state']
        self.chatgpt_login_polling.add(state)
        def poll():
            try:
                return ChatGPTAuth(self.controller).login_status(state)
            except AccountError:
                return {'status': 'wait'}
        def done(result):
            self.chatgpt_login_polling.discard(state)
            if not self.chatgpt_pending_store.get(state):
                return
            if result.get('status') == 'ok':
                self.finish_chatgpt_login('ChatGPT account added. Reconnect applications to show its GPT models.', True, state)
            elif result.get('status') == 'error':
                self.finish_chatgpt_login('ChatGPT sign-in did not finish. Try again.', False, state)
            else:
                self.after(1800, self.poll_chatgpt_login)
        self.work(poll, done)

    def cancel_chatgpt_login(self):
        if not self.pending_chatgpt_login:
            return
        state = self.pending_chatgpt_login[0]
        self.finish_chatgpt_login('ChatGPT sign-in cancelled.', False, state)
        self.work(lambda: ChatGPTAuth(self.controller).cancel_login(state), lambda _: None)

    def finish_chatgpt_login(self, message, success, state=None):
        state = state or (self.pending_chatgpt_login[0] if self.pending_chatgpt_login else None)
        if state:
            self.chatgpt_pending_store.remove(state)
        self.chatgpt_callback_busy = False
        remaining = self.chatgpt_pending_store.all()
        self._activate_chatgpt_login(remaining[0]['state'] if remaining else None)
        self.set_provider_login_buttons(True)
        if remaining and hasattr(self, 'chatgpt_login_window') and self.chatgpt_login_window.winfo_exists():
            self.chatgpt_login_window.destroy()
            self._show_chatgpt_login_window()
            outcome = self.ui_style.text('ChatGPT account added.' if success else 'This ChatGPT sign-in did not finish.')
            pending = self.ui_style.text('Active sign-in attempts remaining: ')
            self.chatgpt_callback_status.configure(text=f'{outcome} {pending}{len(remaining)}', text_color=ACCENT)
            self.after(1800, self.poll_chatgpt_login)
        elif hasattr(self, 'chatgpt_login_window') and self.chatgpt_login_window.winfo_exists():
            self.chatgpt_login_window.destroy()
        self.notice.configure(text=message, text_color=GREEN if success else '#ffbd93')
        if success:
            self.chatgpt_collapsed = False
            self.controller.preferences['chatgpt-collapsed'] = False
            self.controller.save()
            self.refresh_new_chatgpt_accounts()

    def provider_visible(self, provider):
        return self.visible_services.get(provider, True)

    def google_visible(self):
        return self.provider_visible('gemini')

    def apply_service_visibility(self):
        if not hasattr(self, 'google_accounts_header'):
            return
        if self.google_visible():
            if not self.google_accounts_header.winfo_manager():
                self.google_accounts_header.pack(fill='x', padx=1, pady=(0, 2), after=self.sidebar_spacer)
            if not self.google_accounts_collapsed:
                if not self.google_accounts_content.winfo_manager():
                    self.google_accounts_content.pack(fill='x', after=self.google_accounts_header)
            else:
                self.google_accounts_content.pack_forget()
        else:
            self.google_accounts_header.pack_forget()
            self.google_accounts_content.pack_forget()
        self.show_quota_dots(self.google_compact, self.google_visible() and self.google_accounts_collapsed,
                             after=self.google_accounts_header)
        for provider, group in getattr(self, 'pool_summary_groups', {}).items():
            visible = self.provider_visible('gemini') if provider == 'google' else self.provider_visible('claude' if provider=='claude-native' else provider)
            if visible and not group['frame'].winfo_manager():
                anchor = self.pool_summary_groups.get('openai', {}).get('frame') if provider == 'google' else None
                if anchor is None or not anchor.winfo_manager():
                    anchor = self.tokenharbor_accounts if self.tokenharbor_accounts.winfo_manager() else None
                group['frame'].pack(fill='x', padx=18, pady=(0, 3), before=anchor)
            elif not visible:
                group['frame'].pack_forget()
        if self.provider_visible('tokenharbor'):
            if not self.tokenharbor_accounts.winfo_manager():
                self.tokenharbor_accounts.pack(fill='x', padx=12, pady=(3, 5))
        else:
            self.tokenharbor_accounts.pack_forget()
        if not self.provider_visible('openai'):
            self.chatgpt_accounts.pack_forget()

    def draw_display_settings(self):
        self.label(self.display_settings, 'Display settings', 22, bold=True)
        self.label(self.display_settings, 'Visible services', 16, bold=True)
        self.service_variables = {}
        for provider, title in [('gemini', 'Gemini'), ('claude', 'Claude'), ('openai', 'OpenAI'), ('grok', 'Grok'), ('tokenharbor', 'TokenHarbor')]:
            variable = tk.BooleanVar(master=self, value=self.provider_visible(provider))
            self.service_variables[provider] = variable
            control = ctk.CTkCheckBox(self.display_settings, text=title, variable=variable,
                                     command=lambda kind=provider: self.set_service_visibility(kind))
            control.pack(anchor='w', pady=6)
        self.label(self.display_settings, 'Hidden services remain available for routing.', 12, MUTED)
        self.label(self.display_settings, 'Theme', 16, bold=True)
        self.theme_control = ctk.CTkSegmentedButton(self.display_settings, values=['Dark', 'Light'], command=self.set_theme)
        self.theme_control.set(self.ui_style.theme.title())
        self.theme_control.pack(anchor='w', pady=(0, 14))
        self.label(self.display_settings, 'Language', 16, bold=True)
        self.language_control = ctk.CTkSegmentedButton(self.display_settings, values=['English', 'Русский'], command=self.set_language)
        self.language_control.set('Русский' if self.ui_style.language == 'ru' else 'English')
        self.language_control.pack(anchor='w', pady=(0, 14))
        self.label(self.display_settings, 'Telegram notifications', 16, bold=True)
        self.telegram_enabled = tk.BooleanVar(master=self, value=bool(self.controller.preferences.get('telegram-alerts-enabled', False)))
        self.telegram_enabled_control = ctk.CTkCheckBox(self.display_settings, text='Notify me when an account fails',
            variable=self.telegram_enabled, command=self.save_telegram_preferences)
        self.telegram_enabled_control.pack(anchor='w', pady=(0, 7))
        self.telegram_token_entry = ctk.CTkEntry(self.display_settings, width=340, placeholder_text='Telegram bot token', show='•')
        self.telegram_token_entry.pack(anchor='w', pady=(0, 6))
        token_saved = self.telegram_bot.token_saved()
        self.telegram_token_state = self.label(self.display_settings,
            'Bot token saved securely' if token_saved else 'Bot token not set', 11, MUTED)
        self.telegram_chat_entry = ctk.CTkEntry(self.display_settings, width=340, placeholder_text='Telegram chat ID')
        self.telegram_chat_entry.insert(0, str(self.controller.preferences.get('telegram-chat-id', '')))
        self.telegram_chat_entry.pack(anchor='w', pady=(0, 7))
        self.telegram_chat_entry.bind('<FocusOut>', lambda event: self.save_telegram_preferences())
        self.telegram_chat_entry.bind('<Return>', lambda event: self.save_telegram_preferences())
        telegram_actions = ctk.CTkFrame(self.display_settings, fg_color='transparent')
        telegram_actions.pack(anchor='w', pady=(0, 4))
        self.button(telegram_actions, 'Save bot token', self.save_telegram_token).pack(side='left', padx=(0, 6))
        self.button(telegram_actions, 'Find chat', self.find_telegram_chat).pack(side='left', padx=(0, 6))
        self.button(telegram_actions, 'Send test', self.test_telegram).pack(side='left')
        self.telegram_status_label = self.label(self.display_settings,
            'Send /start to your bot, then select Find chat.', 11, MUTED)

    def save_telegram_preferences(self):
        self.controller.preferences['telegram-alerts-enabled'] = bool(self.telegram_enabled.get())
        self.controller.preferences['telegram-chat-id'] = self.telegram_chat_entry.get().strip()
        self.controller.save()

    def save_telegram_token(self):
        token = self.telegram_token_entry.get().strip()
        if not token:
            self.telegram_status_label.configure(text='Enter the bot token first.', text_color='#f7ca70')
            return
        try:
            self.telegram_bot.save_token(token)
        except TelegramError as error:
            self.telegram_status_label.configure(text=str(error), text_color='#ffbd93')
            return
        self.telegram_token_entry.delete(0, 'end')
        self.telegram_token_state.configure(text='Bot token saved securely', text_color=GREEN)
        self.save_telegram_preferences()
        self.telegram_status_label.configure(text='Bot token saved.', text_color=GREEN)

    def find_telegram_chat(self):
        self.save_telegram_preferences()
        def done(chat_id):
            self.telegram_chat_entry.delete(0, 'end')
            self.telegram_chat_entry.insert(0, str(chat_id))
            self.save_telegram_preferences()
            self.telegram_status_label.configure(text='Chat found and saved.', text_color=GREEN)
        self.telegram_status_label.configure(text='Looking for a recent message to the bot…', text_color=ACCENT)
        def find():
            try:
                return self.telegram_bot.discover_chat_id(), None
            except TelegramError as error:
                return None, str(error)
        def complete(result):
            chat_id, error = result
            if error:
                self.telegram_status_label.configure(text=error, text_color='#ffbd93')
            else:
                done(chat_id)
        self.work(find, complete)

    def test_telegram(self):
        self.save_telegram_preferences()
        chat_id = self.telegram_chat_entry.get().strip()
        def send():
            self.telegram_bot.send_message(chat_id, 'Omni: Telegram notifications are connected.')
        def done(_):
            self.telegram_status_label.configure(text='Test message sent.', text_color=GREEN)
        self.telegram_status_label.configure(text='Sending test message…', text_color=ACCENT)
        def guarded():
            try:
                return send(), None
            except TelegramError as error:
                return None, str(error)
        def complete(result):
            _, error = result
            if error:
                self.telegram_status_label.configure(text=error, text_color='#ffbd93')
            else:
                done(None)
        self.work(guarded, complete)

    def observe_account_statuses(self, provider, accounts, suppress=False):
        """Notify once when a known healthy account first enters a hard-error state."""
        if self.closed:
            return
        key = 'telegram-account-statuses'
        states = self.controller.preferences.setdefault(key, {})
        is_initial = provider not in self._telegram_status_initialized
        self._telegram_status_initialized.add(provider)
        changed = False
        for account in accounts:
            name = account.get('name')
            if not name:
                continue
            status, severity, detail = account_status(account)
            state_key = provider + ':' + name
            previous = states.get(state_key)
            if provider == 'gemini' and 'quota' not in account and previous == 'error' and severity != 'error':
                continue
            problem = severity == 'error' or status in ('Verification required', 'Temporarily unavailable', 'Access denied')
            next_state = 'error' if problem else severity
            states[state_key] = next_state
            changed = changed or previous != next_state
            if problem and previous != 'error' and not is_initial and not suppress:
                self.send_telegram_account_alert(provider, account, status, detail)
        if changed and states != getattr(self, '_telegram_saved_statuses', None):
            self._telegram_saved_statuses = copy.deepcopy(states)
            self.controller.save()

    def send_telegram_account_alert(self, provider, account, status, detail=''):
        if (not self.controller.preferences.get('telegram-alerts-enabled')
                or not self.controller.preferences.get('telegram-chat-id')
                or not self.telegram_bot.token_saved()):
            return
        service = provider.removeprefix('api-')
        providers = {'gemini': 'Antigravity', 'openai': 'OpenAI', 'claude': 'Claude', 'grok': 'Grok'}
        title = providers.get(service, service.upper() if service == 'api' else service)
        name = self.display_name(account, title)
        from ui_locale import translate
        language = self.controller.preferences.get('language', 'en')
        caption = translate(status, language)
        text = f'⚠️ Omni: {title} · {name} — {caption}.'
        if detail:
            text += '\n' + safe_detail(detail)[:500]
        chat_id = str(self.controller.preferences.get('telegram-chat-id', '')).strip()
        def send():
            for attempt in range(3):
                try:
                    self.telegram_bot.send_message(chat_id, text)
                    return
                except TelegramError:
                    if attempt < 2:
                        time.sleep(3)
            self.mailbox.put((lambda _: self.telegram_status_label.configure(
                text='Could not send Telegram notification. Check bot settings.', text_color='#ffbd93'), None, None, False))
        threading.Thread(target=send, daemon=True).start()

    def set_service_visibility(self, provider):
        self.visible_services[provider] = bool(self.service_variables[provider].get())
        self.controller.preferences['visible-services'] = self.visible_services
        self.controller.save()
        self.apply_service_visibility()
        self.draw_account_list()
        self.draw_chatgpt_accounts()
        self.claude_panel.render()
        self.grok_panel.render()
        self.refresh_api_accounts(use_cache=True)
        if hasattr(self, 'rename_entry') and self.rename_entry.winfo_exists():
            unsaved_label = self.rename_entry.get()
            self.draw_detail()
            self.rename_entry.delete(0, 'end')
            self.rename_entry.insert(0, unsaved_label)

    def set_theme(self, value):
        theme = 'light' if value == 'Light' else 'dark'
        self.controller.preferences['theme'] = theme
        self.controller.save()
        self.theme_control.set(theme.title())
        self.ui_style.apply(theme=theme)
        for name in self.account_widgets:
            self.update_countdown(name)

    def set_language(self, value):
        language = 'ru' if value == 'Русский' else 'en'
        self.controller.preferences['language'] = language
        self.controller.save()
        self.language_control.set(value)
        self.ui_style.apply(language=language)
        self.render_token_capacity()
        self.journal_content = None
        self.render_activity()

    def google_plan_name(self, account):
        plan = self.quota_cache.get(account['name'], {}).get('data', {}).get('subscription') or account.get('subscription')
        return plan if isinstance(plan, str) and plan else 'Plan unknown'

    def change_view(self, value):
        self.detail.pack_forget()
        self.stats_view.pack_forget()
        self.display_settings.pack_forget()
        view = {'Routing statistics': self.stats_view, 'Display settings': self.display_settings}.get(value, self.detail)
        view.pack(fill='both', expand=True, before=self.notice)

    def check_for_updates(self):
        from updater import check_update
        self.update_button.configure(state='disabled', text='Checking updates…')
        def done(release):
            self.available_update = release
            self.update_button.configure(state='normal', text='Update to ' + release['version'] if release else 'Up to date · check again',
                command=self.install_update if release else self.check_for_updates)
        self.work(check_update, done)
        self.after(30000, lambda: self.update_button.configure(state='normal') if not self.closed else None)

    def install_update(self):
        if not self.available_update:
            return
        from updater import download_update
        self.update_button.configure(state='disabled', text='Downloading update…')
        def downloaded(path):
            self.pending_update = path
            self.apply_pending_update()
        self.work(lambda: download_update(self.controller, self.available_update), downloaded)
        self.after(180000, lambda: self.update_button.configure(state='normal') if not self.closed and not self.pending_update else None)

    def apply_pending_update(self):
        if self.closed or not self.pending_update:
            return
        # Do not trust the controller's error fallback as proof of an idle gateway.
        import json
        import urllib.request
        def idle():
            request = urllib.request.Request('http://127.0.0.1:8317/v0/management/quota-wait',
                headers={'Authorization':'Bearer ' + self.controller.key})
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return not json.load(response).get('jobs')
            except OSError:
                return False
        def done(is_idle):
            if is_idle and not self.busy and not self.pending_login and not self.pending_chatgpt_login and not self.pending_claude_login:
                from updater import launch_update
                launch_update(self.controller, self.pending_update)
                self.update_button.configure(text='Installing and restarting…')
                self.after(30000, lambda: self.update_button.configure(state='normal', text='Retry update', command=self.install_update) if not self.closed else None)
            else:
                self.update_button.configure(text='Update ready · waiting for requests…')
                self.after(5000, self.apply_pending_update)
        self.work(idle, done)

    def send_diagnostic_log(self):
        from gateway_diagnostics import send_diagnostics, DEFAULT_ENDPOINT, read_upload_token, save_upload_token
        endpoint = self.controller.preferences.get('diagnostics-endpoint') or DEFAULT_ENDPOINT
        if not endpoint:
            dialog = ctk.CTkInputDialog(text='HTTPS diagnostic upload endpoint:', title='Diagnostic recipient')
            endpoint = dialog.get_input()
        if not endpoint:
            return
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            messagebox.showerror('Invalid recipient', 'Use an HTTPS URL without embedded credentials.', parent=self)
            return
        token = read_upload_token(self.controller, endpoint)
        if not token:
            token = simpledialog.askstring('Diagnostic upload access',
                'Upload access token for ' + parsed.hostname + ':', show='*', parent=self)
            if not token:
                return
        if not messagebox.askyesno('Send diagnostic log?',
            'Recipient: ' + endpoint + '\n\nThe ZIP contains request phases, models, errors, timings, account cooldowns and active requests. '
            'Email addresses are replaced with account labels. Prompts, generated text, passwords and authentication tokens are excluded. '
            '\n\nSend this diagnostic archive now? No automatic uploads will be enabled.', parent=self):
            return
        save_upload_token(self.controller, endpoint, token.strip())
        self.controller.preferences['diagnostics-endpoint'] = endpoint
        self.controller.save()
        self.work(lambda: send_diagnostics(self.controller, endpoint),
            lambda status: messagebox.showinfo('Diagnostic log sent', 'Server accepted the archive (HTTP ' + str(status) + ').', parent=self))

    def save_diagnostic_log(self):
        from gateway_diagnostics import export_diagnostics
        destination = filedialog.asksaveasfilename(parent=self, title='Save diagnostic log',
            initialfile='GeminiAccounts-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip',
            defaultextension='.zip', filetypes=[('Diagnostic archive', '*.zip')])
        if destination:
            self.work(lambda: export_diagnostics(self.controller, destination),
                lambda path: messagebox.showinfo('Diagnostic log saved', str(path), parent=self))

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
        chatgpt_accounts = copy.deepcopy(self.chatgpt_items + self.claude_items + self.grok_items + [a for a in self.api_items if a.get('auth_index')])
        def fetch():
            try:
                accounts, records, strategy = self.controller.activity_snapshot()
                self.harbor_activity.observe(records, TokenHarbor(self.controller, self.integrations).auth_keys())
                self.activity.ingest(records, accounts + chatgpt_accounts)
                with self.controller.quota_start_lock:
                    probes = copy.deepcopy(self.controller.quota_starts)
                state = self.activity.ingest_probes(accounts + chatgpt_accounts, probes)
                return accounts, copy.deepcopy(state), strategy, None, self.controller.quota_wait_status()
            except Exception:
                return None, None, None, 'Cannot reach the proxy. Showing cached data.', {'jobs': []}
        def done(result):
            self.activity_busy = False
            accounts, state, strategy, error, quota_wait = result
            if error:
                self.stats_strategy.configure(text=error, text_color='#ffbd93')
            else:
                self.items = accounts
                self.observe_account_statuses('gemini', accounts)
                self.activity_state = state
                self.recent_account_models = self.latest_models_by_account(state)
                self.activity_strategy = strategy
                self.render_activity()
                self.draw_account_list()
                self.draw_chatgpt_accounts()
                self.update_tokenharbor_status()
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
                        if latest['name'] in {item['name'] for item in self.items}:
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
        latest = sorted((event for event in self.activity_state['latest'].values()
                         if event['name'] in {account['name'] for account in self.items}),
                        key=lambda e: e['at'], reverse=True)
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
        rows = rank_accounts(self.items, self.quota_cache, group,
                             priorities=self.controller.preferences.get('account-priorities', {}))
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
            self.render_policy_rows()
            self.mode_note.configure(text=f'Earliest-reset priority • {title}. Quotas and errors are handled automatically.')
        self.work(apply, done)

    def render_policy_rows(self):
        if not self.policy_rows:
            return
        title = 'Gemini' if self.policy_group == 'gemini' else 'Claude / GPT'
        names = {a['name']: self.display_name(a) for a in self.items}
        lines = [f'Account ranking for {title} • recalculated after quota updates.']
        for index, row in enumerate(self.policy_rows, 1):
            reset = ' • ' + self.activity_time(row['reset']) if row['reset'] else ''
            name = names.get(row['name']) or self.display_name({'name': row['name']})
            lines.append(f"{index}. {name} — {row['reason']}{reset}")
        lines.append('Proxy priorities are calculated for this group. The last ranking remains active after the application closes.')
        self.policy_label.configure(text=self.redact_private_text('\n'.join(lines)), text_color=MUTED)

    @staticmethod
    def activity_time(value):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().strftime('%d.%m %H:%M:%S')
        except (ValueError, AttributeError):
            return 'Time unknown'

    def render_activity(self):
        self.update_mode_label()
        self.tick_account_uptimes()
        state = self.activity_state
        by_name = {a['name']: a for a in self.items + self.chatgpt_items + self.claude_items + self.grok_items}
        def name(key):
            return self.display_name(by_name[key]) if key in by_name else (
                self.private_account_name('Account', key) if self.hide_account_names and key else key or 'Unknown account')
        strategy = getattr(self, 'activity_strategy', 'unknown')
        text = ('Earliest-reset priority • ' + ('Gemini' if self.policy_group == 'gemini' else 'Claude / GPT')) if self.policy_rows else 'Fill one account first → switch when unavailable' if strategy == 'fill-first' else 'Round-robin accounts' if strategy == 'round-robin' else 'Strategy: ' + strategy
        enabled = sum(not a.get('disabled') for a in self.routing_accounts())
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
        for account in self.items + self.chatgpt_items + self.claude_items + self.grok_items + self.api_items:
            key = account['name']
            if key not in self.activity_rows:
                self.activity_rows[key] = self.label(self.stats_accounts, '', 13)
            own = stats.get(key, {})
            count = own.get('success', 0) + own.get('failed', 0)
            average = own.get('latency_ms', 0) / count / 1000 if count else 0
            status = 'Paused' if account['disabled'] else (account.get('restriction_reason') or 'Waiting / restricted') if account.get('unavailable') or account.get('cooldowns') else 'Available'
            retries = []
            for cooldown in account.get('cooldowns') or []:
                try:
                    retry = datetime.fromisoformat(cooldown['retry_at'].replace('Z', '+00:00'))
                    if retry > datetime.now(timezone.utc):
                        retries.append(retry)
                except (KeyError, ValueError, TypeError, AttributeError):
                    pass
            if retries:
                status += ' • next provider retry in ' + self.time_until_reset(min(retries).isoformat())
            self.activity_rows[key].configure(text=f"{name(key)} • {status}\nProxy since startup: {account.get('success') or 0} successful / {account.get('failed') or 0} errors\nObserved: {count} attempts • {own.get('tokens', 0):,} tokens • average {average:.1f} s" + (' • last ' + self.activity_time(own['last']) if own.get('last') else ''))
        mode = self.journal_filter.get()
        events = [e for e in state['events'] if mode == 'All events' or (mode == 'Switches' and e['switch']) or (mode == 'Errors' and e['failed'])]
        lines = []
        for e in reversed(events[-100:]):
            title = 'PING' if e.get('probe') else 'SWITCH' if e['switch'] else 'ERROR' if e['failed'] else 'RESPONSE'
            route = (name(e['from']) + ' → ' if e['from'] else '') + name(e['name'])
            detail = e['reason'] if e.get('probe') else f"{e['reason']} • {e['latency_ms'] / 1000:.1f} s • {e['tokens']:,} tokens"
            lines.append(f"{self.activity_time(e['at'])} • {title}\n{route} • {model_name(e.get('upstream_model') or e['model'], self.model_aliases)}\n{detail}\n")
        content = self.ui_style.text(self.redact_private_text('\n'.join(lines))) or 'No events yet. New requests will appear automatically.'
        if getattr(self, 'journal_content', None) != content:
            scroll = self.stats_journal.yview()[0]
            self.stats_journal.configure(state='normal')
            self.stats_journal.delete('1.0', 'end')
            self.stats_journal.insert('1.0', content)
            self.stats_journal.configure(state='disabled')
            self.stats_journal.yview_moveto(scroll)
            self.journal_content = content
        self.stats_observed.configure(text='Monitoring since ' + self.activity_time(state['since']) + ' (local time). The log persists after closing; monitoring runs while the application is open. The latest 2000 events are kept.')

    def draw_tokenharbor_accounts(self):
        """Show configured TokenHarbor keys beside Google accounts."""
        frame = getattr(self, 'tokenharbor_accounts', None)
        if frame is None:
            return
        if not self.provider_visible('tokenharbor'):
            frame.pack_forget()
            return
        client = TokenHarbor(self.controller, self.integrations)
        keys = client.keys()
        signature = (tuple(keys), tuple(client.paused_keys()), self.tokenharbor_collapsed, self.provider_api_count('tokenharbor'))
        if getattr(self, '_tokenharbor_key_signature', None) == signature and frame.winfo_children():
            self.update_tokenharbor_names()
            return
        self._tokenharbor_key_signature = signature
        for child in frame.winfo_children():
            child.destroy()
        self.tokenharbor_widgets = []
        self.tokenharbor_rows = {}
        self.tokenharbor_name_widgets = {}
        header = self.button(frame, ('▸' if self.tokenharbor_collapsed else '▾') +
            f'  TokenHarbor · {len(keys)+self.provider_api_count("tokenharbor")}pcs', self.toggle_tokenharbor_accounts)
        header.configure(height=28, anchor='w', font=('Segoe UI', 11, 'bold'), fg_color='#303b50')
        header.pack(fill='x', padx=1, pady=(2, 3))
        self.tokenharbor_header = header
        self.install_service_add_button(header, 'tokenharbor')
        self.tokenharbor_compact = self.make_quota_dots(header, ('',))
        self.set_quota_dots(self.tokenharbor_compact, [None])
        self.show_quota_dots(self.tokenharbor_compact, self.tokenharbor_collapsed, after=header)
        if self.tokenharbor_collapsed:
            return
        self.tokenharbor_last = ctk.CTkLabel(frame, text='', height=17,
            anchor='w', font=('Segoe UI', 10), text_color=MUTED)
        self.tokenharbor_last.pack(fill='x', padx=8, pady=(0, 3))
        if not keys:
            ctk.CTkLabel(frame, text='No TokenHarbor keys connected', height=17,
                anchor='w', font=('Segoe UI', 10), text_color=MUTED).pack(fill='x', padx=8, pady=(0, 3))
        for key in keys:
            card = ctk.CTkFrame(frame, fg_color='#202938', corner_radius=8, border_width=1, border_color='#344155')
            card.pack(fill='x', padx=1, pady=(0, 2))
            heading_row = ctk.CTkFrame(card, fg_color='transparent')
            heading_row.pack(fill='x', padx=8, pady=(3, 0))
            heading = ctk.CTkLabel(heading_row, text='', localize=False, height=20,
                anchor='w', font=('Segoe UI', 11), text_color=TEXT)
            heading.pack(side='left', fill='x', expand=True)
            self.bind_account_rename(heading, key_id(key), 'TokenHarbor')
            pause = self.account_pause_button(heading_row, key_id(key), 'tokenharbor')
            self.update_pause_button(pause, key in client.paused_keys())
            pause.pack(side='right')
            self.tokenharbor_name_widgets[key_id(key)] = (heading, key_label(key))
            status = ctk.CTkLabel(card, text='', height=17,
                anchor='w', font=('Segoe UI', 10), text_color=MUTED)
            status.pack(fill='x', padx=8, pady=(0, 3))
            self.tokenharbor_widgets.append(card)
            self.tokenharbor_rows[key_id(key)] = (card, status)
        self.update_tokenharbor_names()
        self.update_tokenharbor_status()
        self.refresh_api_accounts(use_cache=True)

    def update_tokenharbor_names(self):
        for fingerprint, (heading, label) in getattr(self, 'tokenharbor_name_widgets', {}).items():
            name = self.private_account_name('TokenHarbor', fingerprint) if self.hide_account_names else self.controller.preferences.get('labels', {}).get(fingerprint) or label
            heading.configure(text='●  ' + name)

    def update_tokenharbor_status(self):
        if self.tokenharbor_collapsed or not getattr(self, 'tokenharbor_rows', None):
            return
        latest = self.harbor_activity.state.get('latest') or {}
        last_name = self.private_account_name('TokenHarbor', latest.get('key_id', 'unknown')) if latest and self.hide_account_names else latest.get('label', '')
        self.tokenharbor_last.configure(text='Last used: ' + last_name if latest else
                                        'Key in use is identified after a response')
        for fingerprint, (card, label) in self.tokenharbor_rows.items():
            event = self.harbor_activity.state.get('keys', {}).get(fingerprint)
            if not event:
                line, color = 'No requests recorded · balance unknown', MUTED
            else:
                try:
                    at = datetime.fromisoformat(event['at'].replace('Z', '+00:00')).astimezone().strftime('%H:%M')
                except (TypeError, ValueError, KeyError, AttributeError):
                    at = '—'
                if event.get('status') == 429:
                    line, color = f'429 at {at} · limit hit · reset unknown', '#ffbd93'
                elif event.get('failed'):
                    line, color = f'Error {event.get("status") or "?"} at {at} · balance unknown', '#ffbd93'
                else:
                    line, color = f'OK at {at} · balance/reset in dashboard', MUTED
            line = self.uptime_status(label, {'name': fingerprint, 'status': 'active',
                'status_message': json.dumps({'error': {'code': event.get('status')}}) if event and event.get('status') in (401, 403) else ''}, line)
            if label.cget('text') != line:
                label.configure(text=line, text_color=color)
            active = latest.get('key_id') == fingerprint
            desired = ACCENT if active else '#344155'
            if card.cget('border_color') != desired:
                card.configure(border_color=desired)

    def toggle_tokenharbor_accounts(self):
        self.tokenharbor_collapsed = not self.tokenharbor_collapsed
        self.controller.preferences['tokenharbor-collapsed'] = self.tokenharbor_collapsed
        self.controller.save()
        self.draw_tokenharbor_accounts()
        self.refresh_api_accounts(use_cache=True)

    def toggle_google_accounts(self):
        self.google_accounts_collapsed = not self.google_accounts_collapsed
        self.controller.preferences['google-accounts-collapsed'] = self.google_accounts_collapsed
        self.controller.save()
        self.apply_service_visibility()
        self.draw_account_list()
        self.refresh_api_accounts(use_cache=True)

    def draw_account_list(self):
        self.google_accounts_header.configure(text=('▸' if self.google_accounts_collapsed else '▾') +
                                             f'  Antigravity · {len(self.items)+self.provider_api_count("gemini")}pcs')
        self.google_accounts_header.configure(font=('Segoe UI', 10, 'bold'))
        self.apply_service_visibility()
        self.draw_tokenharbor_accounts()
        self.update_total_quota()
        accounts = sorted(self.items, key=self.account_sort_key)
        manual_order = any(self.account_priority(a) for a in accounts)
        names = [a['name'] for a in accounts]
        layout = [(a['name'], (a.get('access_issue') == 'verification',
            self.account_weekly_depleted(a['name']), self.quota_layout(a['name']), manual_order, self.account_empty_quota(a))) for a in accounts]
        empty_count = sum(self.account_empty_quota(a) for a in accounts)
        ready_count = len(accounts) - empty_count
        if getattr(self, 'account_layout', None) == layout:
            for account in accounts:
                self.update_account_row(account)
            return
        position = self.account_list._parent_canvas.yview()[0]
        for _, widget, _ in getattr(self, 'account_group_widgets', []):
            widget.destroy()
        for name in list(self.account_widgets):
            if name not in names:
                self.account_widgets.pop(name)['card'].destroy()
            else:
                self.account_widgets[name]['card'].pack_forget()
        self.account_group_widgets = []
        self.account_layout = layout
        for index, account in enumerate(accounts):
            section = ('Quota empty · rest stop', empty_count, '#ff8d8d', True) if empty_count and index == ready_count else None
            if section:
                title, count, color, divider = section
                if divider:
                    separator = ctk.CTkFrame(self.google_accounts_content, height=1, fg_color='#43516a')
                    options = {'fill': 'x', 'padx': 5, 'pady': (6, 3)}
                    separator.pack(**options)
                    self.account_group_widgets.append((index, separator, options))
                header = ctk.CTkLabel(self.google_accounts_content, text=f'{title} · {count}', height=19, anchor='w',
                    font=('Segoe UI', 11, 'bold'), text_color=color)
                options = {'fill': 'x', 'padx': 6, 'pady': (0, 3)}
                header.pack(**options)
                self.account_group_widgets.append((index, header, options))
            name = account['name']
            if name in self.account_widgets:
                self.account_widgets[name]['card'].pack(fill='x', pady=(0, 1), padx=1)
                self.update_account_row(account)
                continue
            card = ctk.CTkFrame(self.google_accounts_content, fg_color='#202938', corner_radius=10,
                border_width=1, border_color=ACCENT if not self.details_collapsed and name == self.selected else '#344155')
            card.pack(fill='x', pady=(0, 1), padx=1)
            status = self.sidebar_account_status(account)
            heading_row = ctk.CTkFrame(card, fg_color='transparent')
            heading_row.pack(fill='x', pady=(6, 0), padx=7)
            heading_row.grid_columnconfigure(0, weight=1)
            controls = ctk.CTkFrame(heading_row, fg_color='transparent', width=1, height=19)
            controls.grid(row=0, column=1, sticky='e')
            button = ctk.CTkButton(heading_row, text=self.account_heading(account), localize=False,
                height=19, anchor='w', corner_radius=6, fg_color='#303e59' if not self.details_collapsed and account['name'] == self.selected else CARD,
                hover=not self.details_collapsed,
                hover_color='#334158', text_color=TEXT, font=('Segoe UI', 12, 'bold'), command=lambda a=account: self.select(a))
            button.configure(width=1)
            button.configure(image=self.provider_icons['antigravity'], compound='left', border_spacing=4)
            button.grid(row=0, column=0, sticky='ew')
            self.bind_account_rename(button, name, 'Google')
            pause = self.account_pause_button(controls, name, 'google')
            pause.pack(side='right')
            remove = self.button(controls, '×', lambda n=name: self.remove_google_account(n))
            remove.configure(width=15, height=18, corner_radius=2, font=('Segoe UI', 11),
                             fg_color='transparent', text_color=MUTED, hover_color='#52313a')
            self.attach_tooltip(remove, 'Remove account')
            remove.pack(side='right', padx=(2, 0))
            status_row = ctk.CTkFrame(card, fg_color='transparent')
            status_row.pack(fill='x', padx=8, pady=0)
            priority = self.make_priority_counter(controls, account, 'google')
            plan = ctk.CTkLabel(status_row, text='', height=16, width=1, corner_radius=5,
                                fg_color='#183b32', text_color=TEXT, font=('Segoe UI', 9, 'bold'))
            plan.pack(side='left', padx=(0, 5))
            state = ctk.CTkLabel(status_row, text='', height=16, width=1, anchor='w',
                                 font=('Segoe UI', 10), text_color=MUTED, wraplength=0, justify='left')
            state.pack(side='left', fill='x', expand=True)
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
            quota_frame.pack(fill='x', padx=7, pady=(0, 7))
            widgets = {'card': card, 'button': button, 'pause': pause, 'remove': remove, 'plan': plan, 'status': state, 'priority': priority, 'quota_icons': {}, 'quotas': {}, 'quota_frame': quota_frame, 'countdown': countdown, 'verification_frame': verification_frame,
                       'active_families': (), 'quota_rows': {}}
            self.account_widgets[account['name']] = widgets
            button.bind('<Configure>', lambda event, row=widgets: self.draw_active_badges(row, row.get('active_families', ()), row.get('badge_model', '')), add='+')
            groups = self.quota_groups(account['name'])
            for group in groups:
                visible_buckets = sorted(group['buckets'], key=lambda b: b['window'] != '5h')
                for bucket in visible_buckets:
                    remaining = bucket.get('remaining')
                    text = self.sidebar_quota_text(group, bucket)
                    header = ctk.CTkFrame(quota_frame, fg_color='transparent')
                    header.pack(fill='x', padx=3, pady=(1 if group['kind'] == 'claude' and bucket['window'] == '5h' else 0, 0))
                    header.grid_columnconfigure(2, weight=1)
                    icon = ctk.CTkLabel(header, text='', image=self.provider_icons[group['kind']] if bucket is visible_buckets[0] else None, height=14, width=14)
                    icon.grid(row=0, column=0, padx=(0, 4))
                    widgets['quota_icons'][(group['kind'], bucket['window'])] = icon
                    label = ctk.CTkLabel(header, text=text, height=14, width=76, font=('Segoe UI', 11), text_color=self.quota_color(remaining), anchor='w')
                    label.grid(row=0, column=1, sticky='w')
                    reset_label = ctk.CTkLabel(header, text='', height=14, width=68, font=('Segoe UI', 12, 'bold'), text_color=TEXT, anchor='e')
                    reset_label.grid(row=0, column=3, sticky='e', padx=(6, 0))
                    countdown[(group['kind'], bucket['window'])] = reset_label
                    bar = self.make_quota_limit_bar(header, name, group['kind'], bucket['window'],
                        width=35, height=5, fg_color='#354157', progress_color=self.quota_color(remaining))
                    bar.grid(row=0, column=2, sticky='ew', padx=(3, 0))
                    bar.set(remaining if remaining is not None else 0)
                    widgets['quotas'][(group['kind'], bucket['window'])] = (label, bar)
                    widgets['quota_rows'][(group['kind'], bucket['window'])] = header
            self.update_account_row(account)
        for account_name in self.account_widgets:
            self.update_countdown(account_name)
        self.after_idle(lambda: self.account_list._parent_canvas.yview_moveto(position))

    def account_heading(self, account):
        marker = '!' if account.get('access_issue') else 'Ⅱ' if account.get('disabled') else ''
        return (marker + '  ' if marker else '') + self.display_name(account)

    def make_priority_counter(self, parent, account, provider):
        frame = ctk.CTkFrame(parent, fg_color='transparent', corner_radius=5, height=18, width=1)
        frame.pack(side='right', padx=(3, 0))
        down = self.button(frame, '', lambda: self.change_account_priority(account, provider, -1))
        down.configure(width=14, height=18, corner_radius=1, image=self.playback_icons['down'], border_spacing=0, fg_color='transparent')
        self.attach_tooltip(down, 'Decrease priority')
        down.pack(side='left')
        value = ctk.CTkLabel(frame, text='0', width=15, height=18, font=('Segoe UI', 10), text_color=TEXT)
        value.pack(side='left')
        up = self.button(frame, '', lambda: self.change_account_priority(account, provider, 1))
        up.configure(width=14, height=18, corner_radius=1, image=self.playback_icons['up'], border_spacing=0, fg_color='transparent')
        self.attach_tooltip(up, 'Increase priority')
        up.pack(side='left')
        value.priority_down, value.priority_up = down, up
        return value

    def update_priority_counter(self, widget, account):
        value = self.controller.preferences.get('account-priorities', {}).get(account['name'], 0)
        widget.configure(text=str(value))
        widget.priority_down.configure(state='normal' if value > 0 else 'disabled')
        widget.priority_up.configure(state='normal' if value < 999 else 'disabled')

    def change_account_priority(self, account, provider, delta):
        if self.busy:
            return
        if provider == 'api':
            self.change_api_priority(account['name'], delta)
            return
        priorities = self.controller.preferences.get('account-priorities', {})
        previous = priorities.get(account['name'], 0)
        value = min(999, max(0, previous + delta))
        if value == previous:
            return
        self.controller.preferences.setdefault('account-priorities', {})[account['name']] = value
        self.controller.save()
        if provider == 'grok':
            self.grok_panel.render()
            self.refresh_grok_accounts()
        elif provider == 'claude-native':
            self.claude_panel.render()
            self.refresh_claude_accounts()
        elif provider == 'openai':
            self.draw_chatgpt_accounts()
            self.refresh_chatgpt_accounts()
        else:
            self.draw_account_list()
            self.policy_rows = []
            self.queue_policy()
        self.notice.configure(text='Account priority saved.', text_color=GREEN)

    def account_weekly_depleted(self, name):
        gemini = next((group for group in self.quota_groups(name) if group['kind'] == 'gemini'), {})
        weekly = next((bucket.get('remaining') for bucket in gemini.get('buckets', [])
                       if bucket.get('window') == 'weekly'), None)
        return (isinstance(weekly, (int, float)) and not isinstance(weekly, bool)
                and math.isfinite(weekly) and 0 <= weekly < .01)

    def account_sort_key(self, account):
        problem = self.account_problem_rank(account)
        priority = -self.account_priority(account)
        empty = self.account_empty_quota(account)
        if empty:
            return (1, problem, priority, 2, self.account_reset_order(account['name']), 1)
        if account.get('access_issue') == 'verification':
            return (0, problem, priority, 0, 0, 0)
        return (0, problem, priority, 2 if self.account_weekly_depleted(account['name']) else 1,
                self.account_reset_order(account['name']), 1)

    def account_empty_quota(self, account):
        """Unknown quota stays usable; a depleted window blocks its provider family."""
        if account.get('access_issue') == 'verification':
            return False
        name = account.get('name')
        quota = account.get('quota') or {}
        windows = quota.get('windows') or []
        values = [window.get('remaining') for window in windows
                  if isinstance(window, dict) and isinstance(window.get('remaining'), (int, float))
                  and not isinstance(window.get('remaining'), bool) and math.isfinite(window['remaining'])]
        if values:
            return any(value <= 0 for value in values)
        groups = self.quota_cache.get(name, {}).get('data', {}).get('groups', []) if name else []
        known = []
        for group in groups:
            remaining = [b.get('remaining') for b in group.get('buckets', [])
                         if isinstance(b.get('remaining'), (int, float)) and not isinstance(b.get('remaining'), bool)
                         and math.isfinite(b['remaining'])]
            if remaining:
                known.append(any(value <= 0 for value in remaining))
        return bool(known) and all(known)

    def account_problem_rank(self, account):
        """Keep accounts requiring attention above healthy and paused accounts."""
        if account_status(account)[1] in ('error', 'warning'):
            return 0
        name = account.get('name')
        if name and self.quota_cache.get(name, {}).get('error'):
            return 0
        return 1

    def account_priority(self, account):
        return self.controller.preferences.get('account-priorities', {}).get(account['name'], 0)

    def account_reset_order(self, name):
        resets = []
        window = 'weekly' if self.account_weekly_depleted(name) else '5h'
        for group in self.quota_groups(name):
            if group.get('kind') != 'gemini':
                continue
            for bucket in group['buckets']:
                if bucket.get('window') != window:
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
        # OpenAI brand mark from Simple Icons 13.21.0, embedded for offline packaged builds.
        openai = Image.open(io.BytesIO(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAJrUlEQVR4nM1bW3IbtxJtQMoNqZ8bXaVulXU/MllBlBWEXoGVFZhegZkVmF6B6RWIWoHpFZhZgZUViPqwXHXLiswfUU7EQfoAM+QAA8yLQyanSlXiPECg0Y/TjeY+bREfbxeRisUTEnGPlDjhS5H1gKKpEDQlSb8+OuxO6W+AoC3g46fFU0XU59F7NV6b8XRGXfn1+eGh+Ew7QqsC+P/tHycPy+Wrmgt3MSMpfzk+/HpCO0BrAuBd78dCvRIkvqEWwBo0/t9R9xltGa0I4MPN4kxA5UNQ6q0S4kJIeSEoNuq9pEgZTcHfd973hJp0RffZNk1iYwFg53khZ55bV0LRsLPXmZQtgJ1lTy1pyLP5yXN7xuowU0KdWNrFDpQFdCGUuODveNtUSBsJQE88pneeW+dd2RnUndT1zf2AVzbkf/9NNQGTkZJecjSZ1XlPUkPc3qpv4li9ca/zrj87Pur26y4e4wlSWHjtxevvZRPkzbi8vrl7hbGqvtdYAIt4MXQdHu/Cy0ffdsdUEwibd/Hikt8f0sYQg0V8/x4RqdLT1ACQMH/JrXVR0a/H33Z7VAMwIdYiRI7wZBMHyuo9zV6OY+qxtvUCfoOnoz5/Jfcf//fwXxdUgH1qgEX8pe9eE3sFUcABGCIv4AWrbF+E9+BcSBo+OjyYBe5PM2PxOPTCmg9r55/xwzvWhEIh1NKAD7dfnrDoT1m+p476n8Puy96H5tzH989jUoMgX+AdF3tiUNeZGUGoCY/7gzUca8KB7H4f8kmlAqg0aSl/LmNumh4LbeNR4JEr3vH+JjkB5sq+ZOoKAXzi+D8HP/veKRRAhUlr8O4Hx6lAj+c8jeHxUWdELeHDzd2FKwQW7mOfcGV4kMUZL35MJYuH8wvdQkh6iJfvw4tXr5kvRG0uHpBSsJlCsJlvWto+YvWs72IJtZ1TBfDiRwhJ3pssNN6R74+PDgZVWCLmwyTpedX4bvyHGFoXeRPgJ9xncwK4/v3ujXfxZtKPOVZX2y3lDW2w88cIl2VODpO9/rR4B6Zp5qNGiO8wS6oATqvH5GwWooX7nCUA8Hqe+Kn7EAhOMukpNcNcj3HUjcrGwC5/vFkgRF56TAcJ1BiCKSM6iWZZjlnzBgcrAWBApLPuA6C2nJYOaQPAzquMUZkRsmDgW2AahWYh5cR5L0eaVgLgAXNhDotvQm1dVLPzu/fYXTvjU28RYkOOFqYBgcE/+O/Hnz3fFWU/y8xF17bO21h8EbSds88xdr72GUxefjO+4uAU/ALmh83gW1fuGEZganR9s7iEILP3AuYWZT9oAahYud56jnSWtoTUzpm5vXd8ztyY3MGJO3lsBs/pBL6E/JEogiAhUJ+3DyExAa7cWlDjbVVhYOfw5rDzPLMUL4q0DnOCL2HtONHm4QMLFA4UAg74h1n2g0y8aZS9uC/3x9QyoJ46rBWSK1ZlfsZVZRcIoTAPE5bVb96RWMDwD753s5/lcrl0w8m8LIWsC80qUTmyw5rmBPijrG3zM3i21MOTsXGYS+IfcmaRr1fkhSVjkTusaHXxZiIWAQH3/yXlBPjD/7hGmUWkHh6qXDZ+4h8iUOuSeUzda40rQg1xHuL+uOYuAjsIVYaHv779clo0MPwDqDUodjA/Efnq824EwBPal3s/ltUKCxYRMY99k/iHqOirjH9AZUprlDMPcarZbgY7EQAmVMevrBfhwPiHSoVPaBSETm4+wGw3K0Tp1tq4/v4D/fMwJ2shYqD9Q0lipIUuZT97TZtVvKba0ICZ+0DViurOwI5Zx372IeklvRAOqaDQRWHTVKpyzvFpqgUyiYsWxXyIH/qhAXG8Zc2NNaZqiroJtFmwD9FhM+MfQKHTsBl6tyt1ImYXSBL2m/gAZWVN7Hmfhmwsqf3ldqIKgWkDOmyucwMrbLoOLoVxvGpsXzXsVwtASGGFJSwKBx8UwGonAgSmDhdvCk2ZHc6S4zQZeNhthHlqASRmcG7fF89DEk3eCRIYJDn/NGeaRCGXLUarMIhDCPKEjDKHGCIwbfUJtApXY/h0aSUAaAHblZUCYxGovIQKDinKWFhd/wCh4x3aASwiZOzKl2ausrSICrAiMKjiNEhwcK+8lL4JVI6F5pmgsHlB5nqvJM9eQVdx2D+4xYuiBAdaZtJXsbVCDHnMMicAnvRPVIA0z64S+1G8MP7BCZuZBEfXCW6wcDVyzxupZbiOGZwmJ4DCo+r1M5VYGGD8Q7evebknwUk6TKL1LM35Q5XD1jqAX8kVfSm2BeBTbd7Bw0SVc0hZWJU6HMJQMEszuNLdJZudPwTxZ7x00+kr+CxLAPd0n9v9TB0unGeX1+E0TANlnLN/CBgFz21Voc2clBPJDPutnA6nHj7HALNDsm37jq+K6v4QLAS8zVY4XztPyn4tAXSok8vZXdUOMcAMVsdXaKgoq/vXbYSoC1NJEi6POU+/1xKAbxcUSa9T9DFACxw2RRxPqtb9XdTp9AoBjk/FSzdLnCesVyNvAq6d65YYP1IG6PHwHphegCp2Dl/iK2nXAfIY9Ah5jvus9pt8k5RQbAZixQVYXZ9gN4psNEk0elrd4hi2tS4+IqztofUl2Oy0nrRpvDxjXxIVNE+VjREppV4pRaeeMXLHfcI7AI6mM4CXrnNCbDo+44gdzaRKSNPfuaSzAvrrbcJiPzPNnviiIaogCfOO4RWzb2ApxY9tOyzTbwhaXEh/g2237jzDUK9hqr473jDIKju0PrNU0RbbhmNKUcr9M4wwaH7lizcdKYHFmyFCE/x0NyHhHJq20L5eoTt0rh1VibNM/M2bwO2r5PcGQypBUABJO+yMnOZlNoeLr+T+s7rnh6lz8rXgrMemlweyM6oiYE6gxmT3NMxR90Ppq87cCl2t7vGLl1PydHDzi8OO7Lyu0P2h22LLflBRpzvU56jNeWP9drvSWFMkBDOCmuBHC+QcsBCXm5RpZu6FxgYjZOc6qJv86GqRMy6StiamWSnYJkJA8vAdtYPG3aFJ/6Gb2LwucnRFqMw2kpA19PDqmgAjbJb8mNqkcoV2hUyyqWOunA1ahc+G1Rqla3LyssmvSczJj8prjJSDTaJSM76ZTOp+eX+KHzPprlChz+5SPzHXJWhzUJE3G/xidE//vmda9j1Irbk8P/IxvDba+BoLoAq02Sw5XLl8Yo0ZChNK7k1lpqdPxRBorJ1oiNrWpechbFUAKTwxeyO01cAJ7KZBAkmIe1bQBEmXeZuls51oQAoTSfB7I300XT2kotawJ0fb+D3xTgWQheHyy17iQO2kRhdXOGIIORVSTbZZNvsLN2HJwAbYNV0AAAAASUVORK5CYII='))).convert('RGBA')
        light_openai = Image.new('RGBA', openai.size, '#243047')
        light_openai.putalpha(openai.getchannel('A'))
        grok = Image.new('RGBA', (64, 64))
        draw = ImageDraw.Draw(grok)
        draw.arc((8, 8, 55, 55), 45, 340, fill='#bac9df', width=5)
        draw.line((19, 49, 51, 14), fill='#bac9df', width=6)
        antigravity = Image.open(io.BytesIO(base64.b64decode(ANTIGRAVITY_PNG))).convert('RGBA')
        return {kind: ctk.CTkImage(light_image=light_openai if kind == 'openai' else bitmap, dark_image=bitmap, size=(14, 14))
                for kind, bitmap in [('gemini', gemini), ('claude', claude), ('openai', openai), ('antigravity', antigravity), ('grok', grok)]}

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

    @staticmethod
    def visible_quota_buckets(group):
        weekly = next((bucket.get('remaining') for bucket in group['buckets']
                       if bucket.get('window') == 'weekly'), None)
        hide_five_hour = isinstance(weekly, (int, float)) and not isinstance(weekly, bool) and 0 <= weekly < .01
        return [bucket for bucket in group['buckets']
                if not (hide_five_hour and bucket.get('window') == '5h')]

    def quota_layout(self, name):
        return tuple((group['kind'], bucket['window']) for group in self.quota_groups(name)
                     for bucket in self.visible_quota_buckets(group))

    def create_pool_summary(self, provider, title):
        group = ctk.CTkFrame(self.sidebar_footer, fg_color='transparent')
        group.pack(fill='x', padx=18, pady=(0, 3))
        collapsed = self.controller.preferences.get(provider + '-pool-collapsed', True)
        header = self.button(group, ('▸' if collapsed else '▾') + '  ' + title,
                             lambda: self.toggle_pool_summary(provider))
        header.configure(height=25, anchor='w', font=('Segoe UI', 11, 'bold'), fg_color='#303b50')
        header.pack(fill='x', pady=(0, 2))
        self.install_service_add_button(header, provider)
        compact = self.make_quota_dots(header, ('5h', '1w'))
        self.show_quota_dots(compact, collapsed, after=header)
        body = ctk.CTkFrame(group, fg_color='transparent')
        if not collapsed:
            body.pack(fill='x', padx=3)
        self.pool_summary_groups[provider] = {'frame': group, 'header': header, 'body': body, 'compact': compact,
                                             'title': title, 'collapsed': collapsed}
        return body

    def toggle_pool_summary(self, provider):
        group = self.pool_summary_groups[provider]
        group['collapsed'] = not group['collapsed']
        group['header'].configure(text=('▸' if group['collapsed'] else '▾') + '  ' + group['title'])
        if group['collapsed']:
            group['body'].pack_forget()
        else:
            group['body'].pack(fill='x', padx=3)
        self.controller.preferences[provider + '-pool-collapsed'] = group['collapsed']
        self.controller.save()
        self.show_quota_dots(group['compact'], group['collapsed'], after=group['header'])
        self.update_compact_quotas()

    def make_quota_dots(self, parent, labels):
        frame = ctk.CTkFrame(parent, fg_color='#303b50', width=len(labels) * 21, height=22, corner_radius=0)
        frame.dot_widgets = []
        for label in labels:
            widget = ctk.CTkLabel(frame, text='', width=19, height=22, padx=0)
            widget.dot_label = label
            widget.pack(side='left', padx=(0, 2))
            widget.bind('<Button-1>', lambda event, button=parent: button.invoke())
            frame.dot_widgets.append(widget)
        return frame

    @staticmethod
    def show_quota_dots(frame, visible, after):
        if visible and not frame.winfo_manager():
            frame.place(relx=1, rely=.5, x=-28 if hasattr(after, 'service_add') else -5, anchor='e')
            frame.lift()
        elif not visible:
            frame.place_forget()

    def set_quota_dots(self, frame, values):
        signature = tuple(None if value is None else round(value, 3) for value in values)
        if getattr(frame, 'dot_values', None) == signature:
            return
        frame.dot_values = signature
        for index, widget in enumerate(frame.dot_widgets):
            hide = widget.dot_label.endswith('5h') and index+1 < len(values) and isinstance(values[index+1], (int, float)) and values[index+1] < .01
            if hide:
                widget.pack_forget()
            elif not widget.winfo_manager():
                following = next((other for other in frame.dot_widgets[index+1:] if other.winfo_manager()), None)
                widget.pack(side='left', padx=(0, 2), **({'before': following} if following else {}))
        for widget, value in zip(frame.dot_widgets, values):
            label = widget.dot_label.split()[-1] if widget.dot_label.strip() else ''
            widget.configure(image=ctk.CTkImage(light_image=quota_dot(value, True, label),
                                              dark_image=quota_dot(value, label=label), size=(19, 19)))

    def update_compact_quotas(self):
        def average(values):
            values = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1]
            return sum(values) / len(values) if values else None
        google = {('gemini', '5h'): [], ('gemini', 'weekly'): [], ('claude', '5h'): [], ('claude', 'weekly'): []}
        for account in self.items:
            if account.get('disabled') or self.quota_cache.get(account['name'], {}).get('error'):
                continue
            for group in self.quota_groups(account['name']):
                for bucket in group['buckets']:
                    key = (group['kind'], bucket['window'])
                    if key in google:
                        google[key].append(bucket.get('remaining'))
        if hasattr(self, 'google_compact'):
            self.set_quota_dots(self.google_compact, [average(v) for v in google.values()])
        def openai_values(accounts):
            values_by_window = []
            for label in ('5h', '1w'):
                values = []
                for account in accounts:
                    quota = account.get('quota') or {}
                    if account.get('disabled') or quota.get('error'):
                        continue
                    for window in quota.get('windows', []):
                        if window.get('label') == label and isinstance(window.get('remaining'), (int, float)):
                            values.append(window['remaining'] / 100)
                values_by_window.append(average(values))
            return values_by_window
        openai = openai_values([account for account in self.chatgpt_items if not is_free_account(account)])
        free_openai = openai_values([account for account in self.chatgpt_items if is_free_account(account)])
        if hasattr(self, 'chatgpt_compact'):
            self.set_quota_dots(self.chatgpt_compact, openai)
        if hasattr(self, 'chatgpt_free_compact'):
            self.set_quota_dots(self.chatgpt_free_compact, free_openai)
        for provider, group in getattr(self, 'pool_summary_groups', {}).items():
            values = [getattr(self, 'total_remaining', None), getattr(self, 'total_weekly_remaining', None)] if provider == 'google' else openai
            if provider=='claude-native':
                values = self.claude_panel.pooled_values()
            if provider=='grok':
                values = self.grok_panel.pooled_values()
            self.set_quota_dots(group['compact'], values)

    def update_openai_pool_quota(self):
        accounts = [account for account in self.chatgpt_items if not account.get('disabled')]
        values = {'5h': [], '1w': []}
        entries = {'5h': [], '1w': []}
        now = datetime.now(timezone.utc)
        def valid(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100
        for account in accounts:
            quota = account.get('quota') or {}
            if quota.get('error'):
                continue
            windows = {window['label']: window for window in quota.get('windows', [])}
            weekly = windows.get('1w', {}).get('remaining')
            if valid(weekly):
                values['1w'].append(weekly / 100)
                try:
                    moment = datetime.fromtimestamp(windows['1w']['reset_at'], timezone.utc).isoformat()
                except (KeyError, ValueError, TypeError, OverflowError, OSError):
                    moment = None
                entries['1w'].append({'remaining': weekly / 100, 'reset': moment, 'weekly_remaining': 1})
            primary = windows.get('5h', {})
            remaining = primary.get('remaining')
            if valid(remaining):
                def reset(window):
                    try:
                        return datetime.fromtimestamp(window['reset_at'], timezone.utc).isoformat()
                    except (KeyError, ValueError, TypeError, OverflowError, OSError):
                        return None
                bucket = {'remaining': remaining / 100, 'reset': reset(primary)}
                week = {'remaining': weekly / 100 if valid(weekly) else None, 'reset': reset(windows.get('1w', {}))}
                entry = quota_entry(account, bucket, week, 'claude', now)
                values['5h'].append(0 if valid(weekly) and weekly < 1 else entry['remaining'])
                if valid(weekly) and weekly < 1:
                    entry['weekly_remaining'] = 0
                entries['5h'].append(entry)
        for window, widgets in self.openai_pool_widgets.items():
            available = values[window]
            remaining = sum(available) / len(available) if available else None
            title, value, bar = widgets
            text = f'{window} · pooled remaining' if len(available) == len(accounts) and available else f'{window} · data {len(available)}/{len(accounts)} accounts'
            color = self.quota_color(remaining)
            title.configure(text=text)
            value.configure(text=self.quota_percent(remaining), text_color=color)
            bar.configure(progress_color=color)
            bar.set(remaining if remaining is not None else 0)
            forecast = quota_projection(entries[window], now, exhausted_only=False)
            self.openai_forecasts[window] = (remaining, forecast)
            canvas = self.openai_forecast_canvases[window]
            if forecast:
                bar.pack_forget()
                if not canvas.winfo_manager():
                    canvas.pack(fill='x', pady=(1, 0))
                self.draw_total_forecast(openai_window=window)
            else:
                canvas.pack_forget()
                if not bar.winfo_manager():
                    bar.pack(fill='x', pady=(1, 0))

    def update_total_quota(self):
        self.update_openai_pool_quota()
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
                        entry = quota_entry(account, bucket, weekly, 'gemini')
                        depleted_weekly = isinstance(weekly_value, (int, float)) and not isinstance(weekly_value, bool) and 0 <= weekly_value < .01
                        values.append(0 if depleted_weekly else entry['remaining'])
                        if depleted_weekly:
                            entry['weekly_remaining'] = 0
                        entries.append(entry)
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
        self.update_compact_quotas()

    def schedule_total_forecast(self, weekly=False, openai_window=None):
        job_attr = 'weekly_forecast_resize_job' if weekly else 'forecast_resize_job'
        if openai_window:
            job_attr = 'openai_' + openai_window + '_resize_job'
        if getattr(self, job_attr, None):
            self.after_cancel(getattr(self, job_attr))
        def draw():
            setattr(self, job_attr, None)
            if not self.closed:
                self.draw_total_forecast(weekly=weekly, openai_window=openai_window)
        setattr(self, job_attr, self.after(75, draw))

    def draw_total_forecast(self, weekly=False, openai_window=None):
        canvas = self.weekly_forecast_canvas if weekly else self.forecast_canvas
        forecast = self.total_weekly_forecast if weekly else self.total_forecast
        total_remaining = self.total_weekly_remaining if weekly else self.total_remaining
        key_attr = 'weekly_forecast_render_key' if weekly else 'forecast_render_key'
        labels_attr = 'weekly_forecast_hover_labels' if weekly else 'forecast_hover_labels'
        if openai_window:
            canvas = self.openai_forecast_canvases[openai_window]
            total_remaining, forecast = self.openai_forecasts.get(openai_window, (None, []))
            weekly = openai_window == '1w'
            key_attr = 'openai_' + openai_window + '_render_key'
            labels_attr = 'openai_' + openai_window + '_hover_labels'
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

    def hover_forecast(self, event, weekly=False, openai_window=None):
        canvas = self.weekly_forecast_canvas if weekly else self.forecast_canvas
        if openai_window:
            canvas = self.openai_forecast_canvases[openai_window]
        canvas.delete('forecast_hover')
        labels_attr = 'openai_' + openai_window + '_hover_labels' if openai_window else 'weekly_forecast_hover_labels' if weekly else 'forecast_hover_labels'
        labels = getattr(self, labels_attr, [])
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
        self.update_selection_style(account, widgets)
        widgets['button'].configure(text=self.account_heading(account))
        self.update_pause_button(widgets['pause'], account.get('disabled'))
        widgets['plan'].configure(text=' ' + self.google_plan_name(account) + ' ')
        self.update_priority_counter(widgets['priority'], account)
        state, severity, reason = google_account_status(account, self.quota_groups(account['name']))
        reserved = blocked_families(self.controller.preferences, account['name'], self.quota_groups(account['name']))
        if reserved and severity != 'error':
            state, severity = 'Quota reserve reached · ' + ' / '.join(kind.title() for kind in sorted(reserved)), 'warning'
        state_text = state if severity in ('warning', 'error') else f'{state} · {account.get("success") or 0} responses'
        widgets['status'].configure(text=self.uptime_status(widgets['status'], account, state_text),
            text_color={'error': '#ff6b7a', 'warning': '#f7ca70', 'normal': MUTED, 'muted': MUTED}[severity])
        if account.get('access_issue') == 'verification':
            if not widgets['verification_frame'].winfo_manager():
                widgets['verification_frame'].pack(fill='x', padx=5, pady=(0, 3), before=widgets['quota_frame'])
        else:
            widgets['verification_frame'].pack_forget()
        for group in self.quota_groups(account['name']):
            visible = {bucket['window'] for bucket in self.visible_quota_buckets(group)}
            first_visible = next((bucket['window'] for bucket in sorted(group['buckets'], key=lambda b: b['window'] != '5h') if bucket['window'] in visible), None)
            for bucket in group['buckets']:
                key = (group['kind'], bucket['window'])
                widgets['quota_icons'][key].configure(image=self.provider_icons[group['kind']] if bucket['window'] == first_visible else None)
                row = widgets['quota_rows'][key]
                if bucket['window'] not in visible:
                    row.pack_forget()
                elif not row.winfo_manager():
                    options = {'fill': 'x', 'padx': 3, 'pady': (3 if group['kind'] == 'claude' and bucket['window'] == '5h' else 0, 0)}
                    siblings = list(widgets['quota_rows'])
                    following = next((widgets['quota_rows'][k] for k in siblings[siblings.index(key) + 1:] if widgets['quota_rows'][k].winfo_manager()), None)
                    if following:
                        options['before'] = following
                    row.pack(**options)
                label, bar = widgets['quotas'][(group['kind'], bucket['window'])]
                remaining = bucket.get('remaining')
                label.configure(text=self.sidebar_quota_text(group, bucket), text_color=self.quota_color(remaining))
                bar.configure(progress_color=self.quota_color(remaining))
                bar.set(remaining if remaining is not None else 0)
                bar.set_floor(quota_floor(self.controller.preferences, account['name'], group['kind'], bucket['window']))
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
            for bucket in self.visible_quota_buckets(group):
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
            return '#147d61' if ctk.get_appearance_mode() == 'Light' else '#66e2a7'
        minimum, maximum = bounds or (0, 7 * 86400)
        ratio = min(1, max(0, (seconds - minimum) / (maximum - minimum))) if maximum > minimum else .5
        start, end, fraction = ((102, 226, 167), (245, 197, 107), ratio * 2) if ratio <= .5 else ((245, 197, 107), (255, 68, 85), (ratio - .5) * 2)
        factor = .62 if ctk.get_appearance_mode() == 'Light' else 1
        return '#' + ''.join(f'{round((a + (b - a) * fraction) * factor):02x}' for a, b in zip(start, end))

    def tick_countdowns(self):
        for name in self.account_widgets:
            self.update_countdown(name)
        for item in self.chatgpt_items:
            self.update_chatgpt_countdowns(item)
        self.claude_panel.render()
        self.grok_panel.render()
        self.update_total_quota()
        if not self.closed:
            self.after(15000, self.tick_countdowns)

    @staticmethod
    def model_family(model):
        if model.startswith('api-') and '/' in model:
            return model.split('/', 1)[0][4:]
        # These Claude-compatible aliases actually route to Gemini subscriptions.
        if model == 'claude-sonnet-4-5' or model.startswith('gemini'):
            return 'gemini'
        if model.startswith('gpt-oss'):
            return 'claude'
        if model.startswith(('gpt', 'o1', 'o3', 'o4', 'codex')):
            return 'openai'
        if model.startswith('grok'):
            return 'grok'
        if model.startswith('claude'):
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
        for family, title in (('claude', 'Claude'), ('gemini', 'Gemini'), ('openai', 'OpenAI')):
            if family in resets:
                minutes = math.ceil(max(0, resets[family] - now) / 60)
                duration = f'{minutes // 60}h {minutes % 60:02}m' if minutes >= 60 else f'{minutes}m'
                labels.append(f'until {title} · {duration}')
        return '  /  '.join(labels) or 'Waiting'

    def poll_gateway_jobs(self):
        if self.closed:
            return
        if not self.controller.key:
            self.after(1000, self.poll_gateway_jobs)
            return
        def done(snapshot):
            if self.closed:
                return
            self.gateway_jobs = snapshot.get('jobs', [])
            self.gateway_jobs_checked = time.monotonic()
            self.after(1000, self.poll_gateway_jobs)
        self.work(self.controller.quota_wait_status, done)

    def active_provider_accounts(self):
        if time.monotonic() - getattr(self, 'gateway_jobs_checked', 0) > 10:
            return {}
        running = {job.get('upstream_model') or
                   getattr(self, 'model_aliases', {}).get(job.get('model'), job.get('model', ''))
                   for job in getattr(self, 'gateway_jobs', []) if job.get('state') == 'running'}
        waiting = {job.get('upstream_model') or
                   getattr(self, 'model_aliases', {}).get(job.get('model'), job.get('model', ''))
                   for job in getattr(self, 'gateway_jobs', []) if job.get('state') == 'waiting'}
        busy_families = {self.model_family(model) for model in running | waiting}
        enabled = {a['name'] for a in self.items + getattr(self, 'chatgpt_items', []) + getattr(self, 'claude_items', []) + getattr(self, 'grok_items', []) + getattr(self, 'api_items', []) if not a.get('disabled')}
        latest = {}
        for model, event in self.activity_state['latest'].items():
            actual = event.get('upstream_model') or getattr(self, 'model_aliases', {}).get(event.get('model') or model, event.get('model') or model)
            family = self.model_family(actual)
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(event['at'].replace('Z', '+00:00'))).total_seconds()
                age -= max(0, float(event.get('latency_ms') or 0)) / 1000
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            # Completed fast requests can disappear between queue polls. Keep
            # their confirmed account visible, without attributing another
            # model's running request or quota wait to this account.
            eligible = actual in running or family not in busy_families
            if (family and eligible and not event.get('failed') and not event.get('probe') and 0 <= age < 60
                    and (family not in latest or event['at'] > latest[family]['at'])):
                latest[family] = event
        return {family: event['name'] for family, event in latest.items() if event['name'] in enabled}

    def active_account_names(self):
        return set(self.active_provider_accounts().values())

    @staticmethod
    def latest_models_by_account(state):
        latest = {}
        for event in state.get('events', []):
            if event.get('probe'):
                continue
            name = event.get('name')
            if name and event.get('at') and event.get('at', '') >= latest.get(name, {}).get('at', ''):
                latest[name] = event
        for event in state.get('latest', {}).values():
            name = event.get('name')
            if name and event.get('at') and event.get('at', '') >= latest.get(name, {}).get('at', ''):
                latest[name] = event
        for name, stats in state.get('stats', {}).items():
            if stats.get('last_model') and stats.get('last', '') >= latest.get(name, {}).get('at', ''):
                latest[name] = {'at': stats['last'], 'upstream_model': stats['last_model'],
                                'latency_ms': stats.get('last_latency_ms') or 0}
        return latest

    def last_account_model(self, name, now=None):
        recent = getattr(self, 'recent_account_models', None)
        last = (recent if recent is not None else App.latest_models_by_account(self.activity_state)).get(name, {})
        try:
            timestamp = datetime.fromisoformat(last['at'].replace('Z', '+00:00'))
            age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
            age -= max(0, float(last.get('latency_ms') or 0)) / 1000
            if not 0 <= age < 60:
                return ''
        except (KeyError, ValueError, TypeError, AttributeError):
            return ''
        model = last.get('upstream_model') or last.get('model')
        if not model:
            return ''
        return model_name(model, getattr(self, 'model_aliases', None))

    def draw_active_badges(self, widgets, families, model=''):
        widgets['badge_model'] = model
        button = widgets['button']
        canvas = button._canvas
        scale = button._get_widget_scaling()
        heading = button.cget('text')
        layout = (families, model, heading, button.winfo_width(), button.winfo_height(), scale, button.cget('fg_color'))
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
        scale = card._get_widget_scaling()
        size = (canvas.winfo_width(), canvas.winfo_height(), scale)
        if min(size[:2]) < 12 * scale:
            return
        segments = widgets.get('rainbow_segments')
        if not segments:
            segments = [(canvas.create_line(0, 0, 0, 0, width=2.5 * scale,
                        capstyle='round', tags='rainbow'), i / 192) for i in range(192)]
            widgets['rainbow_segments'] = segments
        if not widgets.get('rainbow_resize_bound'):
            def resize_border(event):
                if widgets.get('active_highlight'):
                    self.draw_rainbow_border(widgets, (time.monotonic() / 8) % 1)
            canvas.bind('<Configure>', resize_border, add='+')
            widgets['rainbow_resize_bound'] = True
        if widgets.get('rainbow_size') != size:
            inset = 2.5 * scale + 2
            x0, y0 = inset, inset
            x1, y1 = size[0] - inset, size[1] - inset
            radius = min(float(card.cget('corner_radius')) * scale - inset,
                         (x1 - x0) / 2, (y1 - y0) / 2)
            radius = max(0, radius)
            points = []
            for cx, cy, start in [(x0 + radius, y0 + radius, 180), (x1 - radius, y0 + radius, 270),
                                  (x1 - radius, y1 - radius, 0), (x0 + radius, y1 - radius, 90)]:
                for step in range(13):
                    angle = math.radians(start + step * 7.5)
                    points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
            points.append(points[0])
            lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
            perimeter = sum(lengths)
            def at(distance):
                for a, b, length in zip(points, points[1:], lengths):
                    if distance <= length and length:
                        return tuple(a[j] + (b[j] - a[j]) * distance / length for j in (0, 1))
                    distance -= length
                return points[0]
            for i, (item, _) in enumerate(segments):
                canvas.coords(item, *at(perimeter * i / len(segments)),
                              *at(perimeter * (i + 1) / len(segments)))
                canvas.itemconfigure(item, width=2.5 * scale)
            widgets['rainbow_size'] = size
        for item, offset in segments:
            rgb = colorsys.hsv_to_rgb((phase + offset) % 1, .72, 1)
            canvas.itemconfigure(item, fill='#' + ''.join(f'{round(value * 255):02x}' for value in rgb))
        canvas.tag_raise('rainbow')

    def animate_active_borders(self):
        if self.closed:
            return
        providers = self.active_provider_accounts()
        active = set(providers.values())
        running_models = {}
        for job in getattr(self, 'gateway_jobs', []):
            if job.get('state') != 'running':
                continue
            actual = job.get('upstream_model') or getattr(self, 'model_aliases', {}).get(job.get('model'), job.get('model', ''))
            family = self.model_family(actual)
            if family:
                running_models[family] = model_name(actual, getattr(self, 'model_aliases', None))
        for name, widgets in self.account_widgets.items():
            card = widgets['card']
            families = tuple(kind for kind in ('gemini', 'claude') if providers.get(kind) == name)
            self.draw_active_badges(widgets, families,
                running_models.get(families[-1], self.last_account_model(name)) if families else self.last_account_model(name))
            self.update_active_border(widgets, name in active)
        for name, widgets in getattr(self, 'chatgpt_widgets', {}).items():
            is_active = providers.get('openai') == name
            caption = running_models.get('openai', self.last_account_model(name)) if is_active else self.last_account_model(name)
            if widgets['model'].cget('text') != caption:
                widgets['model'].configure(text=caption)
            self.update_active_border(widgets, is_active)
        google_names = {item['name'] for item in self.items}
        google_names.update(item['name'] for item in self.api_items if item.get('provider') == 'gemini')
        self.set_agent_header_active(getattr(self, 'google_accounts_header', None), bool(active & google_names))
        paid_names = {item['name'] for item in self.chatgpt_items if not is_free_account(item)}
        free_names = {item['name'] for item in self.chatgpt_items if is_free_account(item)}
        paid_names.update(item['name'] for item in self.api_items if item.get('provider') == 'openai')
        self.set_agent_header_active(getattr(self, 'chatgpt_header', None), bool(active & paid_names))
        self.set_agent_header_active(getattr(self, 'chatgpt_free_header', None), bool(active & free_names))
        claude_names = {item['name'] for item in self.claude_items}
        claude_names.update(item['name'] for item in self.api_items if item.get('provider') == 'claude')
        grok_names = {item['name'] for item in self.grok_items}
        grok_names.update(item['name'] for item in self.api_items if item.get('provider') == 'grok')
        self.set_agent_header_active(self.claude_panel.header, bool(active & claude_names))
        self.set_agent_header_active(self.grok_panel.header, bool(active & grok_names))
        harbor_event = self.harbor_activity.state.get('latest') or {}
        try:
            harbor_age = time.time() - datetime.fromisoformat(harbor_event['at'].replace('Z', '+00:00')).timestamp()
            harbor_active = not harbor_event.get('failed') and 0 <= harbor_age < 60
        except (KeyError, ValueError, TypeError):
            harbor_active = False
        self.set_agent_header_active(getattr(self, 'tokenharbor_header', None), bool(harbor_active))
        if hasattr(self, 'tokenharbor_compact'):
            value = None if not harbor_event else 0 if harbor_event.get('failed') else 1
            self.set_quota_dots(self.tokenharbor_compact, [value])
        self.claude_panel.animate()
        self.grok_panel.animate()
        self.animate_api_accounts()
        self.after(500, self.animate_active_borders)

    @staticmethod
    def set_agent_header_active(header, active):
        if header is None or not header.winfo_exists() or getattr(header, 'active_account_highlight', None) == active:
            return
        header.active_account_highlight = active
        widgets = getattr(header, 'active_border_widgets', None)
        if widgets is None:
            widgets = {'card': header}
            header.active_border_widgets = widgets
        widgets['active_highlight'] = active
        if not active:
            header._canvas.delete('rainbow')
            widgets.pop('rainbow_size', None)
            widgets.pop('rainbow_segments', None)

    def animate_border_colors(self):
        if self.closed:
            return
        rows = list(getattr(self, 'account_widgets', {}).values())
        rows += list(getattr(self, 'chatgpt_widgets', {}).values())
        rows += list(getattr(self, 'api_rows', {}).values())
        for panel in ('claude_panel', 'grok_panel'):
            rows += list(getattr(getattr(self, panel, None), 'rows', {}).values())
        headers = [getattr(self, field, None) for field in ('google_accounts_header', 'chatgpt_header', 'chatgpt_free_header', 'tokenharbor_header')]
        headers += [getattr(getattr(self, panel, None), 'header', None) for panel in ('claude_panel', 'grok_panel')]
        rows += [header.active_border_widgets for header in headers if header is not None and hasattr(header, 'active_border_widgets')]
        phase = (time.monotonic() / 8) % 1
        for widgets in rows:
            if widgets.get('active_highlight') and widgets['card'].winfo_ismapped():
                self.draw_rainbow_border(widgets, phase)
        frames = self.playback_icons['reset-rainbow']
        reset_icon = frames[int(time.monotonic() * 30) % len(frames)]
        for widgets in getattr(self, 'chatgpt_widgets', {}).values():
            for button in widgets.get('reset_buttons', []):
                if button.winfo_ismapped():
                    button.configure(image=reset_icon)
        self.after(33, self.animate_border_colors)

    def update_active_border(self, widgets, is_active):
        card = widgets['card']
        if widgets.get('active_highlight') != is_active:
            widgets['active_highlight'] = is_active
            if not is_active:
                card._canvas.delete('rainbow')
                widgets.pop('rainbow_size', None)
                widgets.pop('rainbow_segments', None)
        if is_active and card.winfo_ismapped():
            self.draw_rainbow_border(widgets, (time.monotonic() / 8) % 1)

    def private_account_name(self, provider, identity):
        groups = self.controller.preferences.setdefault('private-account-numbers', {})
        numbers = groups.setdefault(provider, {})
        if identity not in numbers:
            numbers[identity] = max(numbers.values(), default=0) + 1
            self.controller.save()
        return self.controller.preferences.get('private-account-labels', {}).get(identity) or f'{provider} {numbers[identity]}'

    def display_name(self, account, provider=None):
        provider = provider or ('Grok' if account.get('provider', account.get('type'))=='xai' else 'Claude' if account.get('provider', account.get('type')) in ('claude', 'anthropic') else 'OpenAI' if account.get('provider', account.get('type')) == 'codex' or
            any(item['name'] == account['name'] for item in self.chatgpt_items) else 'Google')
        if self.hide_account_names:
            return self.private_account_name(provider, account['name'])
        label = self.controller.preferences.get('api-account-labels' if account.get('api') or ' API' in provider else 'labels', {}).get(account['name']) or account.get('label')
        return label or account.get('email') or f'{provider} account'

    def redact_private_text(self, text):
        if not self.hide_account_names:
            return text
        replacements = {}
        for account in self.items + self.chatgpt_items + self.claude_items + self.grok_items + self.api_items:
            for identity in (account.get('email'), account.get('label'), self.controller.preferences.get('labels', {}).get(account['name'])):
                if identity:
                    replacements[identity] = self.display_name(account)
        if replacements:
            pattern = '|'.join(re.escape(identity) for identity in sorted(replacements, key=len, reverse=True))
            text = re.sub(pattern, lambda match: replacements[match.group()], text)
        return re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', 'Hidden account', text)

    def toggle_account_names(self):
        self.hide_account_names = not self.hide_account_names
        self.controller.preferences['hide-account-names'] = self.hide_account_names
        self.controller.save()
        self.privacy_toggle.configure(image=self.privacy_icons[self.hide_account_names])
        self.draw_account_list()
        self.draw_chatgpt_accounts()
        self.claude_panel.render()
        self.grok_panel.render()
        self.refresh_api_accounts()
        self.update_tokenharbor_status()
        self.update_mode_label()
        self.update_detail_account()
        self.render_activity()
        self.render_policy_rows()
        self.notice.configure(text='Account names hidden.' if self.hide_account_names else 'Account names visible.', text_color=MUTED)

    def update_selection_style(self, account, widgets):
        selected = not self.details_collapsed and account['name'] == self.selected
        active = widgets.get('active_highlight', False)
        widgets['card'].configure(border_width=2 if active else 1,
            border_color=ACCENT if selected or active else '#344155')
        widgets['button'].configure(fg_color='#303e59' if selected else CARD, hover=not self.details_collapsed)

    def select(self, account):
        if self.details_collapsed:
            return
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
        self.detail_heading.configure(localize=False, text=self.display_name(account))
        self.detail_email = self.label(self.detail, '', color=MUTED)
        self.detail_email.pack_forget()
        status = 'Sign-in saved • account paused' if account['disabled'] else 'Sign-in saved • enabled for requests'
        self.detail_plan = self.label(self.detail, self.google_plan_name(account), 13, bold=True)
        self.detail_plan.configure(fg_color='#183b32', corner_radius=5)
        self.detail_status = self.label(self.detail, status, color=MUTED)
        self.label(self.detail, 'Remaining quota', 17, bold=True)
        cached = self.quota_cache.get(account['name'])
        self.quota_updated = self.label(self.detail, 'Loading Google quotas…', 12, MUTED)
        self.quota_updated.configure(wraplength=0)
        data = (cached or {}).get('data', {})
        self.detail_quota_layout = self.quota_layout(account['name'])
        self.detail_quota_frames = {}
        for group in self.quota_groups(account['name']):
            self.label(self.detail, group['name'], 15, bold=True)
            parent = ctk.CTkFrame(self.detail, fg_color='transparent')
            parent.pack(fill='x')
            for bucket in sorted(group['buckets'], key=lambda b: b['window'] != '5h'):
                key = (group['kind'], bucket['window'])
                self.detail_quota_widgets[key] = self.quota_row('Weekly quota' if bucket['window'] == 'weekly' else '5-hour quota', bucket, parent,
                    limit_key=(account['name'], group['kind'], bucket['window']))
                self.detail_quota_frames[key] = self.detail_quota_widgets[key][1].master
        self.label(self.detail, 'Bars show remaining quota: full = 100%. Missing percentages are shown as No data.', 12, MUTED)
        actions = ctk.CTkFrame(self.detail, fg_color='transparent')
        actions.pack(fill='x', pady=(8, 16))
        self.button(actions, 'Use only this account', lambda: self.action(lambda: self.controller.route(account['name']), 'Account selected for Claude.'), primary=True).pack(side='left', padx=(0, 10))
        self.pause_button = self.button(actions, 'Resume' if account['disabled'] else 'Pause', self.pause_selected)
        self.pause_button.pack(side='left')
        self.button(actions, 'Remove account', self.remove_selected_account).pack(side='right')
        rename_frame = ctk.CTkFrame(self.detail, fg_color='transparent')
        rename_frame.pack(fill='x', pady=(0, 20))
        entry = ctk.CTkEntry(rename_frame, placeholder_text='Account label, e.g. Personal', height=36, fg_color=CARD, border_color='#3a465c')
        entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
        entry.insert(0, self.controller.preferences.get('labels', {}).get(account['name'], ''))
        self.rename_entry = entry
        if self.hide_account_names:
            entry.delete(0, 'end')
        entry.configure(show='')
        self.button(rename_frame, 'Save label', lambda: self.rename(account, entry.get())).pack(side='left')
        self.unavailable_label = self.label(self.detail, '', color='#ffbd93')
        self.label(self.detail, 'Pausing preserves the sign-in. Switching applies to future requests; an ongoing response may finish on the previous account.', 12, MUTED)
        self.update_detail_account()
        self.after_idle(lambda: self.detail._parent_canvas.yview_moveto(position))

    def quota_row(self, model, quota, parent=None, limit_key=None):
        row = ctk.CTkFrame(parent if parent is not None else self.detail, fg_color=CARD, corner_radius=9)
        row.pack(fill='x', pady=5)
        header = ctk.CTkFrame(row, fg_color='transparent')
        header.pack(fill='x', padx=14, pady=(10, 5))
        remaining = (quota or {}).get('remaining')
        color = self.quota_color(remaining)
        ctk.CTkLabel(header, text=MODEL_LABELS.get(model, model), text_color=TEXT, font=('Segoe UI', 13), anchor='w').pack(side='left')
        value = ctk.CTkLabel(header, text='', text_color=color, font=('Segoe UI', 12, 'bold'))
        value.pack(side='right')
        bar = (self.make_quota_limit_bar(row, *limit_key, height=9, fg_color='#354157', progress_color=color)
               if limit_key else ctk.CTkProgressBar(row, height=9, fg_color='#354157', progress_color=color))
        bar.limit_key = limit_key
        bar.pack(fill='x', padx=14, pady=(0, 7))
        bar.set(remaining if remaining is not None else 0)
        if getattr(bar, 'limit_key', None):
            bar.set_floor(quota_floor(self.controller.preferences, *bar.limit_key))
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
        if getattr(bar, 'limit_key', None):
            bar.set_floor(quota_floor(self.controller.preferences, *bar.limit_key))
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
        self.detail_plan.configure(text=self.google_plan_name(account))
        email = account.get('email')
        if not self.hide_account_names and email and self.display_name(account) != email:
            self.detail_email.configure(text=email)
            if not self.detail_email.winfo_manager():
                self.detail_email.pack(fill='x', anchor='w', pady=(0, 8), after=self.detail_heading)
        else:
            self.detail_email.configure(text='')
            self.detail_email.pack_forget()
        self.rename_entry.configure(show='')
        self.detail_status.configure(text='Sign-in saved • account paused' if account['disabled'] else 'Sign-in saved • enabled for requests')
        self.pause_button.configure(text='Resume' if account['disabled'] else 'Pause')
        self.unavailable_label.configure(text='The service reported temporary unavailability. Your sign-in is saved; you can select another account.' if account.get('unavailable') else '')
        self.update_detail_quota()

    def remove_selected_account(self):
        self.remove_google_account(self.selected)

    def remove_google_account(self, name):
        if self.busy:
            return
        account = next((a for a in self.items if a['name'] == name), None)
        if not account:
            return
        name = account['name']
        identity = self.display_name(account) if self.hide_account_names else account.get('email') or self.display_name(account)
        if not messagebox.askyesno('Remove account?',
                f'Remove {identity} from Omni?\n\n'
                'Its saved sign-in will be deleted and it will no longer be used for new requests. '
                'Your Google account will not be deleted. You can add it again by signing in.\n\n'
                'An ongoing request may still finish on this account.', parent=self):
            return
        def remove():
            self.controller.remove_account(name)
            return self.controller.accounts()
        def done(items):
            self.quota_cache.pop(name, None)
            self.notice.configure(text='Account removed. You can add it again by signing in.', text_color=GREEN)
            self.loaded(items)
        self.work(remove, done, mutation=True)

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
        self.detail_quota_layout = self.quota_layout(self.selected)
        for group in self.quota_groups(self.selected):
            visible = {bucket['window'] for bucket in self.visible_quota_buckets(group)}
            for bucket in group['buckets']:
                key = (group['kind'], bucket['window'])
                frame = self.detail_quota_frames.get(key)
                if frame is None:
                    continue
                if bucket['window'] not in visible:
                    frame.pack_forget()
                elif not frame.winfo_manager():
                    options = {'fill': 'x', 'pady': 5}
                    weekly = self.detail_quota_frames.get((group['kind'], 'weekly'))
                    if bucket['window'] == '5h' and weekly.winfo_manager():
                        options['before'] = weekly
                    frame.pack(**options)
                self.update_quota_row(self.detail_quota_widgets[key], bucket)
        for model, widgets in self.model_widgets.items():
            self.update_quota_row(widgets, data.get('models', {}).get(model))

    @staticmethod
    def quota_color(remaining):
        return MUTED if remaining is None else (GREEN if remaining > .3 else '#f5c56b' if remaining > .1 else '#ff8d8d')

    def schedule_quota_render(self):
        if self.quota_render_job is None:
            self.quota_render_job = self.after(120, self.render_quota_updates)

    def render_quota_updates(self):
        self.quota_render_job = None
        if self.closed:
            return
        self.draw_account_list()
        for account_name in self.account_widgets:
            self.update_countdown(account_name)
        if self.selected:
            self.update_detail_quota()
        self.queue_policy()

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
            google_account = next((item for item in self.items if item['name'] == name), None)
            if google_account:
                status_account = dict(google_account)
                quota_data = dict(data or old.get('data') or {})
                if error and re.search(r'\bHTTP\s+(401|403)\b', error, re.I):
                    quota_data['error'] = error
                status_account['quota'] = quota_data
                bootstrap = name in getattr(self, '_telegram_google_bootstrap', set())
                getattr(self, '_telegram_google_bootstrap', set()).discard(name)
                self.observe_account_statuses('gemini', [status_account], suppress=bootstrap)
            if data is not None and not error and not data.get('summary_error'):
                self.observe_token_capacity(name, 'Google', self.google_plan_name(account), data.get('groups', []))
            if any(a['name'] == name for a in self.items):
                self.schedule_quota_render()
        self.work(fetch, done)

    def periodic_quota(self):
        if not self.busy:
            self.refresh_chatgpt_accounts()
            self.refresh_claude_accounts()
            self.refresh_grok_accounts()
            self.refresh_api_accounts()
            for account in self.items:
                self.fetch_quota(account['name'])
            # A gateway config reload can drop Claude Desktop's approved aliases.
            # Reconcile them without touching Claude's session files or preset.
            def repair_routes():
                try:
                    self.integrations.reconcile_desktop_routes()
                    return None
                except (AccountError, OSError, ValueError) as error:
                    return str(error)
            def route_done(error):
                if error and not self.closed:
                    self.notice.configure(text=error, text_color='#ffbd93')
            self.work(repair_routes, route_done)
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
            value = ctk.BooleanVar(value=False)
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
                       '\n\nRequests from selected applications will use Omni. '
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
            if not messagebox.askyesno('Restore previous settings?', 'Client configurations will be restored to their state before the first connection. Later edits to these files will also be replaced by the backup. Omni preferences will return to defaults. Google sign-ins will be preserved.\n\nRestore settings?', parent=window):
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

    def tokenharbor_settings(self, parent):
        window = ctk.CTkToplevel(self)
        window.title('TokenHarbor free model')
        window.geometry('570x560')
        window.configure(fg_color=PANEL)
        window.transient(parent)
        client = TokenHarbor(self.controller, self.integrations)
        ctk.CTkLabel(window, text='Claude Haiku 5.5 Free', font=('Segoe UI', 23, 'bold'),
                     text_color=TEXT).pack(anchor='w', padx=24, pady=(20, 8))
        ctk.CTkLabel(window, text='TokenHarbor requires a Universal Key and free-model access.\n'
                     'This is a limited-time offer with an allowance shown in TokenHarbor.\n'
                     'Only the :free route will be connected; no paid fallback is configured.',
                     justify='left', text_color=MUTED).pack(anchor='w', padx=24)
        self.button(window, 'Get TokenHarbor key',
                    lambda: webbrowser.open('https://tokenharbor.ai/signup?next=/dashboard/api-keys')).pack(
                        fill='x', padx=24, pady=(14, 8))
        entry = ctk.CTkEntry(window, placeholder_text='Paste thk_… Universal Key', show='*', height=36)
        entry.pack(fill='x', padx=24, pady=(0, 8))
        def paste_key():
            try:
                secret = window.clipboard_get().strip()
            except (tk.TclError, AttributeError):
                status.configure(text='Clipboard is empty or unavailable.', text_color='#ffbd93')
                return
            if not secret:
                status.configure(text='Clipboard is empty.', text_color='#ffbd93')
                return
            entry.delete(0, 'end')
            entry.insert(0, secret)
            entry.focus_set()
            status.configure(text='Key pasted. You can connect the free model.', text_color=MUTED)
        def paste_shortcut(_event):
            paste_key()
            return 'break'
        entry.bind('<Control-v>', paste_shortcut)
        entry.bind('<Control-V>', paste_shortcut)
        entry.bind('<Shift-Insert>', paste_shortcut)
        self.button(window, 'Paste key from clipboard', paste_key).pack(fill='x', padx=24, pady=(0, 8))
        status = ctk.CTkLabel(window, text='Connected' if client.connected() else 'Not connected',
                              text_color=GREEN if client.connected() else MUTED,
                              wraplength=520, justify='left')
        status.pack(anchor='w', padx=24)
        keys_frame = ctk.CTkScrollableFrame(window, fg_color='transparent', height=150)
        keys_frame.pack(fill='both', expand=True, padx=24, pady=(10, 0))
        ctk.CTkLabel(keys_frame, text='Connected TokenHarbor keys (rotated by gateway)',
                     text_color=TEXT, anchor='w').pack(fill='x')
        def refresh_keys():
            for child in keys_frame.winfo_children()[1:]:
                child.destroy()
            keys = client.keys()
            if not keys:
                ctk.CTkLabel(keys_frame, text='No keys connected', text_color=MUTED).pack(anchor='w', pady=3)
            for key in keys:
                row = ctk.CTkFrame(keys_frame, fg_color='transparent')
                row.pack(fill='x', pady=2)
                masked = key[:7] + '…' + key[-4:]
                ctk.CTkLabel(row, text=masked, text_color=MUTED, anchor='w').pack(side='left', fill='x', expand=True)
                self.button(row, 'Remove', lambda value=key: remove_key(value)).pack(side='right')
        def remove_key(key):
            if not messagebox.askyesno('Remove TokenHarbor key', 'Remove this key from the local gateway?', parent=window):
                return
            self.work(lambda: client.remove_key(key), lambda _: (refresh_keys(), status.configure(text='TokenHarbor key removed.', text_color=GREEN)), mutation=True)
        refresh_keys()
        footer = ctk.CTkFrame(window, fg_color=PANEL)
        footer.pack(fill='x', padx=0, pady=0)
        ctk.CTkLabel(footer,
                     text='Free account API: 60 requests/minute, 1,800/hour.\n'
                          'Haiku campaign allowance and expiry: see TokenHarbor dashboard.',
                     text_color=MUTED, justify='left').pack(anchor='w', padx=24, pady=(8, 4))
        self.button(footer, 'View current allowance',
                    lambda: webbrowser.open('https://tokenharbor.ai/dashboard')).pack(
                        fill='x', padx=24, pady=(0, 6))
        def connect():
            secret = entry.get().strip()
            if not secret:
                status.configure(text='Paste a TokenHarbor Universal Key first.', text_color='#ffbd93')
                entry.focus_set()
                return
            preset = client.approved_desktop_preset()
            affected = str(self.controller.proxy_dir / 'config.yaml')
            if preset:
                affected += '\n' + str(preset)
            warning = ('The app will send a short test request to TokenHarbor and update:\n\n' + affected +
                       '\n\nYour key will be stored in the local gateway configuration. '
                       'Requests using this model go to TokenHarbor. Its free-model terms say prompts and '
                       'responses may be retained; free access must be enabled in your TokenHarbor account. '
                       'Haiku Free is a limited-time offer with usage limits shown in your dashboard. '
                       'The selected model remains unchanged until you choose Haiku in Claude. Continue?')
            if not messagebox.askyesno('Connect TokenHarbor?', warning, parent=window):
                return
            connect_button.configure(state='disabled')
            status.configure(text='Checking the free model and connecting…', text_color=MUTED)
            def perform():
                try:
                    return client.connect(secret), None
                except Exception as error:
                    return None, str(error) if isinstance(error, AccountError) else 'Could not connect TokenHarbor.'
            def done(result):
                if not window.winfo_exists():
                    return
                desktop_updated, error = result
                connect_button.configure(state='normal')
                if error:
                    status.configure(text=error, text_color='#ffbd93')
                    return
                entry.delete(0, 'end')
                disconnect_button.configure(state='normal')
                refresh_keys()
                self.draw_tokenharbor_accounts()
                status.configure(text='Free model connected. Choose it in Claude Code /model or the Code tab.',
                                 text_color=GREEN)
                if desktop_updated and messagebox.askyesno('Reload Claude model menu?',
                        'Restart Claude Desktop to show the new model now? Running work will be interrupted.',
                        parent=window):
                    self.work(lambda: self.integrations.restart_desktop(['claude_desktop']),
                              lambda _: status.configure(text='Claude Desktop restarted. Choose Haiku in the model menu.',
                                                          text_color=GREEN))
            self.work(perform, done, mutation=True)
        connect_button = self.button(footer, 'Connect free model', connect, primary=True)
        connect_button.pack(fill='x', padx=24, pady=(0, 6))
        def disconnect():
            if not messagebox.askyesno('Remove TokenHarbor?',
                    'Remove the TokenHarbor key and model from the local gateway and connected Claude menu?',
                    parent=window):
                return
            def done(_):
                if window.winfo_exists():
                    status.configure(text='TokenHarbor removed. Restart Claude Desktop to refresh its menu.',
                                     text_color=GREEN)
                    disconnect_button.configure(state='disabled')
                self.draw_tokenharbor_accounts()
            self.work(client.disconnect, done, mutation=True)
        disconnect_button = self.button(footer, 'Remove TokenHarbor connection', disconnect)
        disconnect_button.configure(state='normal' if client.connected() else 'disabled')
        disconnect_button.pack(fill='x', padx=24, pady=(0, 8))

    def bind_account_rename(self, widget, name, provider):
        widget.bind('<Double-Button-1>', lambda event: self.edit_account_name(widget, name, provider), add='+')

    def edit_account_name(self, widget, name, provider):
        previous = getattr(self, '_inline_account_editor', None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        entry = ctk.CTkEntry(widget.master, height=20, corner_radius=4, font=('Segoe UI', 11))
        self._inline_account_editor = entry
        prefs = self.controller.preferences
        key = 'private-account-labels' if self.hide_account_names else 'api-account-labels' if ' API' in provider else 'labels'
        value = prefs.get(key, {}).get(name) or widget.cget('text')
        entry.insert(0, value)
        entry.configure(width=entry._reverse_widget_scaling(widget.winfo_width()))
        entry.place(x=entry._reverse_widget_scaling(widget.winfo_x()), y=entry._reverse_widget_scaling(widget.winfo_y()))
        def finish(event=None, save=True):
            if not entry.winfo_exists():
                return
            label = entry.get().strip()[:100]
            entry.destroy()
            if save:
                labels = prefs.setdefault(key, {})
                if label:
                    labels[name] = label
                else:
                    labels.pop(name, None)
                self.controller.save()
                self.draw_account_list()
                self.draw_chatgpt_accounts()
                self.claude_panel.render()
                self.grok_panel.render()
                self.refresh_api_accounts(use_cache=True)
                self.update_tokenharbor_names()
            return 'break'
        entry.bind('<Return>', finish)
        entry.bind('<Escape>', lambda event: finish(event, False))
        entry.bind('<FocusOut>', finish)
        entry.focus_set()
        entry.select_range(0, 'end')
        return entry

    @staticmethod
    def make_playback_icons():
        icons = {}
        for paused in (False, True):
            variants = []
            for color in ('#243247', '#edf2fa'):
                icon = Image.new('RGBA', (64, 64))
                draw = ImageDraw.Draw(icon)
                if paused:
                    draw.polygon([(20, 10), (52, 32), (20, 54)], fill=color)
                else:
                    draw.rounded_rectangle((15, 12, 26, 52), radius=3, fill=color)
                    draw.rounded_rectangle((38, 12, 49, 52), radius=3, fill=color)
                variants.append(icon.resize((32, 32), Image.Resampling.LANCZOS))
            icons[paused] = ctk.CTkImage(light_image=variants[0], dark_image=variants[1], size=(14, 14))
        for kind in ('up', 'down', 'reset', 'add', 'pin'):
            variants = []
            for color in ('#243247', '#edf2fa'):
                icon = Image.new('RGBA', (64, 64))
                draw = ImageDraw.Draw(icon)
                if kind in ('up', 'down'):
                    draw.line([(17, 34), (32, 19), (47, 34)], fill=color, width=6)
                    draw.line([(32, 20), (32, 49)], fill=color, width=6)
                    if kind == 'down':
                        icon = icon.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                elif kind == 'reset':
                    draw.arc((11, 11, 53, 53), 35, 320, fill=color, width=6)
                    draw.polygon([(45, 8), (58, 21), (40, 23)], fill=color)
                elif kind == 'pin':
                    draw.polygon([(20, 10), (44, 10), (40, 30), (50, 40), (14, 40), (24, 30)], fill=color)
                    draw.line([(32, 39), (32, 57)], fill=color, width=5)
                    icon = icon.rotate(-30, Image.Resampling.BICUBIC)
                else:
                    draw.line([(32, 13), (32, 51)], fill=color, width=6)
                    draw.line([(13, 32), (51, 32)], fill=color, width=6)
                variants.append(icon.resize((32, 32), Image.Resampling.LANCZOS))
            icons[kind] = ctk.CTkImage(light_image=variants[0], dark_image=variants[1], size=(12, 12))
        mask = Image.new('L', (64, 64))
        draw = ImageDraw.Draw(mask)
        draw.arc((11, 11, 53, 53), 35, 320, fill=255, width=6)
        draw.polygon([(45, 8), (58, 21), (40, 23)], fill=255)
        icons['reset-rainbow'] = []
        reset_mask = mask.resize((32, 32), Image.Resampling.LANCZOS)
        for phase in range(180):
            icon = Image.new('RGBA', (32, 32))
            pixels = icon.load()
            for y in range(32):
                for x in range(32):
                    alpha = reset_mask.getpixel((x, y))
                    if alpha:
                        rgb = colorsys.hsv_to_rgb((phase/180 + (x+y)/64) % 1, .72, 1)
                        pixels[x, y] = (*[round(v*255) for v in rgb], alpha)
            icons['reset-rainbow'].append(ctk.CTkImage(light_image=icon, dark_image=icon, size=(12, 12)))
        return icons

    def update_pause_button(self, button, paused):
        button.configure(text='', image=self.playback_icons[bool(paused)])

    def attach_tooltip(self, widget, description):
        tip = ctk.CTkLabel(self, text='', height=23, corner_radius=5, fg_color='#303b50', font=('Segoe UI', 10))
        widget.tooltip = tip
        def show(event=None):
            tip.configure(text=description() if callable(description) else description)
            x = widget.winfo_rootx()-self.winfo_rootx()
            y = widget.winfo_rooty()-self.winfo_rooty()
            tip.place(x=tip._reverse_widget_scaling(x), y=tip._reverse_widget_scaling(y), anchor='sw')
            tip.lift()
        widget.bind('<Enter>', show, add='+')
        widget.bind('<Leave>', lambda event: tip.place_forget(), add='+')
        widget.bind('<Button-1>', lambda event: tip.place_forget(), add='+')
        widget.bind('<Destroy>', lambda event: tip.destroy() if event.widget is widget and tip.winfo_exists() else None, add='+')

    def install_service_add_button(self, header, provider):
        services = {'google': ('Gemini', 'add_button'), 'openai': ('OpenAI', 'add_chatgpt_button'),
                    'claude-native': ('Claude', 'add_claude_button'), 'grok': ('Grok', 'add_grok_button'),
                    'tokenharbor': ('TokenHarbor', 'add_tokenharbor_button')}
        service, attribute = services[provider]
        button = self.button(header, '', lambda: self.provider_login_menu(service))
        button.configure(width=20, height=21, image=self.playback_icons['add'], fg_color='transparent', border_spacing=1)
        button.place(relx=1, rely=.5, x=-3, anchor='e')
        header.service_add = button
        setattr(self, attribute, button)
        self.attach_tooltip(button, 'Add '+service+' account')

    def account_pause_button(self, parent, name, provider):
        button = self.button(parent, '', lambda: self.pause_provider_account(name, provider))
        button.configure(width=18, height=18, corner_radius=2, fg_color='transparent',
                         image=self.playback_icons[False], border_spacing=1)
        self.attach_tooltip(button, lambda: 'Resume account' if button.cget('image') is self.playback_icons[True] else 'Pause account')
        return button

    def pause_provider_account(self, name, provider):
        if self.busy:
            return
        if provider == 'tokenharbor':
            client = TokenHarbor(self.controller, self.integrations)
            key = next((key for key in client.keys() if key_id(key) == name), None)
            if key is None:
                return
            paused = key not in client.paused_keys()
            self.work(lambda: client.set_key_paused(key, paused), lambda _: self.draw_tokenharbor_accounts(), mutation=True)
            return
        items = self.api_items if provider == 'api' else self.chatgpt_items if provider == 'openai' else self.items
        account = next((item for item in items if item['name'] == name), None)
        if account is None:
            return
        paused = not account.get('disabled')
        def apply():
            if provider == 'api':
                self.api_manager().set_paused(name, paused)
            elif provider == 'google':
                self.controller.pause(account)
            else:
                self.controller._set_disabled(account, paused)
        def done(_):
            account['disabled'] = paused
            if provider == 'api':
                self.refresh_api_accounts()
            elif provider == 'google':
                self.draw_account_list()
                self.refresh()
            else:
                self.draw_chatgpt_accounts()
                self.refresh_chatgpt_accounts()
        self.work(apply, done, mutation=True)

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
        self.set_provider_login_buttons(True)
        self.notice.configure(text='Choose your Google account in the browser and complete sign-in. It will appear here automatically.', text_color=ACCENT)
        self.login_window = ctk.CTkToplevel(self)
        self.login_window.title('Add account')
        self.login_window.geometry('480x340')
        self.login_window.resizable(False, False)
        self.login_window.configure(fg_color=PANEL)
        self.login_window.transient(self)
        ctk.CTkLabel(self.login_window, text='Complete Google sign-in', font=('Segoe UI', 22, 'bold'), text_color=TEXT).pack(pady=(26, 10))
        ctk.CTkLabel(self.login_window, text='Copy the link into MoreLogin or another browser.\nComplete Google sign-in on this computer.', font=('Segoe UI', 12), text_color=MUTED).pack(pady=(0, 8))
        link_controls = ctk.CTkFrame(self.login_window, fg_color='transparent', height=1)
        link_controls.pack(pady=(0, 10))
        self.google_open_browser_button = self.button(link_controls, 'Open browser', lambda: webbrowser.open(self.login_url))
        self.google_open_browser_button.pack(side='left', padx=(0, 6))
        self.google_copy_link_button = self.button(link_controls, 'Copy sign-in link', self.copy_google_login_link)
        self.google_copy_link_button.pack(side='left')
        ctk.CTkLabel(self.login_window, text='If localhost is blocked, paste the full callback address here.',
                    font=('Segoe UI', 12), text_color=MUTED, wraplength=430).pack(pady=(0, 4))
        callback_row = ctk.CTkFrame(self.login_window, fg_color='transparent')
        callback_row.pack(fill='x', padx=20, pady=(0, 6))
        self.google_callback_entry = ctk.CTkEntry(callback_row, placeholder_text='http://localhost:…/oauth-callback?…',
                                                 height=30)
        self.google_callback_entry.pack(side='left', fill='x', expand=True)
        self.google_paste_callback_button = self.button(callback_row, 'Paste', self.paste_google_callback)
        self.google_paste_callback_button.configure(width=58, height=30)
        self.google_paste_callback_button.pack(side='right', padx=(6, 0))
        self.google_callback_entry.bind('<Control-KeyPress>', self.google_callback_paste_key, add='+')
        self.google_callback_entry.bind('<Return>', lambda _: self.submit_google_callback())
        self.google_callback_button = self.button(self.login_window, 'Complete sign-in', self.submit_google_callback)
        self.google_callback_button.configure(height=28)
        self.google_callback_button.pack(pady=(0, 6))
        self.google_callback_status = ctk.CTkLabel(self.login_window, text='Waiting for sign-in…', text_color=MUTED,
                                                  font=('Segoe UI', 11), wraplength=440)
        self.google_callback_status.pack(fill='x', padx=20)
        self.google_callback_busy = False
        self.after(1800, self.poll_login)

    def copy_google_login_link(self):
        if self.login_url:
            self.clipboard_clear()
            self.clipboard_append(self.login_url)
            self.google_callback_status.configure(text='Link copied. Open it in your browser profile.', text_color=GREEN)

    def submit_google_callback(self):
        if not self.pending_login or self.google_callback_busy:
            return
        callback = self.google_callback_entry.get().strip()
        if not callback:
            self.google_callback_status.configure(text='Paste the full localhost callback address from the browser.', text_color='#ffbd93')
            return
        state = self.pending_login[0]
        self.google_callback_busy = True
        self.google_callback_button.configure(state='disabled')
        self.google_callback_status.configure(text='Completing sign-in…', text_color=MUTED)
        def submit():
            try:
                return self.controller.complete_google_login(callback, state), None
            except AccountError as error:
                return None, str(error)
        def done(result):
            if not self.pending_login or self.pending_login[0] != state:
                return
            answer, error = result
            if error:
                self.google_callback_busy = False
                if self.google_callback_status.winfo_exists():
                    self.google_callback_status.configure(text=error, text_color='#ffbd93')
                    self.google_callback_button.configure(state='normal')
                return
            if answer.get('completed'):
                self.finish_login('Account saved. You can select it for Claude.', True)
            elif self.google_callback_status.winfo_exists():
                self.google_callback_entry.delete(0, 'end')
                self.google_callback_status.configure(text='Callback accepted. Waiting for Google confirmation…', text_color=GREEN)
                # Keep the submit button disabled: accepted codes are single-use.
        self.work(submit, done)

    def google_callback_paste_key(self, event):
        # Tk's Ctrl-v binding depends on the active keyboard layout on Windows.
        if event.keycode == 86 or str(event.keysym).lower() == 'v':
            self.paste_google_callback()
            return 'break'

    def paste_google_callback(self):
        if self.google_callback_busy:
            return
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            self.google_callback_status.configure(text='Clipboard is empty or unavailable.', text_color='#ffbd93')
            return
        self.google_callback_entry.delete(0, 'end')
        self.google_callback_entry.insert(0, text)
        self.google_callback_entry.focus_set()

    def poll_login(self):
        if not self.pending_login or self.closed:
            return
        state, started = self.pending_login
        if time.monotonic() - started > 900:
            self.finish_login('Sign-in timed out. Click Add Google account again.', False)
            return
        def poll():
            try:
                return self.controller.login_status(state)
            except AccountError:
                return {'status': 'wait'}
        def done(result):
            if not self.pending_login or self.pending_login[0] != state:
                return
            if result.get('status') == 'ok':
                self.finish_login('Account saved. You can select it for Claude.', True)
            elif result.get('status') == 'error':
                reason = safe_detail(result.get('error') or result.get('message'))
                self.finish_login('Google sign-in failed: ' + reason if reason else
                                  'Google sign-in failed. The gateway did not report a reason.', False)
            else:
                self.after(1800, self.poll_login)
        self.work(poll, done)

    def finish_login(self, message, success):
        self.pending_login = None
        self.login_url = None
        self.set_provider_login_buttons(True)
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

    def toggle_window_pin(self):
        self.window_pinned = not self.window_pinned
        self.attributes('-topmost', self.window_pinned)
        self.pin_button.configure(fg_color=ACCENT if self.window_pinned else 'transparent')
        self.controller.preferences['window-pinned'] = self.window_pinned
        self.controller.save()

    def window_rectangle(self):
        user = ctypes.windll.user32
        user.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT]
        user.GetAncestor.restype = ctypes.wintypes.HWND
        handle = user.GetAncestor(self.winfo_id(), 2)
        rect = ctypes.wintypes.RECT()
        user.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
        user.GetWindowRect(handle, ctypes.byref(rect))
        return handle, rect

    def show_saved_window(self):
        self.deiconify()
        self.update_idletasks()
        position = self.controller.preferences.get('window-position')
        if not isinstance(position, dict) or any(type(position.get(key)) is not int for key in ('x', 'y')):
            return
        handle, rect = self.window_rectangle()
        x, y = position['x'], position['y']
        user = ctypes.windll.user32
        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', ctypes.wintypes.DWORD), ('monitor', ctypes.wintypes.RECT),
                        ('work', ctypes.wintypes.RECT), ('flags', ctypes.wintypes.DWORD)]
        target = ctypes.wintypes.RECT(x, y, x+rect.right-rect.left, y+rect.bottom-rect.top)
        user.MonitorFromRect.argtypes = [ctypes.POINTER(ctypes.wintypes.RECT), ctypes.wintypes.DWORD]
        user.MonitorFromRect.restype = ctypes.wintypes.HANDLE
        monitor = user.MonitorFromRect(ctypes.byref(target), 2)
        info = MonitorInfo(); info.size = ctypes.sizeof(info)
        user.GetMonitorInfoW.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            x = min(max(x, info.work.left), max(info.work.left, info.work.right-80))
            y = min(max(y, info.work.top), max(info.work.top, info.work.bottom-40))
        user.SetWindowPos.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.wintypes.UINT]
        user.SetWindowPos(handle, None, x, y, 0, 0, 0x0015)

    def schedule_window_position_save(self, event):
        if event.widget is not self or self.closed:
            return
        if self.position_save_job:
            self.after_cancel(self.position_save_job)
        self.position_save_job = self.after(600, self.save_window_position)

    def save_window_position(self):
        self.position_save_job = None
        if self.state() != 'normal':
            return
        _, rect = self.window_rectangle()
        position = {'x': rect.left, 'y': rect.top}
        if position != self.controller.preferences.get('window-position'):
            self.controller.preferences['window-position'] = position
            self.controller.save()

    def close(self):
        self.save_window_position()
        self.closed = True
        self.destroy()


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('GeminiAccounts.Desktop')
    ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.windll.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\GeminiAccountsDesktop')
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, 'Omni is already open. Find its window in the taskbar.', 'Omni', 0)
        return
    ctk.set_appearance_mode('dark')
    try:
        App().mainloop()
    finally:
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    main()
