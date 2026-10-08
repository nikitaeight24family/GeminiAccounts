"""Terminal account manager; no GUI, Tk, desktop host or administrator required."""
import argparse
from datetime import datetime, timezone
import json
import signal
import sys
import threading
import time
import webbrowser

from activity import Activity
from backend import AccountError, Controller
from integrations import Integrations
from routing import rank_accounts, reset_date
from runtime import initialize, install_native, start_services, stop_owned
from model_names import model_name


def confirm(prompt, yes=False):
    if yes:
        return True
    try:
        return input(prompt + ' Type yes to continue: ').strip().lower() == 'yes'
    except EOFError:
        return False


def family(model):
    if model.startswith('gemini') or model == 'claude-sonnet-4-5':
        return 'gemini'
    if model.startswith(('claude', 'gpt')):
        return 'claude'


def reset_text(value, now=None, days_only=False):
    moment = reset_date(value)
    if moment is None:
        return '--'
    seconds = max(0, int((moment - (now or datetime.now(timezone.utc))).total_seconds()))
    if days_only:
        return '0d' if seconds == 0 else '< 1d' if seconds < 86400 else f'{seconds // 86400}d'
    minutes = seconds // 60
    days, hours = divmod(minutes // 60, 24)
    return f'{days}d {hours}h' if days else f'{hours}h {minutes % 60:02}m' if hours else f'{minutes}m'


class Terminal:
    def __init__(self, controller):
        self.controller = controller
        self.integrations = Integrations(controller)
        self.activity = Activity(controller.data_dir / 'activity.json')
        self.caches = {}
        self.accounts = []
        self.error = None
        self.stop = threading.Event()
        self.lock = threading.RLock()

    def update(self, quotas=True):
        with self.lock:
            accounts, records, strategy = self.controller.activity_snapshot()
            self.accounts = accounts
            state = self.activity.ingest(records, accounts)
            if not quotas:
                return
            for account in accounts:
                if account.get('access_issue') or account.get('disabled'):
                    continue
                try:
                    data = self.controller.quotas(account)
                    last_used = {}
                    for model, event in state['latest'].items():
                        actual = event.get('upstream_model') or self.controller.model_aliases().get(event.get('model') or model, event.get('model') or model)
                        group = family(actual)
                        if group and event['name'] == account['name']:
                            at = reset_date(event['at'])
                            if at:
                                last_used[group] = max(last_used.get(group, 0), at.timestamp())
                    started = self.controller.start_full_quota_windows(account, data, last_used=last_used)
                    if any(result['status'] == 200 for result in started):
                        data = self.controller.quotas(account)
                    self.caches[account['name']] = {'at': datetime.now(timezone.utc), 'data': data}
                except AccountError as error:
                    self.caches[account['name']] = {'error': str(error)}
            if self.controller.preferences.get('mode') != 'single':
                group = self.controller.preferences.get('reset-group', 'auto')
                if group not in ('gemini', 'claude'):
                    last = max(state['latest'].values(), key=lambda e: e['at'], default={})
                    actual = last.get('upstream_model') or self.controller.model_aliases().get(last.get('model', 'gemini'), last.get('model', 'gemini'))
                    group = family(actual) or 'gemini'
                rows = rank_accounts(accounts, self.caches, group)
                if rows and any(row['tier'] != 2 for row in rows):
                    self.controller.apply_reset_priority(rows)

    def monitor(self):
        try:
            self.controller.request('/usage-statistics-enabled', 'PUT', {'value': True})
        except AccountError:
            pass
        last_quotas = 0
        while not self.stop.is_set():
            try:
                now = time.monotonic()
                quotas = now - last_quotas >= 60
                self.update(quotas)
                if quotas:
                    last_quotas = now
                self.error = None
            except Exception as error:
                self.error = str(error)
            self.stop.wait(5)

    def show_status(self, refresh=True):
        if refresh:
            self.update()
        with self.lock:
            jobs = self.controller.quota_wait_status().get('jobs', [])
            running = {family(job.get('upstream_model') or self.controller.model_aliases().get(job.get('model', ''), job.get('model', '')))
                       for job in jobs if job.get('state') == 'running'}
            if self.error:
                print('Monitoring: ' + self.error)
            if not self.accounts:
                print('No accounts yet. Run: python console.py login')
                return
            for i, account in enumerate(self.accounts, 1):
                label = account.get('email') or account['name']
                issue = account.get('access_issue')
                status = issue or ('paused' if account.get('disabled') else 'ready')
                stats = self.activity.state['stats'].get(account['name'], {})
                latest = stats.get('last_model', '--')
                # Historical selections are highlighted only during real running jobs.
                selected = {}
                for event in self.activity.state['latest'].values():
                    actual = event.get('upstream_model') or self.controller.model_aliases().get(event['model'], event['model'])
                    group = family(actual)
                    if group and (group not in selected or event['at'] > selected[group]['at']):
                        selected[group] = event
                active = [group for group, event in selected.items() if group in running and event['name'] == account['name']]
                print(f'{i}. {label} [{status}]' + (' • ' + ' + '.join(active) if active else ''))
                last = reset_date(stats.get('last'))
                if last and 0 <= (datetime.now(timezone.utc) - last).total_seconds() < 60:
                    print(f'   Last model: {model_name(latest, self.controller.model_aliases())}')
                cached = self.caches.get(account['name'], {})
                if cached.get('error'):
                    print('   Quota: ' + cached['error'])
                groups = cached.get('data', {}).get('groups', [])
                for group in groups:
                    title = 'Gemini' if group['kind'] == 'gemini' else 'Claude'
                    values = []
                    for window in ('5h', 'weekly'):
                        bucket = next((b for b in group['buckets'] if b.get('window') == window), {})
                        remaining = bucket.get('remaining')
                        percent = '--' if remaining is None else f'{remaining * 100:.1f}%'
                        values.append(f'{"1w" if window == "weekly" else "5h"}: {percent} ({reset_text(bucket.get("reset"), days_only=window == "weekly")})')
                    print('   ' + title + '  ' + ' | '.join(values))
            for job in jobs:
                print(f'   Request {job.get("model", "--")}: {job.get("state", "--")}')

    def account(self, identifier):
        items = self.controller.accounts()
        found = [a for a in items if identifier in (a['name'], a.get('email'))]
        if len(found) != 1:
            raise AccountError('Account not found. Use the full email or account name from status.')
        return found[0]

    def configure(self, clients, yes=False):
        if not clients:
            detected = self.integrations.detected()
            clients = [name for name, exists in detected.items() if exists and
                       (name != 'claude_desktop' or self.integrations.windows_desktop)]
        if not clients:
            raise AccountError('No clients detected. Install a client or specify --clients claude_cli codex.')
        paths = [str(p) for client in clients for p in self.integrations.paths()[client]]
        print('Configuration files:\n  ' + '\n  '.join(paths))
        print('Selected clients will use Gemini Accounts and a new default model. Original files are backed up.\n'
              'Existing sessions and sign-ins are preserved. Restart running clients manually afterward.')
        if not confirm('Allow these configuration changes?', yes):
            print('Cancelled. Client configurations were not changed.')
            return False
        self.integrations.apply(clients)
        print('Connected: ' + ', '.join(clients) + '. Launch your clients as usual.')
        return True

    def restore(self, yes=False):
        print('Restore exact client files from before the first connection. Later edits to those files will be replaced.\n'
              'Gemini Accounts preferences reset to defaults. Google sign-ins are preserved.')
        if not confirm('Restore previous settings?', yes):
            print('Cancelled.')
            return False
        count = self.integrations.restore()
        self.controller.preferences = {'labels': {}, 'mode': 'pool', 'selected': None, 'connections-offered': True}
        self.controller.save()
        print(f'Restored {count} configuration files. Restart running clients manually.')
        return True

    def login(self):
        url, state = self.controller.begin_login()
        print('Complete Google sign-in in your browser. If it does not open, use this URL:\n' + url)
        webbrowser.open(url)
        deadline = time.monotonic() + 720
        while time.monotonic() < deadline:
            result = self.controller.login_status(state)
            if result.get('status') == 'ok':
                print('Sign-in saved.')
                for item in self.controller.reconcile_new_login():
                    print(item['name'] + ': ' + item.get('status', 'unknown'))
                for account in self.controller.accounts():
                    if account.get('access_issue') == 'verification':
                        self.verification_link(account)
                return
            if result.get('status') == 'error':
                raise AccountError('Google sign-in failed. Run login again.')
            time.sleep(2)
        raise AccountError('Google sign-in timed out. Run login again.')

    def models(self, gemini=None, claude=None, interactive=False):
        choices = self.controller.family_model_choices()
        current = self.controller.selected_family_models()
        for group in ('claude', 'gemini'):
            print('\nClaude (Antigravity)' if group == 'claude' else '\nGemini')
            for index, model in enumerate(choices[group], 1):
                print(f'{index}. {model_name(model, {})}  [{model}]')
        if interactive:
            try:
                selected = {}
                for group in ('claude', 'gemini'):
                    value = input(group.title() + ' model number (Enter keeps current): ').strip()
                    if value and not 1 <= int(value) <= len(choices[group]):
                        raise ValueError()
                    selected[group] = choices[group][int(value) - 1] if value else current[group]
                gemini, claude = selected['gemini'], selected['claude']
            except (ValueError, IndexError):
                raise AccountError('Choose a model number from the list.') from None
        if gemini or claude:
            self.controller.set_family_models(gemini or current['gemini'], claude or current['claude'])
            print('Model aliases updated for new requests. To update the Codex default, run configure --clients codex (asks permission).')

    @staticmethod
    def verification_link(account):
        url = account.get('verification_url')
        print('Google verification required for ' + (account.get('email') or account['name']))
        if url:
            print(url)
            webbrowser.open(url)
        print('After completing verification, run: python console.py verify "' + (account.get('email') or account['name']) + '"')


def parser():
    root = argparse.ArgumentParser(description='Gemini Accounts — terminal manager for Windows, macOS and Linux')
    commands = root.add_subparsers(dest='command')
    commands.add_parser('menu', help='interactive menu (default)')
    commands.add_parser('serve', help='run gateway and quota monitoring; Ctrl+C stops services started here')
    commands.add_parser('status', help='show accounts, quotas, resets and last models')
    commands.add_parser('login', help='add a Google account through browser sign-in')
    models = commands.add_parser('models', help='list or independently choose Claude and Gemini models')
    models.add_argument('--gemini', help='Gemini model ID')
    models.add_argument('--claude', help='Claude model ID in Antigravity')
    verify = commands.add_parser('verify', help='check verification after completing Google confirmation')
    verify.add_argument('account')
    verify.add_argument('--refresh-link', action='store_true', help='request and open a fresh verification URL')
    use = commands.add_parser('use', help='select one account or restore automatic routing')
    use.add_argument('account', help='email, account name, or all')
    setup = commands.add_parser('configure', help='configure clients after explicit consent')
    setup.add_argument('--clients', nargs='+', choices=['claude_cli', 'codex', 'claude_desktop'])
    setup.add_argument('--yes', action='store_true', help='explicitly approve the listed configuration changes')
    restore = commands.add_parser('restore', help='restore original client files and reset preferences')
    restore.add_argument('--yes', action='store_true', help='explicitly approve replacing configs with their backups')
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    controller = Controller()
    terminal = Terminal(controller)
    # Restoration remains available even when the native service is offline.
    if args.command == 'restore':
        return 0 if terminal.restore(args.yes) else 1
    initialize(controller)
    install_native(controller)
    owned = start_services(controller)
    command = args.command or 'menu'
    if command not in ('menu', 'serve'):
        # One-shot commands leave the local service available to connected clients.
        if command == 'status':
            terminal.show_status()
        elif command == 'login':
            terminal.login()
        elif command == 'models':
            terminal.models(args.gemini, args.claude)
        elif command == 'configure':
            return 0 if terminal.configure(args.clients, args.yes) else 1
        elif command == 'verify':
            account = terminal.account(args.account)
            if args.refresh_link:
                controller.refresh_verification_url(account)
                account = terminal.account(args.account)
                if account.get('access_issue') == 'verification':
                    terminal.verification_link(account)
                else:
                    print('Account verified. No confirmation is required.')
            else:
                controller.retry_verified_account(account)
                print('Verified and enabled (unless another account is manually selected).')
        elif command == 'use':
            controller.route(None if args.account == 'all' else terminal.account(args.account)['name'])
            print('Automatic routing enabled.' if args.account == 'all' else 'Account selected.')
        return 0
    thread = threading.Thread(target=terminal.monitor, daemon=True)
    thread.start()
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, interrupt)
    print('Gemini Accounts: http://127.0.0.1:8317 — press Ctrl+C to exit.')
    try:
        if command == 'serve':
            while not terminal.stop.wait(1):
                if any(child.poll() is not None for child in owned):
                    raise AccountError('A local service stopped. Check the runtime logs.')
        else:
            while True:
                print('\n1 Accounts & quotas  2 Add account  3 Connect clients  4 Restore settings  5 Verify account  6 Models  0 Exit')
                choice = input('> ').strip()
                try:
                    if choice == '0':
                        break
                    if choice == '1':
                        terminal.show_status()
                    elif choice == '2':
                        terminal.login()
                    elif choice == '3':
                        terminal.configure(None)
                    elif choice == '4':
                        terminal.restore()
                    elif choice == '6':
                        terminal.models(interactive=True)
                    elif choice == '5':
                        account = terminal.account(input('Account email: ').strip())
                        if confirm('Have you completed Google verification?'):
                            controller.retry_verified_account(account)
                            print('Account verified.')
                        else:
                            controller.refresh_verification_url(account)
                            terminal.verification_link(terminal.account(account['name']))
                except (AccountError, OSError, ValueError) as error:
                    print('Error: ' + str(error))
    except (KeyboardInterrupt, EOFError):
        print('\nStopping services started by this terminal…')
    finally:
        terminal.stop.set()
        thread.join(timeout=2)
        stop_owned(owned)
    return 0


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--internal-queue']:
            from quota_queue import main as queue_main
            queue_main()
            raise SystemExit(0)
        raise SystemExit(main())
    except (AccountError, OSError, ValueError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
