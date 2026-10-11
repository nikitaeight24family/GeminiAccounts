"""GTK4 client. Launch with the packaged headless backend beside this file."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio


class Omni(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='app.omni.manager')
        self.connect('activate', self.activate)
        self.accounts = {}
        self.rows = {}
        self.groups = {}
        self.buttons = {}
        self.checks = {}
        self.applying = False
        self.request = 0
        self.settings_open = False
        self.private = False

    def send(self, action, **fields):
        self.request += 1
        self.process.stdin.write(json.dumps(dict(action=action, request=self.request, **fields))+'\n')
        self.process.stdin.flush()

    @staticmethod
    def label(value):
        return Gtk.Label(label=value, xalign=0)

    def button(self, text, action):
        button = Gtk.Button(label=text)
        button.connect('clicked', lambda _: action())
        return button

    def activate(self, _):
        if hasattr(self, 'window'):
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='Omni', default_width=1120, default_height=780)
        layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.window.set_child(layout)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidebar.set_size_request(300, -1)
        layout.append(sidebar)
        top = Gtk.Box(spacing=6); sidebar.append(top)
        title = self.label('Omni'); title.set_hexpand(True); top.append(title)
        top.append(self.button('◉', lambda: self.send('private', value=not self.private)))
        top.append(self.button('⚙', self.toggle_settings))
        self.stack = Gtk.Stack(); self.stack.set_hexpand(True); layout.append(self.stack)
        settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        settings.append(self.label('Display settings'))
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details.append(self.label('Saved accounts'))
        details.append(self.button('Automatic routing', lambda: self.send('route')))
        self.notice = self.label(''); details.append(self.notice)
        self.stack.add_named(details, 'accounts'); self.stack.add_named(settings, 'settings')
        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True); sidebar.append(scroll)
        groups = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); scroll.set_child(groups)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3); sidebar.append(footer)
        self.footers = {}
        for provider, title in [('gemini','Google Gemini'),('openai','OpenAI'),('claude','Claude'),('grok','Grok'),('tokenharbor','TokenHarbor')]:
            button = self.button('+ '+title, lambda p=provider: self.login_menu(p))
            sidebar.insert_child_after(button, top); self.buttons[provider] = button
            group = Gtk.Expander(label=title+' · 0pcs', expanded=True)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); group.set_child(body)
            groups.append(group); self.groups[provider] = (group, body)
            summary = self.label(title); footer.append(summary); self.footers[provider] = summary
            check = Gtk.CheckButton(label=title, active=True)
            check.connect('toggled', self.visibility, provider); settings.append(check); self.checks[provider] = check
        for name, values, action in [('Theme',['Dark','Light'],'theme'),('Language',['English','Русский'],'language')]:
            settings.append(self.label(name))
            choice = Gtk.DropDown.new_from_strings(values)
            choice.connect('notify::selected', lambda c, _, a=action: self.send(a, value=(['dark','light'] if a=='theme' else ['en','ru'])[c.get_selected()]) if not self.applying else None)
            settings.append(choice)
        root = Path(os.environ.get('OMNI_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
        executable = Path(__file__).with_name('Omni-Backend')
        command = [str(executable)] if executable.exists() else [sys.executable,str(root/'native_bridge.py')]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding='utf-8', cwd=root)
        def reader():
            for line in self.process.stdout:
                GLib.idle_add(self.receive, json.loads(line))
        threading.Thread(target=reader, daemon=True).start()
        self.window.connect('close-request', self.close)
        GLib.timeout_add_seconds(60, lambda: (self.send('refresh'), True)[1])
        self.window.present()

    def toggle_settings(self):
        self.settings_open = not self.settings_open
        self.stack.set_visible_child_name('settings' if self.settings_open else 'accounts')

    def visibility(self, check, provider):
        value = check.get_active()
        for widget in (self.buttons[provider], self.groups[provider][0], self.footers[provider]):
            widget.set_visible(value)
        if not self.applying:
            self.send('visibility', provider=provider, value=value)

    def login_menu(self, provider):
        popover = Gtk.Popover(); popover.set_parent(self.buttons[provider])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); popover.set_child(box)
        box.append(self.button('Sign in', lambda: (self.send('login', provider=provider), popover.popdown())))
        box.append(self.button('API key', lambda: (self.api_dialog(provider), popover.popdown())))
        popover.popup()

    def api_dialog(self, provider):
        window = Gtk.Window(title='Omni · API', transient_for=self.window, modal=True, default_width=380)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); window.set_child(box)
        label = Gtk.Entry(placeholder_text='Account name'); key = Gtk.PasswordEntry(show_peek_icon=True)
        box.append(label); box.append(key)
        box.append(self.button('Connect', lambda: (self.send('api', provider={'gemini':'Gemini','openai':'OpenAI','claude':'Claude','grok':'Grok','tokenharbor':'TokenHarbor'}[provider], key=key.get_text(), label=label.get_text()), key.set_text(''), window.close())))
        window.present()

    def rename_dialog(self, name):
        window = Gtk.Window(title='New account name', transient_for=self.window, modal=True, default_width=360)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); window.set_child(box)
        entry = Gtk.Entry(placeholder_text='New account name'); box.append(entry)
        box.append(self.button('Save',lambda:(self.send('rename',id=name,label=entry.get_text()),window.close())))
        window.present()

    def receive(self, message):
        event = message.get('event')
        if event == 'preferences':
            self.applying = True
            prefs = message['preferences']; self.private = prefs['private']
            for provider, value in prefs['visible'].items():
                self.checks[provider].set_active(value); self.visibility(self.checks[provider],provider)
            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme',prefs['theme']=='dark')
            for account in self.accounts.values():
                self.update_account(account)
            self.applying = False
        elif event == 'account':
            self.update_account(message['account'])
        elif event == 'accounts':
            for name in list(self.rows):
                if name not in message['ids']:
                    self.groups[self.accounts[name]['provider']][1].remove(self.rows.pop(name)['box'])
                    self.accounts.pop(name)
        elif event in ('error','notice') or message.get('error'):
            self.notice.set_text(message.get('message') or message['error'])
        elif 'url' in (message.get('result') or {}):
            result = message['result']; Gio.AppInfo.launch_default_for_uri(result['url'], None)
            self.notice.set_text(result.get('user_code','Complete sign-in in your browser'))
        return False

    def update_account(self, account):
        name = account['id']; provider = account['provider']; self.accounts[name] = account
        if name not in self.rows:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            line = Gtk.Box(spacing=4); box.append(line)
            title = self.label(''); title.set_hexpand(True); line.append(title)
            gesture = Gtk.GestureClick(); gesture.connect('released',lambda *_:self.rename_dialog(name)); title.add_controller(gesture)
            pause = self.button('⏸', lambda: self.send('pause',id=name)); line.append(pause)
            priority = self.label('0')
            line.append(self.button('↓',lambda:self.send('priority',id=name,delta=-1)))
            line.append(priority); line.append(self.button('↑',lambda:self.send('priority',id=name,delta=1)))
            status = self.label(''); box.append(status)
            reset = self.button('Reset usage',lambda:self.confirm_reset(name)); box.append(reset); reset.set_visible(False)
            self.groups[provider][1].append(box)
            self.rows[name] = dict(box=box,title=title,pause=pause,priority=priority,status=status,reset=reset,quotas={})
        row = self.rows[name]
        row['title'].set_text(provider+' '+str(list(self.accounts).index(name)+1) if self.private else account['label'])
        row['pause'].set_label('▶' if account['disabled'] else '⏸')
        row['priority'].set_text(str(account['priority'])); row['status'].set_text(account['plan']+' · '+account['status'])
        row['reset'].set_visible(bool(account.get('resetCredits') or account.get('resetAvailable')))
        row['reset'].set_sensitive(bool(account.get('resetAvailable')) and not account['disabled'])
        for quota in account['windows']:
            key = quota['id']
            if key not in row['quotas']:
                line = Gtk.Box(spacing=6); row['box'].append(line)
                label = self.label(''); line.append(label)
                overlay = Gtk.Overlay(); overlay.set_hexpand(True); line.append(overlay)
                bar = Gtk.ProgressBar(); overlay.set_child(bar)
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1); scale.set_draw_value(True)
                overlay.add_overlay(scale)
                scale.connect('value-changed',lambda s,n=name,k=key:self.send('floor',id=n,window=k,value=int(s.get_value())) if not self.applying else None)
                row['quotas'][key] = (label,bar,scale)
            label,bar,scale = row['quotas'][key]
            label.set_text(quota['label']+' · '+('—' if quota['remaining'] is None else str(round(quota['remaining']))+'%'))
            bar.set_fraction((quota['remaining'] or 0)/100)
            old = self.applying; self.applying = True; scale.set_value(quota['floor']); self.applying = old
        members = sorted((a for a in self.accounts.values() if a['provider']==provider),key=lambda a:(-a['priority'],a['id']))
        parent = self.groups[provider][1]; previous = None
        for member in members:
            child = self.rows[member['id']]['box']; parent.reorder_child_after(child,previous); previous=child
        self.groups[provider][0].set_label(provider+' · '+str(len(members))+'pcs')

    def close(self, _):
        self.process.stdin.close(); self.process.terminate(); return False

    def confirm_reset(self, name):
        dialog = Gtk.MessageDialog(transient_for=self.window,modal=True,buttons=Gtk.ButtonsType.YES_NO,
                                   text='Use one reset credit for this account?')
        dialog.connect('response',lambda d,response:(self.send('reset',id=name) if response==Gtk.ResponseType.YES else None,d.destroy()))
        dialog.present()


if __name__ == '__main__':
    Omni().run(sys.argv)
