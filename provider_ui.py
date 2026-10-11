"""Grok sign-in and compact management of provider API credentials."""
import time
from ui_style import ctk
from claude_ui import ClaudePanel
from grok_auth import GrokAuth
from api_accounts import APIAccounts, SERVICES
from backend import AccountError
from account_status import account_status
from isolated_browser import open_isolated


class GrokPanel(ClaudePanel):
    provider = 'grok'
    kind = 'grok'
    title = 'Grok'
    items_attribute = 'grok_items'

    windows = ()
    compact_labels = ('',)

    def setup_summary(self):
        super().setup_summary()
        group = self.app.pool_summary_groups[self.kind]
        group['compact'].destroy()
        group['compact'] = self.app.make_quota_dots(group['header'], self.compact_labels)
        self.app.show_quota_dots(group['compact'], group['collapsed'], after=group['header'])
        self.summary_status = ctk.CTkLabel(group['body'], text='', anchor='w', font=('Segoe UI', 11))
        self.summary_status.pack(fill='x')

    def pooled_values(self):
        enabled = [a for a in self.accounts if not a.get('disabled')]
        statuses = [account_status(a)[1] for a in enabled]
        value = 1 if 'normal' in statuses else 0 if statuses and all(s=='error' for s in statuses) else .5 if statuses else None
        return [value]

    def render(self):
        super().render()
        available = sum(account_status(a)[1]=='normal' for a in self.accounts)
        self.summary_status.configure(text=f'{available}/{len(self.accounts)} available · quota not reported')


class ProviderSupport:
    def refresh_grok_accounts(self):
        if not self.controller.key or self.closed or getattr(self, '_grok_refreshing', False):
            return
        self._grok_refreshing = True
        def load():
            try:
                return GrokAuth(self.controller).accounts_with_quotas(maintain_pool=True), None
            except AccountError as error:
                return None, str(error)
        def done(result):
            self._grok_refreshing = False
            accounts, error = result
            if accounts is not None:
                self.grok_items = accounts
                self.grok_panel.render()
            elif error:
                self.notice.configure(text=self.redact_private_text(error), text_color='#ffbd93')
        self.work(load, done)

    def sign_in_grok(self):
        if self.busy or self.pending_login or self.pending_chatgpt_login or self.pending_claude_login or self.pending_grok_login:
            return
        self.work(lambda: GrokAuth(self.controller).begin_login(), self.grok_login_started, mutation=True)

    def grok_login_started(self, result):
        state = result['state']
        self.pending_grok_login = (state, time.monotonic(), min(1800, max(60, result.get('expires_in', 900))))
        self.set_provider_login_buttons(False)
        window = self.grok_login_window = ctk.CTkToplevel(self)
        window.title('Grok sign-in')
        window.geometry('460x240')
        window.transient(self)
        self.label(window, 'Grok sign-in', 22, bold=True)
        self.label(window, 'Confirm the device in the separate browser window.', 12)
        code = ctk.CTkEntry(window, width=220, justify='center', font=('Segoe UI', 22, 'bold'))
        code.insert(0, result.get('user_code', ''))
        code.configure(state='readonly')
        code.pack(pady=12)
        self.button(window, 'Cancel sign-in', self.cancel_grok_login).pack(pady=8)
        window.protocol('WM_DELETE_WINDOW', self.cancel_grok_login)
        try:
            open_isolated(result['url'])
        except AccountError:
            self.cancel_grok_login()
            self.notice.configure(text='Could not open the Grok sign-in browser.', text_color='#ffbd93')
            return
        self.notice.configure(text='Complete Grok sign-in in the separate browser window.', text_color='#739aff')
        self.after(1800, self.poll_grok_login)

    def poll_grok_login(self):
        if self.closed or not self.pending_grok_login:
            return
        state, started, lifetime = self.pending_grok_login
        if time.monotonic() - started > lifetime:
            self.cancel_grok_login()
            self.notice.configure(text='Grok sign-in timed out.', text_color='#ffbd93')
            return
        def poll():
            try:
                return GrokAuth(self.controller).login_status(state)
            except AccountError:
                return {'status': 'wait'}
        def done(result):
            if not self.pending_grok_login or self.pending_grok_login[0] != state:
                return
            status = result.get('status')
            if status in ('ok', 'error'):
                self.pending_grok_login = None
                self.set_provider_login_buttons(True)
                if self.grok_login_window.winfo_exists():
                    self.grok_login_window.destroy()
                if status == 'ok':
                    self.grok_panel.collapsed = False
                    self.controller.preferences['grok-accounts-collapsed'] = False
                    self.controller.save()
                    self.refresh_grok_accounts()
                    self.notice.configure(text='Grok account added.', text_color='#66d7b0')
                else:
                    self.notice.configure(text='Grok sign-in did not finish.', text_color='#ffbd93')
            else:
                self.after(1800, self.poll_grok_login)
        self.work(poll, done)

    def cancel_grok_login(self):
        if not self.pending_grok_login:
            return
        state = self.pending_grok_login[0]
        self.pending_grok_login = None
        self.set_provider_login_buttons(True)
        if getattr(self, 'grok_login_window', None) and self.grok_login_window.winfo_exists():
            self.grok_login_window.destroy()
        self.work(lambda: GrokAuth(self.controller).cancel_login(state), lambda _: None)

    def set_provider_login_buttons(self, enabled):
        for button in (self.add_button, self.add_chatgpt_button, self.add_claude_button, self.add_grok_button):
            button.configure(state='normal' if enabled else 'disabled')

    def provider_login_menu(self, service):
        if self.busy or any((self.pending_login, self.pending_chatgpt_login, self.pending_claude_login, self.pending_grok_login)):
            return
        window = ctk.CTkToplevel(self)
        window.title(service)
        window.geometry('370x245' if service=='OpenAI' else '370x205')
        window.resizable(False, False)
        window.transient(self)
        self.label(window, service, 22, bold=True)
        self.label(window, 'Choose how to connect', 12)
        actions = {
            'Gemini': [('Sign in with Google', self.add_account)],
            'OpenAI': [('Sign in with ChatGPT', self.sign_in_chatgpt), ('Import auth.json', self.import_chatgpt_file)],
            'Claude': [('Sign in with Claude', self.sign_in_claude)],
            'Grok': [('Sign in with Grok', self.sign_in_grok)],
            'TokenHarbor': [('Free model', lambda: self.tokenharbor_settings(self))],
        }[service]
        def choose(action):
            window.destroy()
            action()
        for title, action in actions:
            self.button(window, title, lambda fn=action: choose(fn)).pack(fill='x', padx=24, pady=4)
        self.button(window, 'API key', lambda: choose(lambda: self.open_api_dialog(service))).pack(fill='x', padx=24, pady=4)

    def api_manager(self):
        return APIAccounts(self.controller, self.integrations.lock)

    def open_api_dialog(self, service):
        window = ctk.CTkToplevel(self)
        window.title(service+' · API')
        window.geometry('410x260')
        window.resizable(False, False)
        window.transient(self)
        self.label(window, service+' · API', 22, bold=True)
        label = ctk.CTkEntry(window, placeholder_text='Account name', width=350)
        label.pack(pady=6)
        key = ctk.CTkEntry(window, placeholder_text='API key', show='•', width=350)
        key.pack(pady=6)
        self.label(window, 'API billing is separate from subscriptions.', 11)
        def submit():
            if self.busy or not self.controller.key:
                return
            value, title = key.get(), label.get()
            key.delete(0, 'end')
            window.destroy()
            self.add_provider_api_key(service, value, title)
        self.button(window, 'Connect', submit, primary=True).pack(pady=8)

    def initialize_api_cards(self):
        self.api_rows = {}
        self.refresh_api_accounts()

    def provider_api_count(self, provider):
        return sum(a['provider']==provider for a in self.api_items)

    def api_card_parent(self, provider):
        return {'gemini':self.account_list, 'openai':self.chatgpt_accounts,
                'claude':self.claude_panel.body, 'grok':self.grok_panel.body,
                'tokenharbor':self.tokenharbor_accounts}[provider]

    def api_provider_collapsed(self, provider):
        return {'gemini':self.google_accounts_collapsed, 'openai':self.chatgpt_collapsed,
                'claude':self.claude_panel.collapsed, 'grok':self.grok_panel.collapsed,
                'tokenharbor':self.tokenharbor_collapsed}[provider]

    def add_provider_api_key(self, service, key, label):
        def done(_):
            provider = service.lower()
            if provider in ('claude','grok'):
                panel = self.claude_panel if provider=='claude' else self.grok_panel
                panel.collapsed = False
                self.controller.preferences[provider+'-accounts-collapsed'] = False
            elif provider=='openai':
                self.chatgpt_collapsed = False
                self.controller.preferences['chatgpt-collapsed'] = False
            elif provider=='gemini':
                self.google_accounts_collapsed = False
                self.controller.preferences['google-accounts-collapsed'] = False
            else:
                self.tokenharbor_collapsed = False
                self.controller.preferences['tokenharbor-collapsed'] = False
            self.controller.save()
            self.refresh_api_accounts()
            self.draw_chatgpt_accounts()
            self.claude_panel.render()
            self.grok_panel.render()
            self.draw_account_list()
            self.draw_tokenharbor_accounts()
            self.refresh_api_accounts(use_cache=True)
            self.notice.configure(text='API key added. Models are available through the local gateway.', text_color='#66d7b0')
        self.work(lambda: self.api_manager().add(service, key, label), done, mutation=True)

    def refresh_api_live_accounts(self):
        if not self.controller.key or self.closed or getattr(self, '_api_refreshing', False):
            return
        self._api_refreshing = True
        def load():
            try:
                return self.api_manager().accounts(live=True)
            except (AccountError, OSError, ValueError):
                return None
        def done(accounts):
            self._api_refreshing = False
            if accounts is not None:
                self.api_items = accounts
                self.refresh_api_accounts(use_cache=True)
        self.work(load, done)

    def refresh_api_accounts(self, use_cache=False):
        if not hasattr(self, 'api_rows'):
            return
        if not use_cache:
            try:
                metadata = {a['name']: a for a in self.api_items}
                self.api_items = [dict(metadata.get(a['name'], {}), **a) for a in self.api_manager().accounts()]
            except (OSError, ValueError, AccountError):
                self.api_items = []
            self.refresh_api_live_accounts()
        visible = [a for a in self.api_items if self.provider_visible(a['provider'])]
        count_signature = tuple(self.provider_api_count(p) for p in ('gemini','openai','claude','grok','tokenharbor'))
        if count_signature != getattr(self, '_api_counts', None):
            self._api_counts = count_signature
            self.draw_chatgpt_accounts()
            self.claude_panel.render()
            self.grok_panel.render()
            self.draw_tokenharbor_accounts()
            self.google_accounts_header.configure(text=('▸' if self.google_accounts_collapsed else '▾') + f'  Google Gemini · {len(self.items)+self.provider_api_count("gemini")}pcs')
        names = {a['name'] for a in visible}
        for name in list(self.api_rows):
            if name not in names:
                row = self.api_rows.pop(name)
                if row['card'].winfo_exists(): row['card'].destroy()
        for account in visible:
            name = account['name']
            if name in self.api_rows and not self.api_rows[name]['card'].winfo_exists():
                self.api_rows.pop(name)
            if name not in self.api_rows:
                card = ctk.CTkFrame(self.api_card_parent(account['provider']), fg_color='#202938', corner_radius=8, border_width=1, border_color='#344155')
                top = ctk.CTkFrame(card, fg_color='transparent')
                top.pack(fill='x', padx=6, pady=(3, 0))
                heading = ctk.CTkLabel(top, text='', localize=False, width=1, anchor='w', font=('Segoe UI', 11))
                heading.pack(side='left', fill='x', expand=True)
                self.bind_account_rename(heading, name, account['provider'].title()+' API')
                pause = self.account_pause_button(top, name, 'api')
                pause.pack(side='right')
                controls = ctk.CTkFrame(card, fg_color='transparent')
                controls.pack(fill='x', padx=6)
                counter = self.make_priority_counter(top, account, 'api')
                remove = self.button(controls, '×', lambda n=name: self.remove_api_key(n))
                remove.configure(width=18, height=18, font=('Segoe UI', 12), fg_color='transparent')
                remove.pack(side='right')
                ctk.CTkLabel(controls, text='API', height=17, corner_radius=5, fg_color='#264268', font=('Segoe UI', 9, 'bold'), width=30).pack(side='left')
                models = ctk.CTkLabel(card, text='', anchor='w', wraplength=210, font=('Segoe UI', 9))
                models.pack(fill='x', padx=6, pady=(0, 2))
                state = ctk.CTkLabel(card, text='', anchor='w', font=('Segoe UI', 10), text_color='#9daec4')
                state.pack(fill='x', padx=6, pady=(0, 3))
                self.api_rows[name] = dict(card=card, heading=heading, pause=pause, counter=counter, models=models, state=state)
            row = self.api_rows[name]
            title = self.display_name(account, account['provider'].title()+' API')
            self.update_pause_button(row['pause'], account.get('disabled'))
            row['heading'].configure(text=title, image=self.provider_icons.get(account['provider']), compound='left')
            row['counter'].configure(text=str(account['priority']))
            row['counter'].priority_down.configure(state='normal' if account['priority']>0 else 'disabled')
            row['counter'].priority_up.configure(state='normal' if account['priority']<999 else 'disabled')
            row['models'].configure(text=f"API · {len(account['models'])} models · " + ', '.join(account['models'][:1]) + ('…' if len(account['models'])>1 else ''))
            status, severity, detail = account_status(account)
            if not account.get('status'):
                status = 'Key registered' if account.get('registered') else 'Checking gateway'
                severity = 'normal' if account.get('registered') else 'muted'
            row['state'].configure(text=status, text_color={'normal':'#66d7b0','muted':'#9daec4','warning':'#f7ca70','error':'#ff6b7a'}[severity])
            self.update_active_border(row, account['name'] in self.active_account_names())
        order = tuple((a['name'],self.api_provider_collapsed(a['provider'])) for a in visible)
        if order != getattr(self, '_api_order', None):
            for row in self.api_rows.values():
                row['card'].pack_forget()
            self._api_order = order
        for account in visible:
            card = self.api_rows[account['name']]['card']
            if not self.api_provider_collapsed(account['provider']) and not card.winfo_manager():
                card.pack(fill='x', padx=1, pady=(0,2))

    def animate_api_accounts(self):
        active = self.active_account_names()
        for name, row in getattr(self, 'api_rows', {}).items():
            if not row['card'].winfo_exists(): continue
            self.update_active_border(row, name in active)

    def change_api_priority(self, name, delta):
        self.work(lambda: self.api_manager().change(name, delta), lambda _: self.refresh_api_accounts(), mutation=True)

    def remove_api_key(self, name):
        self.work(lambda: self.api_manager().remove(name), lambda _: self.refresh_api_accounts(), mutation=True)
