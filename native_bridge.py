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
from urllib.parse import quote, urlencode, urlsplit, parse_qs

from backend import Controller, AccountError, atomic_write, dpapi
from account_status import account_status, google_account_status, safe_detail
from api_accounts import APIAccounts
from chatgpt_auth import ChatGPTAuth
from claude_auth import ClaudeAuth
from grok_auth import GrokAuth
from integrations import Integrations
from tokenharbor import TokenHarbor
from harbor_activity import key_id, key_label
from quota_limits import quota_floor, sync_quota_limits
from chatgpt_oauth_pending import PendingChatGPTLogins
from account_uptime import update_uptime
from telegram_notifications import TelegramBot
from connection_health import ConnectionHealth
from activity import Activity
from isolated_browser import open_isolated
from account_archive import read_archive, write_archive

SERVICES = ('gemini', 'openai', 'claude', 'grok', 'tokenharbor')
API_SERVICES = dict(zip(SERVICES, ('Gemini', 'OpenAI', 'Claude', 'Grok', 'TokenHarbor')))


class NativeBridge:
    def __init__(self, controller=None, emit=None):
        self.controller = controller or Controller()
        self.emit = emit or self.write
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.accounts = {}
        self.cache_path = self.controller.data_dir / 'account-display-cache.dpapi'
        try:
            saved = json.loads(dpapi(self.cache_path.read_bytes(), decrypt=True))
            self.cached_accounts = {item['id']: item for item in saved if isinstance(item, dict)
                                    and isinstance(item.get('id'), str) and item.get('provider') in SERVICES}
        except (OSError, ValueError, AccountError, TypeError):
            self.cached_accounts = {}
        self.startup_accounts = list(self.cached_accounts.values())
        self.initial_inventory_complete = False
        self.cache_timer = None
        self.refreshing = False
        self.quota_pending = set()
        self.quota_attempts = {}
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.clients = {'openai': ChatGPTAuth(self.controller), 'claude': ClaudeAuth(self.controller),
                        'grok': GrokAuth(self.controller)}
        self.integrations = Integrations(self.controller)
        self.connections = ConnectionHealth(self.integrations)
        self.stop_event = threading.Event()
        self.maintenance_thread = None
        self.activity_thread = None
        self.activity = Activity(self.controller.data_dir / "activity.json")
        self.activity_lock = threading.Lock()
        self.live_activity = {}
        self.api = APIAccounts(self.controller)
        self.harbor = TokenHarbor(self.controller, self.integrations)
        self.pending_logins = PendingChatGPTLogins(self.controller.data_dir / 'chatgpt-pending-logins.json')
        self.completed_logins = {}
        self.telegram = TelegramBot(self.controller.data_dir / 'telegram-bot-token.bin')

    def write(self, message):
        with self.output_lock:
            print(json.dumps(message, ensure_ascii=False), flush=True)

    def preferences(self):
        prefs = self.controller.preferences
        from remote_server import get_client_snippets
        remote_server = prefs.get('remote-server') or {}
        snippets = get_client_snippets(remote_server.get('host', ''), remote_server.get('client_key', '')) if remote_server.get('host') else None
        return {'theme': prefs.get('theme', 'dark'), 'language': prefs.get('language', 'en'),
                'telegram': {'enabled':bool(prefs.get('telegram-alerts-enabled')), 'chatId':prefs.get('telegram-chat-id',''), 'tokenSaved':self.telegram.token_saved()},
                'private': prefs.get('hide-account-names', False),
                'visible': {p: prefs.get('visible-services', {}).get(p, True) for p in SERVICES},
                'summaryCollapsed': {p: prefs.get(('google' if p=='gemini' else p)+'-pool-collapsed', True) for p in SERVICES},
                'collapsed': {p: prefs.get({'gemini': 'google-accounts-collapsed',
                                          'openai': 'chatgpt-collapsed','openai-free':'chatgpt-free-collapsed','tokenharbor':'tokenharbor-collapsed'}.get(p, p+'-accounts-collapsed'), p!='gemini')
                              for p in SERVICES + ('openai-free',)},
                'backendMode': prefs.get('backend-mode', 'local'),
                'remoteBackendStatus': prefs.get('remote-backend-status', {
                    'mode': prefs.get('backend-mode', 'local'),
                    'connected': prefs.get('backend-mode', 'local') == 'local'
                }),
                'remoteServer': remote_server,
                'remoteServerConfig': prefs.get('remote-server-config', {}),
                'remoteSnippets': snippets}

    def account_dto(self, account, provider):
        prefs = self.controller.preferences
        kind = {'gemini': 'google', 'openai': 'openai', 'claude': 'claude-native', 'grok': 'grok'}.get(provider, provider)
        quota = account.get('quota') or {}
        status, severity, detail = google_account_status(account, quota.get('groups', [])) if provider == 'gemini' else account_status(account)
        # OpenAI can briefly report an expired/invalidated token while its
        # refresh is still in progress.  The gateway keeps the credential
        # active in that interval; do not present a destructive "Sign in
        # again" action until the credential itself is marked unavailable or
        # a subsequent verification confirms the 401.
        quota_auth_failure = str(quota.get('error') or '').lower()
        confirmed_auth_failure = ('http 401' in quota_auth_failure or
                                  'token_revoked' in quota_auth_failure or
                                  'invalidated oauth token' in quota_auth_failure)
        if (provider == 'openai' and status == 'Sign in again' and
                str(account.get('status') or '').lower() in ('active', 'available', 'ok') and
                not account.get('unavailable') and not confirmed_auth_failure):
            status, severity = 'Checking sign-in', 'warning'
        if not account.get('disabled') and severity not in ('error',) and status not in ('Verification required', 'Access denied'):
            if quota.get('error') or (provider == 'gemini' and quota.get('summary_error') and not quota.get('groups')):
                quota_detail = safe_detail(quota.get('error') or quota.get('summary_error'))
                if provider == 'openai' and ('http 401' in quota_detail.lower() or
                                             'token_revoked' in quota_detail.lower() or
                                             'invalidated oauth token' in quota_detail.lower()):
                    status, severity, detail = 'Sign in again', 'error', quota_detail
                else:
                    status, severity, detail = 'Quota unavailable', 'warning', quota_detail
            elif not quota and not account.get('api') and provider != 'tokenharbor' and status == 'Available':
                status, severity, detail = 'Loading quota', 'muted', ''
        name = account['name']
        private_provider = {'gemini':'Google','openai':'OpenAI','claude':'Claude','grok':'Grok','tokenharbor':'TokenHarbor'}[provider]
        numbers = prefs.setdefault('private-account-numbers', {}).setdefault(private_provider,{})
        if name not in numbers:
            numbers[name] = max(numbers.values(), default=0)+1
            self.controller.save()
        private_label = prefs.get('private-account-labels',{}).get(name) or f'{private_provider} {numbers[name]}'
        windows = []
        if provider == 'gemini':
            for group in quota.get('groups', []):
                for bucket in group.get('buckets', []):
                    window_name = bucket.get('window')
                    label = '1mo' if window_name == 'monthly' else '1w' if window_name == 'weekly' else '5h'
                    remaining = bucket.get('remaining')
                    reset = bucket.get('reset')
                    try:
                        reset = datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp() if reset else None
                    except (ValueError, TypeError):
                        reset = None
                    windows.append({'id': str(group.get('kind', ''))+'/'+str(window_name or ''), 'label': label,
                                    'family': group.get('kind', ''), 'remaining': remaining*100 if remaining is not None else None,
                                    'reset': reset, 'floor': quota_floor(prefs, name, group.get('kind', ''), window_name)})
        else:
            for window in quota.get('windows', []):
                label = window.get('label', '')
                window_key = 'weekly' if label == '1w' else 'monthly' if label == '1mo' else '5h'
                windows.append({'id': kind+'/'+window_key, 'label': label, 'family': provider,
                                'remaining': window.get('remaining'), 'reset': window.get('reset_at'),
                                'floor': quota_floor(prefs, name, kind, window_key)})

        def window_sort_key(w):
            f = str(w.get('family') or provider or '').lower()
            family_rank = 0 if f in ('gemini', 'google') else 1 if f in ('claude', 'claude-native') else 2
            lbl = str(w.get('label') or '').lower()
            window_rank = 0 if lbl == '5h' or '5h' in lbl or 'hour' in lbl else \
                          1 if lbl == '1w' or '1w' in lbl or 'week' in lbl else \
                          2 if lbl == '1mo' or '1mo' in lbl or 'month' in lbl else 3
            return (family_rank, window_rank, str(w.get('id', '')))

        windows.sort(key=window_sort_key)
        duration, changed = update_uptime(prefs.setdefault('account-uptime', {}), account, time.time())
        if changed:
            self.controller.save()
        live = self.live_activity.get(name, {})
        usage_tokens = max(0, int(live.get('tokens', 0) or 0))
        return {'id': name, 'provider': provider,
                'label': prefs.get('api-account-labels' if account.get('api') else 'labels', {}).get(name) or account.get('email') or name,
                'customLabel': prefs.get('api-account-labels' if account.get('api') else 'labels', {}).get(name) or '',
                'plan': quota.get('subscription') or quota.get('plan_type') or account.get('plan_type') or account.get('subscription') or 'Plan unknown',
                'privateLabel': private_label,
                'uptime': duration,
                'status': status, 'severity': severity, 'detail': detail, 'windows': windows,
                'priority': account.get('priority', 0) if account.get('api') else prefs.get('account-priorities', {}).get(name, 0),
                'disabled': bool(account.get('disabled')), 'api': bool(account.get('api')),
                'responses': max(account.get('success', 0), live.get('responses', 0)), 'tokens': usage_tokens,
                'model': live.get('model', ''),
                'activity': live.get('state', 'idle'),
                'resetCredits': quota.get('reset_credits'), 'resetAvailable': bool(quota.get('reset_options')),
                'resetReason': quota.get('reset_error') or '',
                'active': live.get('state') in ('running', 'recent')}

    def publish(self, account, provider):
        dto = self.account_dto(account, provider)
        with self.state_lock:
            self.accounts[account['name']] = (account, provider)
            cached = self.cached_accounts.get(account['name'])
            # The first inventory pass has no quota yet. Keep the last known
            # display values until the independent quota task returns.
            if (cached and cached.get('provider') == provider and not account.get('_omni_quota_refreshed')
                    and not (account.get('quota') or {}).get('windows')
                    and not (account.get('quota') or {}).get('groups')
                    and dto['severity'] != 'error' and dto['status'] not in ('Verification required', 'Access denied')):
                keys = ['windows', 'plan', 'resetCredits', 'resetAvailable', 'resetReason']
                if dto['status'] in ('Available', 'Loading quota'):
                    keys += ['status', 'severity', 'detail']
                for key in keys:
                    dto[key] = cached.get(key, dto.get(key))
            if cached != dto:
                self.cached_accounts[account['name']] = dto
                if self.initial_inventory_complete:
                    self.schedule_cache_save()
        if cached != dto:
            self.emit({'event': 'account', 'account': dto})

    def _refresh_openai_priorities(self):
        """Reconcile provider priorities away from the UI command thread."""
        try:
            with self.state_lock:
                accounts = [account for account, provider in self.accounts.values()
                            if provider == 'openai' and not account.get('api')]
            if accounts:
                self.clients['openai'].apply_reset_priority(accounts)
        except Exception:
            # The clicked value is already persisted locally. A later refresh
            # will retry the remote reconciliation without delaying the UI.
            pass

    def schedule_cache_save(self):
        if self.cache_timer:
            self.cache_timer.cancel()
        self.cache_timer = threading.Timer(1.0, self.save_account_cache)
        self.cache_timer.daemon = True
        self.cache_timer.start()

    def save_account_cache(self):
        with self.state_lock:
            snapshot = list(self.cached_accounts.values())
            self.cache_timer = None
            try:
                atomic_write(self.cache_path, dpapi(json.dumps(snapshot, ensure_ascii=False).encode('utf-8')))
            except (OSError, AccountError):
                pass

    def refresh(self):
        with self.state_lock:
            if self.refreshing:
                return
            self.refreshing = True
        try:
            self.controller.prepare()
            sources = {'gemini': self.controller.accounts()}
            for provider, client in self.clients.items():
                try:
                    sources[provider] = client.accounts()
                except Exception as exc:
                    self.emit({'event':'notice','message':provider+': '+safe_detail(exc)})
                    sources[provider] = [a for a,p in self.accounts.values() if p==provider]
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
                        self.schedule_quota(account, provider)
            with self.state_lock:
                self.accounts = {n: item for n, item in self.accounts.items() if n in names}
                if any(n not in names for n in self.cached_accounts):
                    self.cached_accounts = {n: item for n, item in self.cached_accounts.items() if n in names}
                self.initial_inventory_complete = True
                self.schedule_cache_save()
            self.emit({'event': 'accounts', 'ids': names})
            self.emit({'event': 'ready'})
        except Exception as exc:
            self.emit({'event': 'error', 'message': safe_detail(exc)})
        finally:
            with self.state_lock:
                self.refreshing = False

    def review_login(self, provider, started_at):
        """Check the newly created credential without exposing identity or tokens to Electron."""
        gateway_provider = {'gemini': {'antigravity'}, 'openai': {'codex'},
                            'claude': {'claude', 'anthropic'}, 'grok': {'xai'}}[provider]
        rows = self.controller.request('/auth-files').get('files', [])
        candidates = []
        recent_candidates = []
        for row in rows:
            if row.get('provider', row.get('type')) not in gateway_provider:
                continue
            timestamps = []
            for field in ('created_at', 'updated_at', 'last_refresh', 'modified_at'):
                try:
                    raw = row.get(field)
                    if raw:
                        timestamps.append(datetime.fromisoformat(str(raw).replace('Z', '+00:00')).timestamp())
                except (AttributeError, ValueError, TypeError, OverflowError):
                    pass
            if any(started_at - 60 <= stamp <= time.time() + 10 for stamp in timestamps):
                candidates.append(row)
            elif row.get('auth_index') and timestamps and max(timestamps) >= started_at - 300:
                recent_candidates.append(row)
        if not candidates and len(recent_candidates) == 1:
            candidates = recent_candidates
        if not candidates:
            return {'status': 'checking'}
        if len(candidates) != 1:
            return {'status': 'uncertain'}
        account = candidates[0]
        identity = account.get('account') if provider == 'openai' and account.get('account') else account.get('email')
        duplicate = bool(identity and any(
            other is not account and other.get('provider', other.get('type')) in gateway_provider
            and str((other.get('account') if provider == 'openai' and other.get('account') else other.get('email')) or '').casefold() == str(identity).casefold()
            for other in rows))
        status, _, detail = account_status(account)
        if status in ('Sign in again', 'Access denied', 'Account blocked', 'Verification required'):
            return {'status': 'error', 'reason': status, 'duplicate': duplicate}
        if not account.get('auth_index'):
            return {'status': 'checking', 'duplicate': duplicate}
        try:
            if provider == 'gemini':
                self.controller.check_verified_account(account)
                verified = True
            elif provider in ('openai', 'claude'):
                quota = self.clients[provider].quota(account)
                if str(quota.get('error') or '').endswith(('HTTP 401', 'HTTP 403')):
                    return {'status': 'error', 'reason': 'Sign in again', 'duplicate': duplicate}
                verified = not bool(quota.get('error'))
            else:
                verified = False  # Grok has no read-only credential probe.
        except (AccountError, ValueError, TypeError):
            verified = False
        return {'status': 'verified' if verified else 'checking', 'duplicate': duplicate}

    def schedule_quota(self, account, provider, now=None):
        now = time.monotonic() if now is None else now
        name = account['name']
        with self.state_lock:
            if name in self.quota_pending or now - self.quota_attempts.get(name, -60) < 30:
                return False
            self.quota_pending.add(name)
            self.quota_attempts[name] = now
        def run():
            try:
                self.fetch_quota(account, provider)
            finally:
                with self.state_lock:
                    self.quota_pending.discard(name)
        try:
            self.pool.submit(run)
        except RuntimeError:
            with self.state_lock:
                self.quota_pending.discard(name)
            return False
        return True

    def refresh_expired_quotas(self, now=None):
        now = time.time() if now is None else now
        with self.state_lock:
            accounts = list(self.accounts.values())
        for account, provider in accounts:
            # Paused accounts stay out of request rotation, but their health
            # ping must continue so quota windows and session state stay fresh.
            if account.get('api') or provider == 'tokenharbor':
                continue
            quota = account.get('quota') or {}
            deadlines = [w.get('reset_at') for w in quota.get('windows', [])]
            for group in quota.get('groups', []):
                for bucket in group.get('buckets', []):
                    try:
                        deadlines.append(datetime.fromisoformat(bucket['reset'].replace('Z', '+00:00')).timestamp())
                    except (KeyError, ValueError, TypeError, AttributeError):
                        pass
            if any(isinstance(deadline, (float, int)) and 0 < deadline <= now for deadline in deadlines):
                self.schedule_quota(account, provider)

    def fetch_quota(self, account, provider):
        try:
            quota = self.controller.quotas(account) if provider == 'gemini' else self.clients[provider].quota(account)
            with self.state_lock:
                current = self.accounts.get(account['name'])
                if current is None or current[0] is not account:
                    return
            try:
                probed = False
                if not quota.get('error') and not account.get('api'):
                    if provider == 'gemini':
                        with self.activity_lock:
                            last_used = {}
                            for event in self.activity.state.get('latest', {}).values():
                                if event.get('name') != account['name'] or event.get('probe') or event.get('failed'):
                                    continue
                                model = event.get('upstream_model') or event.get('model') or ''
                                family = 'gemini' if model.startswith('gemini-') else 'claude'
                                try:
                                    at = datetime.fromisoformat(event['at'].replace('Z', '+00:00')).timestamp()
                                    last_used[family] = max(last_used.get(family, 0), at)
                                except (KeyError, ValueError, TypeError):
                                    pass
                        probed = any(r.get('status') == 200 for r in
                                     self.controller.start_full_quota_windows(account, quota, last_used=last_used))
                    elif provider in ('claude', 'openai'):
                        probed = self.clients[provider].start_full_quota_window(account, quota) == 200
                if probed:
                    quota = self.controller.quotas(account) if provider == 'gemini' else self.clients[provider].quota(account)
            except (AccountError, OSError, ValueError):
                # A failed optional ping must not discard a valid quota response.
                pass
            with self.state_lock:
                current = self.accounts.get(account['name'])
                if current is None or current[0] is not account:
                    return
                account['quota'] = quota
                account['_omni_quota_refreshed'] = True
                self.publish(account, provider)
        except Exception as exc:
            with self.state_lock:
                current = self.accounts.get(account['name'])
                if current is None or current[0] is not account:
                    return
                account['quota'] = {**(account.get('quota') or {}), 'error': safe_detail(exc)}
                account['_omni_quota_refreshed'] = True
                self.publish(account, provider)

    def command(self, command):
        action = command['action']
        prefs = self.controller.preferences
        if action == 'preferences':
            return self.preferences()
        if action == 'snapshot':
            with self.state_lock:
                return {'preferences': self.preferences(),
                        'accounts': list(self.cached_accounts.values()) if self.initial_inventory_complete else list(self.startup_accounts),
                        'inventoryComplete': self.initial_inventory_complete}
        if action == 'account_identity':
            with self.state_lock:
                entry = self.accounts.get(command.get('id'))
                return {'email': entry[0].get('email', '')} if entry else {}
        if action == 'replace_recovered':
            raise AccountError('Recovery must verify the original workspace before replacing credentials.')
        if action == 'recovery_target':
            name = str(command.get('id') or '')
            raw = self.controller.request('/auth-files/download?name='+quote(name))
            from chatgpt_auth import gateway_credential
            credential = gateway_credential(raw)
            area = credential.get('plan_type') or ''
            if not area:
                import re
                match = re.search(r'-(free|k12|edu|plus|team|pro|business)\.json$', name, re.I)
                area = match.group(1).lower() if match else ''
            return {'accountId': credential['account_id'], 'email': credential['email'], 'area': area}
        if action == 'recovery_verify':
            name = str(command.get('id') or '')
            rows = self.clients['openai'].accounts()
            row = next((r for r in rows if r.get('name') == name), None)
            if not row:
                return {'verified': False}
            quota = self.clients['openai'].quota(row)
            return {'verified': not bool(quota.get('error')), 'error': quota.get('error', '')}
        if action == 'account_inventory':
            email = str(command.get('email') or '').strip().casefold()
            rows = self.controller.request('/auth-files').get('files', [])
            result = []
            for row in rows:
                if email and str(row.get('email') or '').casefold() != email:
                    continue
                with self.state_lock:
                    entry = self.accounts.get(row.get('name'))
                    if entry:
                        row = {**row, **entry[0]}
                status, severity, detail = account_status(row)
                name = str(row.get('name') or '')
                area = row.get('plan_type') or (row.get('quota') or {}).get('plan_type')
                if not area:
                    import re
                    match = re.search(r'-(free|k12|edu|plus|team|pro|business)\.json$', name, re.I)
                    area = match.group(1) if match else 'Unknown workspace'
                result.append({'id': name, 'email': row.get('email',''),
                               'area': area,
                               'status': status, 'severity': severity,
                               'detail': detail, 'auth_index': bool(row.get('auth_index')),
                               'models': row.get('models') or row.get('model_ids') or []})
            return result
        if action == 'archive_inventory':
            rows = self.controller.request('/auth-files').get('files', [])
            result = []
            labels = self.controller.preferences.get('labels', {})
            priorities = self.controller.preferences.get('account-priorities', {})
            for row in rows:
                provider = row.get('provider', row.get('type'))
                if provider not in ('antigravity', 'codex'):
                    continue
                name = str(row.get('name') or '')
                area = row.get('plan_type') or ''
                if not area:
                    import re
                    match = re.search(r'-(free|k12|edu|plus|team|pro|business)\.json$', name, re.I)
                    area = match.group(1) if match else ''
                result.append({'id': name, 'provider': provider, 'email': row.get('email', ''),
                               'area': area, 'label': labels.get(name, ''),
                               'priority': priorities.get(name, row.get('priority', 0) or 0),
                               'disabled': bool(row.get('disabled'))})
            return result
        if action == 'archive_export':
            path = str(command.get('path') or '')
            selected = {str(value) for value in (command.get('ids') or []) if value}
            password = command.get('password')
            if not path or not selected:
                raise AccountError('Select at least one account to export.')
            rows = self.controller.request('/auth-files').get('files', [])
            records = []
            labels = self.controller.preferences.get('labels', {})
            priorities = self.controller.preferences.get('account-priorities', {})
            for row in rows:
                name = str(row.get('name') or '')
                provider = row.get('provider', row.get('type'))
                if name not in selected or provider not in ('antigravity', 'codex'):
                    continue
                payload = self.controller.request('/auth-files/download?'+urlencode({'name': name}))
                records.append({'provider': provider, 'name': name, 'payload': payload,
                                'metadata': {'label': labels.get(name, ''),
                                             'priority': priorities.get(name, row.get('priority', 0) or 0),
                                             'disabled': bool(row.get('disabled'))}})
            if len(records) != len(selected):
                raise AccountError('One or more selected accounts are no longer available.')
            return write_archive(path, records, password, command.get('automatic_credentials'))
        if action == 'archive_import':
            data = read_archive(str(command.get('path') or ''), command.get('password'))
            existing = self.controller.request('/auth-files').get('files', [])
            existing_by_email = {}
            for row in existing:
                provider = row.get('provider', row.get('type'))
                email = str(row.get('email') or '').casefold()
                if provider in ('antigravity', 'codex') and email:
                    existing_by_email.setdefault((provider, email), row)
            imported, skipped, failed = [], [], []
            labels = self.controller.preferences.setdefault('labels', {})
            priorities = self.controller.preferences.setdefault('account-priorities', {})
            for record in data['records']:
                provider, name, payload = record['provider'], record['name'], record['payload']
                email = str(payload.get('email') or '').casefold()
                old = existing_by_email.get((provider, email))
                if old:
                    skipped.append({'email': email, 'reason': 'already-connected'})
                    continue
                try:
                    self.controller.upload_auth_file(name, json.dumps(payload, ensure_ascii=False).encode('utf-8'), archive=True)
                    meta = record.get('metadata') or {}
                    if meta.get('label'):
                        labels[name] = str(meta['label'])[:120]
                    if isinstance(meta.get('priority'), int):
                        priorities[name] = max(0, min(9, meta['priority']))
                    imported.append({'email': email, 'provider': provider, 'name': name})
                except Exception as exc:
                    failed.append({'email': email, 'reason': safe_detail(exc)})
            self.controller.save()
            if imported:
                self.pool.submit(self.refresh)
            return {'imported': imported, 'skipped': skipped, 'failed': failed,
                    'automatic_credentials': data.get('automatic_credentials', [])}
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
        elif action == 'collapse':
            provider = command['provider']
            if provider not in SERVICES + ('openai-free',):
                raise ValueError('Unknown service')
            key = {'gemini': 'google-accounts-collapsed', 'openai': 'chatgpt-collapsed', 'openai-free': 'chatgpt-free-collapsed'}.get(provider, provider+'-accounts-collapsed')
            prefs[key] = bool(command['value'])
        elif action == 'summary_collapse':
            provider = command['provider']
            if provider not in SERVICES:
                raise ValueError('Unknown service')
            prefs[('google' if provider=='gemini' else provider)+'-pool-collapsed'] = bool(command['value'])
        elif action == 'remote_server_test':
            from remote_server import test_ssh_connection
            return test_ssh_connection(command.get('config') or {})
        elif action == 'remote_server_deploy':
            from remote_server import deploy_to_server
            def on_progress(msg):
                self.emit({'event': 'remote_deploy_progress', 'message': msg})
            res = deploy_to_server(command.get('config') or {}, self.controller, progress_callback=on_progress)
            self.emit({'event': 'preferences', 'preferences': self.preferences()})
            return res
        elif action == 'remote_server_switch':
            mode = command.get('mode', 'local')
            if mode not in ('local', 'remote'):
                raise ValueError('Invalid backend mode')
            if mode == 'remote':
                from remote_server import probe_remote_gateway
                server = prefs.get('remote-server') or {}
                probe = probe_remote_gateway(server)
                if not probe.get('connected'):
                    current = prefs.get('backend-mode', 'local')
                    status = {'mode': current, 'connected': False,
                              'error': probe.get('error', 'Remote gateway is not reachable.')}
                    prefs['remote-backend-status'] = status
                    self.controller.save()
                    self.emit({'event': 'preferences', 'preferences': self.preferences()})
                    return status
                status = {'mode': 'remote', 'connected': True,
                          'gateway': probe.get('gateway'),
                          'model_count': probe.get('model_count', 0),
                          'latency_ms': probe.get('latency_ms'),
                          'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
                prefs['backend-mode'] = 'remote'
                prefs['remote-backend-status'] = status
                self.controller.save()
                self.emit({'event': 'preferences', 'preferences': self.preferences()})
                return status
            prefs['backend-mode'] = mode
            prefs['remote-backend-status'] = {
                'mode': 'local', 'connected': True,
                'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            self.controller.save()
            self.emit({'event': 'preferences', 'preferences': self.preferences()})
            return prefs['remote-backend-status']
        elif action == 'remote_server_save':
            cfg = command.get('config') or {}
            prefs['remote-server-config'] = {
                'host': str(cfg.get('host') or '').strip(),
                'port': int(cfg.get('port') or 22),
                'user': str(cfg.get('user') or 'root').strip(),
                'key_path': str(cfg.get('key_path') or '').strip(),
                'use_fido': bool(cfg.get('use_fido'))
            }
            self.controller.save()
            return {'saved': True}
        elif action == 'telegram_preferences':
            prefs['telegram-alerts-enabled'] = bool(command['enabled'])
            prefs['telegram-chat-id'] = str(command.get('chatId') or '').strip()
        elif action == 'telegram_token':
            self.telegram.save_token(command['token'])
        elif action == 'telegram_find':
            prefs['telegram-chat-id'] = self.telegram.discover_chat_id()
        elif action == 'telegram_test':
            self.telegram.send_message(prefs.get('telegram-chat-id'), 'Omni: test notification')
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
            self.controller.save()
            if provider == 'openai':
                # The remote priority write is slow network work. Publish the
                # clicked value first and reconcile the provider pool off the
                # command path so the UI responds immediately.
                self.pool.submit(self._refresh_openai_priorities)
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
            if provider not in ('gemini', 'openai', 'claude', 'grok'):
                raise AccountError('This service uses an API key, not browser sign-in.')
            result = self.controller.begin_login() if provider == 'gemini' else self.clients[provider].begin_login()
            result = result if isinstance(result, dict) else {'url': result[0], 'state': result[1]}
            self.pending_logins.add(result['state'], result['url'], provider, result.get('user_code', ''))
            return {**result, 'expires_at': self.pending_logins.get(result['state'])['expires_at']}
        elif action == 'login_browser':
            pending = self.pending_logins.get(command['state'])
            if not pending or pending.get('provider') != command['provider']:
                raise AccountError('This sign-in has expired. Start sign-in again.')
            parts = urlsplit(pending['url'])
            allowed = {'gemini': ('accounts.google.com',), 'openai': ('auth.openai.com',),
                       'claude': ('claude.ai',), 'grok': ('accounts.x.ai', 'auth.x.ai')}
            if parts.scheme != 'https' or parts.hostname not in allowed.get(command['provider'], ()):
                raise AccountError('Invalid sign-in page.')
            open_isolated(pending['url'])
            return {'opened': True}
        elif action == 'login_cancel':
            provider, state = command['provider'], command['state']
            pending = self.pending_logins.get(state)
            if not pending or pending.get('provider') != provider:
                raise AccountError('This sign-in has expired. Start sign-in again.')
            if provider == 'gemini':
                self.controller.request('/oauth-session?' + urlencode({'state': state}), 'DELETE')
            elif provider in self.clients:
                self.clients[provider].cancel_login(state)
            else:
                raise AccountError('Unknown sign-in provider.')
            self.pending_logins.remove(state)
            return {'cancelled': True}
        elif action == 'harbor_connect':
            self.harbor.connect(command['key'])
            self.pool.submit(self.refresh)
            return {'connected': True}
        elif action == 'login_pending':
            return [row for row in self.pending_logins.all()
                    if row.get('provider', 'openai') == command.get('provider', 'openai')]
        elif action == 'login_complete':
            provider, value, state = command['provider'], command['value'], command['state']
            if provider == 'openai':
                state = ChatGPTAuth.callback_state(value) or state
                if not self.pending_logins.get(state) or self.pending_logins.get(state).get('provider') != provider:
                    raise AccountError('This sign-in has expired. Start sign-in again.')
                return self.clients['openai'].complete_login(value, state)
            if provider == 'gemini':
                pending = self.pending_logins.get(state)
                if not pending or pending.get('provider') != provider:
                    raise AccountError('This sign-in has expired. Start sign-in again.')
                self.controller.google_login_state = state
                self.controller.google_login_redirect = parse_qs(urlsplit(pending['url']).query).get(
                    'redirect_uri', ['http://localhost:51121/oauth-callback'])[0]
                return self.controller.complete_google_login(value, state)
            raise AccountError('Callback sign-in is not supported by this service.')
        elif action == 'login_status':
            provider, state = command['provider'], command['state']
            pending = self.pending_logins.get(state)
            if not pending or pending.get('provider') != provider:
                completed = self.completed_logins.get(state)
                if completed and completed[0] == provider and time.monotonic() - completed[1] < 300:
                    return {'status': 'ok'}
                raise AccountError('This sign-in has expired. Start sign-in again.')
            checker = self.controller if provider == 'gemini' else self.clients.get(provider)
            if checker is None:
                raise AccountError('Unknown sign-in provider.')
            result = checker.login_status(state)
            if result.get('status') == 'ok':
                self.completed_logins[state] = (provider, time.monotonic(), pending['created_at'])
                self.pending_logins.remove(state)
                self.pool.submit(self.refresh)
            return result
        elif action == 'login_review':
            provider, state = command['provider'], command['state']
            completed = self.completed_logins.get(state)
            if not completed or completed[0] != provider or time.monotonic() - completed[1] >= 300:
                raise AccountError('This sign-in result is no longer available.')
            return self.review_login(provider, completed[2])
        elif action == 'api':
            self.api.add(API_SERVICES[command['provider']], command['key'], command.get('label', ''))
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
            self.schedule_quota(account, provider)
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
            return self.connections.maintain(
                on_progress=lambda rows: self.emit({'event': 'connections', 'connections': rows}))
        elif action == 'connect':
            return self.connections.connect(command['client'])
        elif action == 'restore_client':
            return self.connections.restore(command['client'])
        elif action == 'restart_client':
            return self.connections.restart(command['client'], command.get('confirmed', False))
        else:
            raise ValueError('Unknown action')
        self.controller.save()
        result = self.preferences()
        self.emit({'event': 'preferences', 'preferences': result})
        return result

    def poll_activity(self, now=None):
        now = time.time() if now is None else now
        with self.activity_lock:
            files = self.controller.request('/auth-files').get('files', [])
            records = self.controller.request('/usage-queue?count=200')
            aliases = self.controller.model_aliases()
            for record in records:
                record['upstream_model'] = aliases.get(record.get('model'), record.get('model'))
            self.activity.ingest(records, [a for a in files if a.get('auth_index')])
            queue_status = self.controller.quota_wait_status()
            running_jobs = [j for j in queue_status.get('jobs', []) if j.get('state') == 'running']
            running_accounts = {}
            for job in running_jobs:
                job_model = job.get('upstream_model') or aliases.get(job.get('model'), job.get('model', ''))
                auth_idx = job.get('auth_index')
                matched_name = None
                if auth_idx:
                    matched_name = next((a['name'] for a in files if a.get('auth_index') == auth_idx), None)
                if not matched_name:
                    latest_acc = next((event.get('name') for event in self.activity.state.get('latest', {}).values()
                                       if (event.get('upstream_model') == job_model or event.get('model') == job_model)), None)
                    if latest_acc and latest_acc in self.accounts and not self.accounts[latest_acc][0].get('disabled'):
                        matched_name = latest_acc
                    else:
                        family = 'gemini' if job_model.startswith('gemini-') else 'openai' if job_model.startswith('gpt-') else 'claude' if job_model.startswith('claude-') else 'grok' if job_model.startswith('grok-') else 'tokenharbor'
                        candidates = [a for a in files if not a.get('disabled') and a.get('status') == 'active' and (
                            (family == 'gemini' and a.get('provider') == 'antigravity') or
                            (family == 'openai' and a.get('provider') == 'codex') or
                            (family == 'claude' and a.get('provider') in ('claude', 'anthropic', 'antigravity')) or
                            (family == 'grok' and a.get('provider') == 'xai')
                        )]
                        if candidates:
                            candidates.sort(key=lambda a: -(a.get('priority') or 0))
                            matched_name = candidates[0]['name']
                if matched_name:
                    running_accounts[matched_name] = job_model
            latest = {}
            for event in self.activity.state.get('latest', {}).values():
                name = event.get('name')
                if name and event.get('at', '') > latest.get(name, {}).get('at', ''):
                    latest[name] = event
            changed = []
            with self.state_lock:
                for name, (account, provider) in self.accounts.items():
                    event = latest.get(name, {})
                    try:
                        age = now - datetime.fromisoformat(event['at'].replace('Z', '+00:00')).timestamp()
                    except (KeyError, ValueError, TypeError):
                        age = 9999
                    if name in running_accounts:
                        state = 'running'
                        model = running_accounts[name]
                    else:
                        model = event.get('upstream_model') or event.get('model') or ''
                        recent = 0 <= age < 60 and not event.get('failed') and not event.get('probe') and not account.get('disabled')
                        state = 'recent' if recent else 'idle'
                    stats = self.activity.state.get('stats', {}).get(name, {})
                    data = {'state': state, 'model': model if (state in ('running', 'recent')) else '',
                            'responses': stats.get('success', account.get('success', 0)),
                            'tokens': max(0, int(stats.get('tokens', 0) or 0))}
                    if self.live_activity.get(name) != data:
                        self.live_activity[name] = data
                        changed.append((account, provider))
                for account, provider in changed:
                    self.publish(account, provider)

    def start_activity(self):
        if self.activity_thread is not None:
            return
        def monitor():
            while not self.stop_event.wait(0.5):
                if not self.controller.key:
                    continue
                try:
                    self.poll_activity()
                except Exception:
                    with self.state_lock:
                        for name, (account, provider) in self.accounts.items():
                            if self.live_activity.get(name, {}).get('state') != 'idle':
                                self.live_activity[name] = {'state': 'idle', 'model': ''}
                                self.publish(account, provider)
        self.activity_thread = threading.Thread(target=monitor, name='omni-activity', daemon=True)
        self.activity_thread.start()

    def poll_pending_logins(self):
        with self.state_lock:
            sessions = list(self.pending_logins.all())
        completed = False
        for session in sessions:
            try:
                checker = self.controller if session['provider'] == 'gemini' else self.clients.get(session['provider'])
                if checker is None:
                    continue
                result = checker.login_status(session['state'])
            except (AccountError, OSError, ValueError):
                continue
            if result.get('status') in ('ok', 'error'):
                with self.state_lock:
                    self.pending_logins.remove(session['state'])
                    if result['status'] == 'ok':
                        self.completed_logins[session['state']] = (session['provider'], time.monotonic(), session['created_at'])
                completed |= result['status'] == 'ok'
                self.emit({'event': 'login', 'provider': session['provider'],
                           'state': session['state'], 'status': result['status']})
        if completed:
            self.pool.submit(self.refresh)

    def start_maintenance(self):
        if self.maintenance_thread is not None:
            return
        def monitor():
            next_refresh = 0
            while not self.stop_event.wait(5):
                if not self.controller.key:
                    continue
                try:
                    self.poll_pending_logins()
                    self.refresh_expired_quotas()
                    if time.monotonic() >= next_refresh:
                        next_refresh = time.monotonic() + 60
                        self.emit({'event': 'connections', 'connections': self.connections.maintain()})
                        self.refresh()
                except Exception as exc:
                    self.emit({'event': 'notice', 'message': safe_detail(exc)})
        self.maintenance_thread = threading.Thread(target=monitor, name='omni-maintenance', daemon=True)
        self.maintenance_thread.start()

    def handle(self, command):
        try:
            if command.get('action') in ('connections', 'connect', 'restart_client', 'login_review'):
                result = self.command(command)
            else:
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
    bridge.start_maintenance()
    bridge.start_activity()
    commands = ThreadPoolExecutor(max_workers=2, thread_name_prefix='omni-command')
    for line in sys.stdin:
        try:
            command = json.loads(line)
            commands.submit(bridge.handle, command)
        except (ValueError, TypeError):
            bridge.emit({'event': 'error', 'message': 'Invalid command'})
    bridge.stop_event.set()
    if bridge.cache_timer:
        bridge.cache_timer.cancel()
    bridge.save_account_cache()
    commands.shutdown(wait=False, cancel_futures=True)
    bridge.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    # Electron's frozen backend starts the queue as a child of the same
    # executable. Keeping this dispatch here prevents it from spawning a
    # second JSON bridge process and ensures the packaged queue code is used.
    if sys.argv[1:] == ['--internal-queue']:
        from quota_queue import main as queue_main
        queue_main()
    else:
        main()
