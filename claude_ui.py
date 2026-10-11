"""A retained native Claude account pool, separate from Google-provided Claude."""
from datetime import datetime, timezone
import time
import urllib.parse
from ui_style import ctk, localized_messagebox as messagebox
from claude_auth import ClaudeAuth
from account_status import account_status
from quota_limits import quota_floor
from backend import AccountError
from isolated_browser import open_isolated
from model_names import model_name

ACCENT='#739aff'
GREEN='#66d7b0'
PANEL='#191f2b'
TEXT='#edf2fa'
MUTED='#9daec4'


class ClaudePanel(ctk.CTkFrame):
    provider = "claude"
    kind = "claude-native"
    title = "Claude"
    items_attribute = "claude_items"
    windows = ("5h", "1w")
    compact_labels = ("5h", "1w")

    @property
    def accounts(self):
        return getattr(self.app, self.items_attribute)

    def __init__(self, app):
        super().__init__(app.sidebar, fg_color='transparent')
        self.app = app
        self.rows = {}
        self.collapsed = app.controller.preferences.get(self.provider+'-accounts-collapsed', True)
        self.header = app.button(self, '', self.toggle)
        self.header.configure(image=app.provider_icons[self.provider], compound='left', height=27,
                              anchor='w', font=('Segoe UI', 11, 'bold'), fg_color='#303b50')
        self.header.pack(fill='x', padx=1, pady=(1, 2))
        self.compact = app.make_quota_dots(self.header, self.compact_labels)
        self.body = ctk.CTkScrollableFrame(self, height=180, fg_color='transparent')
        self.setup_summary()
        self.render()

    def setup_summary(self):
        app = self.app
        body = app.create_pool_summary(self.kind, self.title)
        app.pool_summary_groups[self.kind]['frame'].pack(fill='x', padx=18, pady=(0, 3), before=app.tokenharbor_accounts)
        self.summary = {}
        for window in self.windows:
            title = ctk.CTkLabel(body, text=window, height=18, anchor='w', font=('Segoe UI', 11))
            title.pack(fill='x')
            bar = ctk.CTkProgressBar(body, height=6, fg_color='#354157', progress_color=GREEN)
            bar.pack(fill='x', pady=(1, 6))
            self.summary[window] = (title, bar)

    def pooled_values(self):
        values = []
        for label in self.windows:
            remaining = [w['remaining']/100 for a in self.accounts
                         if not a.get('disabled') and not (a.get('quota') or {}).get('error')
                         for w in (a.get('quota') or {}).get('windows', []) if w['label']==label]
            values.append(sum(remaining)/len(remaining) if remaining else None)
        return values

    def toggle(self):
        self.collapsed = not self.collapsed
        self.app.controller.preferences[self.provider+'-accounts-collapsed'] = self.collapsed
        self.app.controller.save()
        self.render()
        self.app.refresh_api_accounts(use_cache=True)

    def render(self):
        app = self.app
        if not app.provider_visible(self.provider):
            self.pack_forget()
            return
        if not self.winfo_manager():
            before = app.google_accounts_header if app.google_accounts_header.winfo_manager() else app.sidebar_spacer
            self.pack(fill='x', padx=12, pady=(0, 3), before=before)
        accounts = sorted(self.accounts, key=lambda a: (-app.account_priority(a), a.get('email') or a['name']))
        self.header.configure(text=('▸' if self.collapsed else '▾')+f'  {self.title} · {len(accounts)+app.provider_api_count(self.provider)}pcs')
        app.show_quota_dots(self.compact, self.collapsed, after=self.header)
        values = self.pooled_values()
        app.set_quota_dots(self.compact, values)
        app.set_quota_dots(app.pool_summary_groups[self.kind]['compact'], values)
        for (window, (title, bar)), value in zip(self.summary.items(), values):
            percent = app.quota_percent(value) if value is not None else 'No data'
            title.configure(text=f'{window} · {percent}', text_color=app.quota_color(value))
            bar.configure(progress_color=app.quota_color(value))
            bar.set(value or 0)
        names = {a['name'] for a in accounts}
        for name in list(self.rows):
            if name not in names:
                self.rows.pop(name)['card'].destroy()
        for account in accounts:
            name = account['name']
            if name not in self.rows:
                card = ctk.CTkFrame(self.body, fg_color='#202938', corner_radius=8,
                                     border_width=1, border_color='#344155')
                heading_row = ctk.CTkFrame(card, fg_color='transparent')
                heading_row.pack(fill='x', padx=6, pady=(3, 0))
                heading = ctk.CTkLabel(heading_row, text='', localize=False, height=20, width=1,
                                      anchor='w', font=('Segoe UI', 11), image=app.provider_icons[self.provider], compound='left')
                heading.pack(side='left', fill='x', expand=True)
                app.bind_account_rename(heading, name, self.title)
                status_line = ctk.CTkFrame(card, fg_color='transparent')
                status_line.pack(fill='x', padx=6)
                priority = app.make_priority_counter(heading_row, account, self.kind)
                pause = app.account_pause_button(heading_row, name, self.kind)
                pause.configure(command=lambda n=name: self.pause_account(n))
                pause.configure(width=18, height=18, font=('Segoe UI', 10), fg_color='transparent')
                pause.pack(side='right')
                remove = app.button(status_line, '×', lambda n=name: self.remove_account(n))
                remove.configure(width=18, height=18, font=('Segoe UI', 12), fg_color='transparent')
                remove.pack(side='right')
                plan = ctk.CTkLabel(status_line, text='', width=1, height=17, corner_radius=5,
                                   font=('Segoe UI', 9, 'bold'), fg_color='#654332', text_color='#edf2fa')
                plan.pack(side='left', padx=(0, 4))
                status = ctk.CTkLabel(card, text='', height=17, font=('Segoe UI', 10), anchor='w')
                status.pack(fill='x', padx=6)
                model = ctk.CTkLabel(card, text='', height=15, font=('Segoe UI', 9, 'bold'), anchor='w', text_color='#bac9df')
                windows = {}
                for label in self.windows:
                    line = ctk.CTkFrame(card, fg_color='transparent')
                    line.pack(fill='x', padx=6, pady=(0, 1))
                    value = ctk.CTkLabel(line, text='', width=65, height=15, anchor='w', font=('Segoe UI', 10))
                    value.pack(side='left')
                    bar = app.make_quota_limit_bar(line, name, self.kind, 'weekly' if label=='1w' else '5h', width=68)
                    bar.pack(side='left', padx=(1, 4))
                    timer = ctk.CTkLabel(line, text='', width=1, height=15, anchor='e', font=('Segoe UI', 10), text_color='#9daec4')
                    timer.pack(side='right', fill='x', expand=True)
                    windows[label] = (value, bar, timer)
                error = ctk.CTkLabel(card, text='', height=16, font=('Segoe UI', 9), text_color='#f7ca70', anchor='w')
                self.rows[name] = dict(card=card, heading=heading, plan=plan, status=status,
                                       priority=priority, model=model, windows=windows, error=error, pause=pause)
            row = self.rows[name]
            quota = account.get('quota') or {}
            row['heading'].configure(text=app.display_name(account, self.title))
            app.update_pause_button(row['pause'], account.get('disabled'))
            row['plan'].configure(text=' '+str(quota.get('plan_type') or account.get('plan_type') or 'Plan unknown')+' ')
            status, severity, _ = account_status(account)
            if quota.get('reserved') and severity!='error':
                status, severity = 'Quota reserve reached', 'warning'
            color = {'error':'#ff6b7a','warning':'#f7ca70','normal':'#66d7b0','muted':'#9daec4'}[severity]
            row['status'].configure(text=f'{status} · {account.get("success") or 0} responses', text_color=color)
            app.update_priority_counter(row['priority'], account)
            lookup = {w['label']:w for w in quota.get('windows', [])}
            for label, (value, bar, timer) in row['windows'].items():
                window = lookup.get(label, {})
                remaining = window.get('remaining')
                color = app.quota_color(remaining/100 if remaining is not None else None)
                value.configure(text=f'{label} · {remaining:.0f}%' if remaining is not None else label+' · No data', text_color=color)
                bar.configure(progress_color=color)
                bar.set(remaining/100 if remaining is not None else 0)
                bar.set_floor(quota_floor(app.controller.preferences, name, self.kind, 'weekly' if label=='1w' else '5h'))
                try:
                    reset = datetime.fromtimestamp(window['reset_at'], timezone.utc).isoformat()
                    timer.configure(text=app.time_until_reset(reset))
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    timer.configure(text='—')
            if quota.get('error'):
                row['error'].configure(text=str(quota['error']))
                if not row['error'].winfo_manager(): row['error'].pack(fill='x', padx=6)
            else:
                row['error'].pack_forget()
        order = (self.collapsed, tuple(a['name'] for a in accounts))
        if getattr(self, '_order', None)!=order:
            for row in self.rows.values(): row['card'].pack_forget()
            if not self.collapsed:
                for account in accounts: self.rows[account['name']]['card'].pack(fill='x', padx=1, pady=(0, 2))
            self._order = order
        if self.collapsed or not (accounts or app.provider_api_count(self.provider)):
            self.body.pack_forget()
        elif not self.body._parent_frame.winfo_manager():
            self.body.configure(height=min(230, 120*len(accounts)))
            self.body.pack(fill='x')
        self.animate()

    def refresh(self):
        getattr(self.app, 'refresh_'+self.provider+'_accounts')()

    def pause_account(self, name):
        account = next((a for a in self.accounts if a['name'] == name), None)
        if account is not None:
            self.app.work(lambda: self.app.controller._set_disabled(account, not account.get('disabled')),
                          lambda _: self.refresh(), mutation=True)

    def remove_account(self, name):
        account = next((a for a in self.accounts if a['name'] == name), None)
        if account is None or not messagebox.askyesno('Remove account?',
                'Remove '+self.app.display_name(account, self.title)+' from Omni?', parent=self.app):
            return
        def remove():
            self.app.controller.request('/auth-files?'+urllib.parse.urlencode({'name': name}), 'DELETE')
            for field in ('account-priorities', 'quota-floors'):
                self.app.controller.preferences.get(field, {}).pop(name, None)
            self.app.controller.save()
        self.app.work(remove, lambda _: self.refresh(), mutation=True)

    def animate(self):
        app = self.app
        active = app.active_provider_accounts().get(self.provider)
        for name, row in self.rows.items():
            caption = app.last_account_model(name)
            if name==active:
                actual = next((job.get('upstream_model') or app.model_aliases.get(job.get('model'), job.get('model', ''))
                               for job in app.gateway_jobs if job.get('state')=='running'
                               and app.model_family(job.get('upstream_model') or app.model_aliases.get(job.get('model'), job.get('model', '')))==self.provider), '')
                if actual: caption = model_name(actual, app.model_aliases)
            row['model'].configure(text=caption)
            if caption and not row['model'].winfo_manager(): row['model'].pack(fill='x', padx=6, before=row['status'])
            elif not caption: row['model'].pack_forget()
            app.update_active_border(row, name==active)


class ClaudeSupport:
    def refresh_claude_accounts(self):
        if not self.controller.key or self.closed: return
        def done(accounts):
            self.claude_items = accounts
            self.claude_panel.render()
        self.work(lambda: ClaudeAuth(self.controller).accounts_with_quotas(maintain_pool=True), done)

    def sign_in_claude(self):
        if self.busy or self.pending_login or self.pending_chatgpt_login or self.pending_claude_login or self.pending_grok_login:
            return
        self.work(lambda: ClaudeAuth(self.controller).begin_login(), self.claude_login_started, mutation=True)

    def claude_login_started(self, result):
        url, state = result
        self.pending_claude_login = (state, time.monotonic())
        self.set_provider_login_buttons(False)
        self.add_button.configure(state='disabled')
        self.add_claude_button.configure(state='disabled')
        self.add_chatgpt_button.configure(state='disabled')
        try:
            open_isolated(url)
        except AccountError as error:
            self.pending_claude_login = None
            self.add_button.configure(state='normal')
            self.add_claude_button.configure(state='normal')
            self.add_chatgpt_button.configure(state='normal')
            self.notice.configure(text=str(error), text_color='#ffbd93')
            self.work(lambda: ClaudeAuth(self.controller).cancel_login(state), lambda _: None)
            return
        self.notice.configure(text='Complete Claude sign-in in the separate browser window. The account will appear here automatically.',
                              text_color=ACCENT)
        self.claude_login_window = ctk.CTkToplevel(self)
        self.claude_login_window.title('Claude sign-in')
        self.claude_login_window.geometry('470x235')
        self.claude_login_window.resizable(False, False)
        self.claude_login_window.configure(fg_color=PANEL)
        self.claude_login_window.transient(self)
        self.claude_login_window.protocol('WM_DELETE_WINDOW', self.cancel_claude_login)
        ctk.CTkLabel(self.claude_login_window, text='Complete Claude sign-in',
                     font=('Segoe UI', 21, 'bold'), text_color=TEXT).pack(pady=(25, 10))
        ctk.CTkLabel(self.claude_login_window,
                     text='Enter your email, password and 2FA code in the separate browser.\nThis app never receives your password or 2FA code.',
                     font=('Segoe UI', 12), text_color=MUTED, justify='center').pack(pady=(0, 12))
        self.button(self.claude_login_window, 'Cancel sign-in', self.cancel_claude_login).pack(pady=(0, 8))
        ctk.CTkLabel(self.claude_login_window, text='Waiting for sign-in…',
                     text_color=MUTED, font=('Segoe UI', 11)).pack()
        self.after(1800, self.poll_claude_login)

    def poll_claude_login(self):
        if not self.pending_claude_login or self.closed:
            return
        state, started = self.pending_claude_login
        if time.monotonic() - started > 900:
            self.finish_claude_login('Claude sign-in timed out. Try adding the account again.', False)
            return
        def poll():
            try:
                return ClaudeAuth(self.controller).login_status(state)
            except AccountError:
                return {'status': 'wait'}
        def done(result):
            if not self.pending_claude_login or self.pending_claude_login[0] != state:
                return
            if result.get('status') == 'ok':
                self.finish_claude_login('Claude account added. Reconnect applications to show its Claude models.', True)
            elif result.get('status') == 'error':
                self.finish_claude_login('Claude sign-in did not finish. Try again.', False)
            else:
                self.after(1800, self.poll_claude_login)
        self.work(poll, done)

    def cancel_claude_login(self):
        if not self.pending_claude_login:
            return
        state = self.pending_claude_login[0]
        self.finish_claude_login('Claude sign-in cancelled.', False)
        self.work(lambda: ClaudeAuth(self.controller).cancel_login(state), lambda _: None)

    def finish_claude_login(self, message, success):
        self.pending_claude_login = None
        self.set_provider_login_buttons(True)
        self.add_button.configure(state='normal')
        self.add_claude_button.configure(state='normal')
        self.add_chatgpt_button.configure(state='normal')
        if hasattr(self, 'claude_login_window') and self.claude_login_window.winfo_exists():
            self.claude_login_window.destroy()
        self.notice.configure(text=message, text_color=GREEN if success else '#ffbd93')
        if success:
            self.claude_panel.collapsed = False
            self.controller.preferences['claude-accounts-collapsed'] = False
            self.controller.save()
            self.refresh_claude_accounts()

