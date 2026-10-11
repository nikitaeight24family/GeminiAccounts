"""Headless JSON-lines interface shared by the platform-native managers.

No desktop toolkit is imported here. Network requests run away from the UI;
only sanitized account data crosses the process boundary.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from backend import Controller, AccountError
from account_status import account_status, safe_detail
from api_accounts import APIAccounts
from chatgpt_auth import ChatGPTAuth
from claude_auth import ClaudeAuth
from grok_auth import GrokAuth
from integrations import Integrations
from tokenharbor import TokenHarbor
from harbor_activity import key_id, key_label
from quota_limits import quota_floor, sync_quota_limits

SERVICES = ('gemini', 'openai', 'claude', 'grok', 'tokenharbor')


class NativeBridge:
    def __init__(self, controller=None, emit=None):
        self.controller = controller or Controller()
        self.emit = emit or self.write
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.accounts = {}
        self.refreshing = False
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.clients = {'openai': ChatGPTAuth(self.controller), 'claude': ClaudeAuth(self.controller),
                        'grok': GrokAuth(self.controller)}
        self.integrations = Integrations(self.controller)
        self.api = APIAccounts(self.controller)
        self.harbor = TokenHarbor(self.controller, self.integrations)

    def write(self, message):
        with self.output_lock:
            print(json.dumps(message, ensure_ascii=False), flush=True)

    def preferences(self):
        prefs = self.controller.preferences
        return {'theme': prefs.get('theme', 'dark'), 'language': prefs.get('language', 'en'),
                'private': prefs.get('hide-account-names', False),
                'visible': {p: prefs.get('visible-services', {}).get(p, True) for p in SERVICES},
                'collapsed': {p: prefs.get({'gemini': 'google-accounts-collapsed',
                                          'openai': 'chatgpt-collapsed'}.get(p, p+'-accounts-collapsed'), False)
                              for p in SERVICES}}

    def account_dto(self, account, provider):
        prefs = self.controller.preferences
        kind = {'gemini': 'google', 'openai': 'openai', 'claude': 'claude-native', 'grok': 'grok'}.get(provider, provider)
        quota = account.get('quota') or {}
        status, severity, detail = account_status(account)
        name = account['name']
        windows = []
        if provider == 'gemini':
            for group in quota.get('groups', []):
                for bucket in group.get('buckets', []):
                    label = '1w' if bucket.get('window') == 'weekly' else '5h'
                    remaining = bucket.get('remaining')
                    reset = bucket.get('reset')
                    try:
                        reset = datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp() if reset else None
                    except (ValueError, TypeError):
                        reset = None
                    windows.append({'id': group['kind']+'/'+bucket['window'], 'label': label,
                                    'family': group['kind'], 'remaining': remaining*100 if remaining is not None else None,
                                    'reset': reset, 'floor': quota_floor(prefs, name, group['kind'], bucket['window'])})
        else:
            for window in quota.get('windows', []):
                label = window.get('label', '')
                window_key = 'weekly' if label == '1w' else '5h'
                windows.append({'id': kind+'/'+window_key, 'label': label, 'family': provider,
                                'remaining': window.get('remaining'), 'reset': window.get('reset_at'),
                                'floor': quota_floor(prefs, name, kind, window_key)})
        return {'id': name, 'provider': provider,
                'label': prefs.get('api-account-labels' if account.get('api') else 'labels', {}).get(name) or account.get('email') or name,
                'plan': quota.get('subscription') or quota.get('plan_type') or account.get('subscription') or 'Plan unknown',
                'status': status, 'severity': severity, 'detail': detail, 'windows': windows,
                'priority': account.get('priority', 0) if account.get('api') else prefs.get('account-priorities', {}).get(name, 0),
                'disabled': bool(account.get('disabled')), 'api': bool(account.get('api')),
                'responses': account.get('success', 0), 'model': account.get('active_model', ''),
                'resetCredits': quota.get('reset_credits'), 'resetAvailable': bool(quota.get('reset_options')),
                'resetReason': quota.get('reset_error') or '',
                'active': bool(account.get('active'))}

    def publish(self, account, provider):
        with self.state_lock:
            self.accounts[account['name']] = (account, provider)
        self.emit({'event': 'account', 'account': self.account_dto(account, provider)})

    def refresh(self):
        with self.state_lock:
            if self.refreshing:
                return
            self.refreshing = True
        try:
            self.controller.prepare()
            sources = {'gemini': self.controller.accounts()}
            for provider, client in self.clients.items():
                sources[provider] = client.accounts()
            apis = self.api.accounts(live=True)
            for account in apis:
                account['api'] = True
                sources.setdefault(account['provider'], []).append(account)
            for key in self.harbor.keys():
                sources.setdefault('tokenharbor', []).append({'name': 'harbor:'+key_id(key),
                                                               'email': key_label(key), 'status': 'active',
                                                               'disabled': key in self.harbor.paused_keys()})
            names = []
            for provider, accounts in sources.items():
                for account in accounts:
                    names.append(account['name'])
                    old = self.accounts.get(account['name'])
                    if old and 'quota' in old[0]:
                        account['quota'] = old[0]['quota']
                    self.publish(account, provider)
                    if provider != 'tokenharbor' and not account.get('api'):
                        self.pool.submit(self.fetch_quota, account, provider)
            with self.state_lock:
                self.accounts = {n: item for n, item in self.accounts.items() if n in names}
            self.emit({'event': 'accounts', 'ids': names})
        except Exception as exc:
            self.emit({'event': 'error', 'message': safe_detail(exc)})
        finally:
            self.refreshing = False

    def fetch_quota(self, account, provider):
        try:
            quota = self.controller.quotas(account) if provider == 'gemini' else self.clients[provider].quota(account)
            with self.state_lock:
                if account['name'] not in self.accounts:
                    return
                account['quota'] = quota
            self.publish(account, provider)
        except Exception as exc:
            self.emit({'event': 'notice', 'message': safe_detail(exc)})

    def command(self, command):
        action = command['action']
        prefs = self.controller.preferences
        if action == 'preferences':
            return self.preferences()
        if action == 'visibility':
            provider = command['provider']
            if provider not in SERVICES:
                raise ValueError('Unknown service')
            prefs.setdefault('visible-services', {})[provider] = bool(command['value'])
        elif action in ('theme', 'language', 'private'):
            value = command['value']
            if action == 'theme' and value not in ('dark', 'light'):
                raise ValueError('Unknown theme')
            if action == 'language' and value not in ('en', 'ru'):
                raise ValueError('Unknown language')
            prefs['hide-account-names' if action == 'private' else action] = value
        elif action == 'refresh':
            self.pool.submit(self.refresh)
            return {}
        elif action == 'priority':
            name = command['id']
            account, provider = self.accounts[name]
            if account.get('api'):
                self.api.change(name, delta=int(command['delta']))
                self.pool.submit(self.refresh)
                return {}
            priorities = prefs.setdefault('account-priorities', {})
            priorities[name] = max(0, min(999, priorities.get(name, 0)+int(command['delta'])))
            self.publish(account, provider)
        elif action == 'floor':
            value = int(command['value'])
            if not 0 <= value <= 100:
                raise ValueError('Invalid reserve')
            family, window = command['window'].split('/', 1)
            name = command['id']
            prefs.setdefault('quota-floors', {}).setdefault(name, {}).setdefault(family, {})[window] = value
            account, provider = self.accounts[name]
            groups = account.get('quota', {}).get('groups', []) if provider == 'gemini' else self.clients[provider].quota_limit_groups(account.get('quota', {}))
            self.pool.submit(sync_quota_limits, self.controller, account, groups)
            self.publish(account, provider)
        elif action == 'login':
            provider = command['provider']
            result = self.controller.begin_login() if provider == 'gemini' else self.clients[provider].begin_login()
            return result if isinstance(result, dict) else {'url': result[0], 'state': result[1]}
        elif action == 'login_status':
            return self.controller.login_status(command['state'])
        elif action == 'api':
            self.api.add(command['provider'], command['key'], command.get('label', ''))
            self.pool.submit(self.refresh)
            return {}
        elif action == 'route':
            self.controller.route(command.get('id'))
            self.pool.submit(self.refresh)
            return {}
        elif action == 'rename':
            name = command['id']
            account, provider = self.accounts[name]
            label = str(command.get('label') or '').strip()[:120]
            key = 'api-account-labels' if account.get('api') else 'labels'
            prefs.setdefault(key, {})[name] = label
            self.controller.save()
            self.publish(account,provider)
            return {}
        elif action == 'pause':
            account, provider = self.accounts[command['id']]
            paused = not account.get('disabled')
            if account.get('api'):
                self.api.set_paused(account['name'], paused)
            elif provider == 'tokenharbor':
                key = next(k for k in self.harbor.keys() if 'harbor:'+key_id(k) == account['name'])
                self.harbor.set_key_paused(key, paused)
            else:
                self.controller._set_disabled(account, paused)
            account['disabled'] = paused
            self.publish(account,provider)
            self.pool.submit(self.refresh)
            return {}
        elif action == 'reset':
            account, provider = self.accounts[command['id']]
            if provider != 'openai' or account.get('api'):
                raise AccountError('Usage reset applies only to a ChatGPT subscription account.')
            result = self.clients['openai'].use_reset_credit(account)
            self.pool.submit(self.fetch_quota, account, provider)
            return {'windows_reset': result}
        elif action == 'remove':
            name = command['id']
            account, provider = self.accounts[name]
            if account.get('api'):
                self.api.remove(name)
            elif provider == 'gemini':
                self.controller.remove_account(name)
            elif provider == 'tokenharbor':
                key = next(k for k in self.harbor.keys() if 'harbor:'+key_id(k) == name)
                self.harbor.remove_key(key)
            else:
                self.controller.request('/auth-files?name='+quote(name), 'DELETE')
            self.pool.submit(self.refresh)
            return {}
        elif action == 'import':
            self.clients['openai'].import_file(Path(command['path']))
            self.pool.submit(self.refresh)
            return {}
        elif action == 'connections':
            return self.integrations.detected()
        elif action == 'connect':
            return self.integrations.apply(command['clients'])
        else:
            raise ValueError('Unknown action')
        self.controller.save()
        result = self.preferences()
        self.emit({'event': 'preferences', 'preferences': result})
        return result

    def handle(self, command):
        try:
            with self.state_lock:
                result = self.command(command)
            self.emit({'id': command.get('request'), 'result': result})
        except Exception as exc:
            self.emit({'id': command.get('request'), 'error': safe_detail(exc)})


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    bridge = NativeBridge()
    bridge.emit({'event': 'preferences', 'preferences': bridge.preferences()})
    bridge.pool.submit(bridge.refresh)
    for line in sys.stdin:
        try:
            command = json.loads(line)
            bridge.pool.submit(bridge.handle, command)
        except (ValueError, TypeError):
            bridge.emit({'event': 'error', 'message': 'Invalid command'})
    bridge.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()
