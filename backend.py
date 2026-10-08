"""Local account control. Credentials remain with CLIProxyAPI, never in the UI."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import math
import threading
import urllib.request
import urllib.error
import urllib.parse
import sys

import bcrypt
import yaml


class AccountError(Exception):
    pass


def atomic_write(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.new')
    temp.write_bytes(data)
    if os.name != 'nt':
        temp.chmod(0o600)
    os.replace(temp, path)


def storage_root():
    if os.environ.get('GEMINI_ACCOUNTS_HOME'):
        return Path(os.environ['GEMINI_ACCOUNTS_HOME']).expanduser().resolve()
    if os.name == 'nt':
        local = Path(os.environ['LOCALAPPDATA'])
        cached = local / 'Packages' / 'OpenAI.Codex_2p2nqsd0c76g0' / 'LocalCache' / 'Local'
        return cached if (cached / 'ClaudeGemini' / 'config.yaml').exists() else local
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'GeminiAccounts'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'GeminiAccounts'


def dpapi(data, decrypt=False):
    if os.name != 'nt':
        from cryptography.fernet import Fernet, InvalidToken
        root = storage_root() / 'GeminiAccounts'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_path = root / 'storage-key'
        if not key_path.exists():
            if decrypt:
                raise AccountError('The local storage key is missing.')
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(Fernet.generate_key())
            except FileExistsError:
                pass
        try:
            cipher = Fernet(key_path.read_bytes())
            return cipher.decrypt(data) if decrypt else cipher.encrypt(data)
        except (InvalidToken, ValueError) as error:
            raise AccountError('Could not unlock protected application data.') from error
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.windll.crypt32
    if decrypt:
        ok = api.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = api.CryptProtectData(ctypes.byref(source), 'Gemini Accounts', None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise AccountError('Windows could not unlock the protected application key.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


class Controller:
    def __init__(self, proxy_dir=None, data_dir=None):
        root = storage_root()
        self.proxy_dir = Path(proxy_dir or root / 'ClaudeGemini')
        self.data_dir = Path(data_dir or root / 'GeminiAccounts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / 'preferences.json'
        try:
            self.preferences = json.loads(self.settings_path.read_text('utf-8'))
        except (OSError, ValueError):
            self.preferences = {'labels': {}, 'mode': 'pool', 'selected': None}
        self.key = None
        self.base = 'http://127.0.0.1:8317'
        self.verification_lock = threading.RLock()
        self.verification_checks = {}
        self.verification_path = self.data_dir / 'verification-state.dpapi'
        self.quota_start_lock = threading.RLock()
        self.quota_start_path = self.data_dir / 'quota-starts.json'
        try:
            self.quota_starts = json.loads(self.quota_start_path.read_text('utf-8'))
        except (OSError, ValueError):
            self.quota_starts = {}
        try:
            self.verifications = json.loads(dpapi(self.verification_path.read_bytes(), decrypt=True))
        except (OSError, ValueError, AccountError):
            self.verifications = {}

    def save(self):
        atomic_write(self.settings_path, json.dumps(self.preferences, ensure_ascii=False, indent=2).encode('utf-8'))

    def prepare(self):
        config_path = self.proxy_dir / 'config.yaml'
        if not config_path.exists():
            raise AccountError('The local Gemini connection is not installed.')
        config = yaml.safe_load(config_path.read_text('utf-8-sig'))
        from native_reasoning import remove_legacy_summary_rule
        reasoning_changed = remove_legacy_summary_rule(config)
        host = config.get('server', {}).get('host', '')
        if host not in ('127.0.0.1', 'localhost'):
            raise AccountError('The connection must be restricted to this computer.')
        self.base = 'http://127.0.0.1:' + str(config['server']['port'])
        secret_path = self.data_dir / 'management-key.dpapi'
        if secret_path.exists():
            self.key = dpapi(secret_path.read_bytes(), decrypt=True).decode('ascii')
        else:
            self.key = secrets.token_urlsafe(40)
            atomic_write(secret_path, dpapi(self.key.encode('ascii')))
        management = config.setdefault('management', {})
        current = str(management.get('secret-key', ''))
        try:
            matches = current.startswith('$2') and bcrypt.checkpw(self.key.encode(), current.encode())
        except ValueError:
            matches = False
        if not matches or management.get('allow-remote', False) or reasoning_changed:
            backup = self.data_dir / 'proxy-before-manager.yaml'
            if not backup.exists():
                atomic_write(backup, config_path.read_bytes())
            management['secret-key'] = bcrypt.hashpw(self.key.encode(), bcrypt.gensalt()).decode()
            management['allow-remote'] = False
            management['disable-control-panel'] = True
            atomic_write(config_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode())
        try:
            self.request('/auth-files')
            if config['server']['port'] == 8318:
                self.start_services()
            return
        except AccountError:
            pass
        # Reuse the user's existing service launcher; it avoids duplicate services.
        starter = self.proxy_dir / 'start-proxy.ps1'
        if os.name == 'nt' and starter.exists():
            subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(starter)],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            try:
                self.request('/auth-files')
                return
            except AccountError:
                time.sleep(.3)
        raise AccountError('The connection is not responding. Restart Gemini Accounts.')

    def start_services(self):
        starter = self.proxy_dir / 'start-proxy.ps1'
        if os.name == 'nt' and starter.exists():
            subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(starter)],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            from runtime import start_services
            start_services(self)

    def quota_wait_status(self):
        request = urllib.request.Request('http://127.0.0.1:8317/v0/management/quota-wait',
            headers={'Authorization': 'Bearer ' + (self.key or '')})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
                return json.load(response)
        except (OSError, ValueError):
            return {'jobs': []}

    def request(self, path, method='GET', payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + '/v0/management' + path, data=data, method=method,
            headers={'Authorization': 'Bearer ' + (self.key or ''), 'Content-Type': 'application/json'})
        # Local calls must not be sent through a system HTTP proxy.
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=12) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise AccountError(f'The local connection returned error {exc.code}.') from None
        except (OSError, ValueError) as exc:
            raise AccountError('Cannot reach the local Gemini connection.') from None

    def accounts(self):
        result = self.request('/auth-files')
        # Strip everything except display/routing metadata before it reaches the UI.
        allowed = ('name', 'auth_index', 'email', 'project_id', 'disabled', 'status', 'unavailable', 'cooldowns', 'success', 'failed', 'last_refresh', 'created_at', 'priority')
        accounts = []
        for item in result.get('files', []):
            if item.get('provider', item.get('type')) != 'antigravity':
                continue
            account = {k: item.get(k) for k in allowed}
            from provider_errors import failure_reason
            try:
                failure = json.loads(item.get('status_message') or '{}').get('error', {})
                account['restriction_reason'] = failure_reason(failure.get('code'), item.get('status_message'))
            except (ValueError, TypeError, AttributeError):
                account['restriction_reason'] = None
            issue = self.access_issue(item.get('status_message'))
            if issue.get('access_issue') == 'verification':
                self.remember_verification(account['name'], issue)
            with self.verification_lock:
                account.update(self.verifications.get(account['name'], issue))
            if account.get('access_issue') == 'verification' and not account.get('disabled'):
                # Google validation errors can stop credential failover. Keep the
                # login and its confirmation buttons, but quarantine it from inference.
                self._set_disabled(account, True)
                self.remember_verification(account['name'], {'auto_disabled': True})
                account['disabled'] = True
                account['auto_disabled'] = True
            accounts.append(account)
        return accounts

    @staticmethod
    def access_issue(message):
        try:
            error = json.loads(message or '{}').get('error', {})
            for detail in error.get('details', []):
                if detail.get('reason') == 'VALIDATION_REQUIRED':
                    url = detail.get('metadata', {}).get('validation_url', '')
                    parsed = urllib.parse.urlsplit(url)
                    if parsed.scheme == 'https' and parsed.hostname == 'accounts.google.com' and parsed.path.startswith('/signin/'):
                        return {'access_issue': 'verification', 'verification_url': url}
                    return {'access_issue': 'verification'}
            if error.get('code') == 401:
                return {'access_issue': 'login'}
            if error.get('code') == 403:
                return {'access_issue': 'denied'}
        except (ValueError, TypeError, AttributeError):
            pass
        return {}

    def retry_verified_account(self, account):
        # Clearing a cooldown is not proof that Google accepted verification.
        self.request('/reset-quota', 'POST', {'auth_index': account['auth_index']})
        return self.check_verified_account(account)

    def remember_verification(self, name, issue):
        with self.verification_lock:
            previous = self.verifications.get(name, {})
            saved = {**previous, **issue}
            if previous != saved:
                self.verifications[name] = saved
                atomic_write(self.verification_path, dpapi(json.dumps(self.verifications).encode()))

    def refresh_verification_url(self, account):
        result = self.check_verified_account(account, refresh_link=True)
        if result.get('verification_url'):
            return result
        if result.get('status') == 'ok':
            self.request('/reset-quota', 'POST', {'auth_index': account['auth_index']})
            return result
        raise AccountError('Google did not return a new link. The previous link has been kept.')

    def check_verified_account(self, account, refresh_link=False):
        payload = {'project': account.get('project_id') or 'aicode-consumers',
            'model': 'gemini-3.1-flash-lite',
            'request': {'contents': [{'role': 'user', 'parts': [{'text': 'Hi'}]}],
                        'generationConfig': {'maxOutputTokens': 1}}}
        response = self.request('/api-call', 'POST', {
            'auth_index': account['auth_index'], 'method': 'POST',
            'url': 'https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent',
            'header': {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json',
                       'User-Agent': 'antigravity/2.19.1 windows/amd64'},
            'data': json.dumps(payload)})
        status = response.get('status_code')
        issue = self.access_issue(response.get('body'))
        if issue.get('access_issue') == 'verification':
            self.remember_verification(account['name'], issue)
            if refresh_link:
                return issue
            raise AccountError('Google still requires verification. Open Verify Google; verification controls have been kept.')
        if status != 200:
            raise AccountError(f'Google verification returned {status}. Verification is still required.')
        with self.verification_lock:
            pending = self.verifications.get(account['name'], {})
            if (pending.get('auto_disabled') or account.get('disabled')) and (self.preferences.get('mode') != 'single' or
                                                self.preferences.get('selected') == account['name']):
                self._set_disabled(account, False)
            if self.verifications.pop(account['name'], None) is not None:
                atomic_write(self.verification_path, dpapi(json.dumps(self.verifications).encode()))
        return {'status': 'ok'}

    def activity_snapshot(self):
        accounts = self.accounts()
        for account in accounts:
            if account.get('access_issue') != 'verification':
                continue
            now = time.monotonic()
            if now - self.verification_checks.get(account['name'], -60) < 60:
                continue
            self.verification_checks[account['name']] = now
            try:
                result = self.check_verified_account(account, refresh_link=True)
                if result.get('status') == 'ok':
                    accounts = self.accounts()
            except AccountError:
                pass
        records = []
        for _ in range(5):
            batch = self.request('/usage-queue?count=200')
            records.extend(r for r in batch if isinstance(r, dict))
            if len(batch) < 200:
                break
        aliases = self.model_aliases()
        for record in records:
            model = record.get('model') or record.get('alias') or 'Unknown model'
            record['upstream_model'] = aliases.get(model, model)
        return accounts, records, self.request('/routing/strategy').get('strategy', 'unknown')

    def model_aliases(self):
        from model_names import DEFAULT_ALIASES
        try:
            config = yaml.safe_load((self.proxy_dir / 'config.yaml').read_text('utf-8-sig'))
            return {item['alias']: item['name'] for item in config.get('oauth', {}).get('model-alias', {}).get('antigravity', [])}
        except (OSError, ValueError, yaml.YAMLError):
            return dict(DEFAULT_ALIASES)

    def family_model_choices(self):
        available = set()
        for account in self.accounts():
            if not account.get('access_issue'):
                available.update(self.models(account))
        choices = {
            'gemini': sorted(m for m in available if m.startswith('gemini-') and m != 'gemini-selected' and 'image' not in m),
            'claude': sorted(m for m in available if m.startswith(('claude-sonnet-', 'claude-opus-', 'claude-haiku-')) and m != 'claude-sonnet-4-5'),
        }
        for group, model in self.selected_family_models().items():
            saved = self.preferences.get(group + '-model') or self.model_aliases().get(group + '-selected')
            if saved and model.startswith(group + '-') and model not in choices[group]:
                choices[group].append(model)
                choices[group].sort()
        return choices

    def selected_family_models(self):
        aliases = self.model_aliases()
        gemini = self.preferences.get('gemini-model') or aliases.get('claude-sonnet-4-5', '')
        claude = self.preferences.get('claude-model') or aliases.get('claude-selected', '')
        return {'gemini': gemini if gemini.startswith('gemini-') else 'gemini-3.1-pro-low',
                'claude': claude if claude.startswith('claude-') else 'claude-sonnet-4-6'}

    def set_family_models(self, gemini, claude):
        choices = self.family_model_choices()
        if gemini not in choices['gemini'] or claude not in choices['claude']:
            raise AccountError('Choose a Gemini model and a Claude model from the available account catalog.')
        payload = self.request('/oauth-model-alias').get('oauth-model-alias') or {}
        entries = [dict(item) for item in payload.get('antigravity', [])]
        activity_path = self.data_dir / 'activity.json'
        if activity_path.exists():
            from activity import Activity
            Activity(activity_path).pin_model_aliases({entry['alias']: entry['name'] for entry in entries})
        targets = {model: claude for model in choices['claude']}
        targets.update({'claude-sonnet-4-5': gemini, 'gemini-selected': gemini, 'claude-selected': claude})
        # A model must resolve directly to itself, never through a self-alias.
        entries = [entry for entry in entries if entry['alias'] not in targets]
        from model_names import model_name
        for alias, target in targets.items():
            if alias != target:
                entries.append({'alias': alias, 'name': target, 'fork': True,
                                'force-mapping': True, 'display-name': model_name(target, {})})
        self.request('/oauth-model-alias', 'PATCH', {'provider': 'antigravity', 'aliases': entries})
        self.preferences.update({'gemini-model': gemini, 'claude-model': claude, 'pro-model': gemini})
        self.save()
        return {entry['alias']: entry['name'] for entry in entries}

    def model_choices(self):
        aliases = self.model_aliases()
        available = set()
        for account in self.accounts():
            if account.get('access_issue'):
                continue
            available.update(self.models(account))
        return {
            'pro': sorted({m for m in available if m.startswith(('gemini-', 'claude-', 'gpt-')) and m not in aliases and 'image' not in m} |
                          {aliases.get('claude-sonnet-4-5', 'gemini-3.1-pro-low')}),
            'flash': sorted({m for m in available if m.startswith(('gemini-', 'claude-', 'gpt-')) and m not in aliases and 'image' not in m} |
                            {aliases.get('claude-haiku-4-5', 'gemini-3-flash')}),
        }

    def set_model_choices(self, pro, flash):
        choices = self.model_choices()
        if pro not in choices['pro'] or flash not in choices['flash']:
            raise AccountError('This model is not in the available account catalog. Reload model choices.')
        payload = self.request('/oauth-model-alias').get('oauth-model-alias') or {}
        entries = [dict(item) for item in payload.get('antigravity', [])]
        activity_path = self.data_dir / 'activity.json'
        if activity_path.exists():
            from activity import Activity
            Activity(activity_path).pin_model_aliases({entry['alias']: entry['name'] for entry in entries})
        from model_names import model_name
        for alias, target in [('claude-sonnet-4-5', pro), ('claude-haiku-4-5', flash)]:
            entry = next((item for item in entries if item['alias'] == alias), None)
            if entry is None:
                entry = {'alias': alias}
                entries.append(entry)
            entry.update(name=target, fork=True, **{'force-mapping': True, 'display-name': model_name(target)})
        # The management endpoint persists and hot-reloads only this provider.
        self.request('/oauth-model-alias', 'PATCH', {'provider': 'antigravity', 'aliases': entries})
        self.preferences.update({'pro-model': pro, 'flash-model': flash})
        self.save()
        return {entry['alias']: entry['name'] for entry in entries}

    def apply_reset_priority(self, rows):
        accounts = self.accounts()
        enabled = {a['name']: a for a in accounts if not a['disabled']}
        if self.preferences.get('mode') == 'single' or set(enabled) != {r['name'] for r in rows}:
            return False
        if self.request('/routing/strategy').get('strategy') != 'fill-first':
            self.request('/routing/strategy', 'PUT', {'value': 'fill-first'})
        changes = []
        try:
            for row in rows:
                account = enabled[row['name']]
                if (account.get('priority') or 0) != row['priority']:
                    changes.append((account, account.get('priority') or 0))
                    self.request('/auth-files/fields', 'PATCH', {'name': account['name'], 'priority': row['priority']})
        except AccountError:
            rollback_failed = False
            for account, priority in reversed(changes):
                try:
                    self.request('/auth-files/fields', 'PATCH', {'name': account['name'], 'priority': priority})
                except AccountError:
                    rollback_failed = True
            if rollback_failed:
                raise AccountError('Priority was only partially applied. Check the connection and reload quotas.') from None
            raise
        return True

    def models(self, account):
        query = urllib.parse.urlencode({'name': account['name']})
        result = self.request('/auth-files/models?' + query)
        return [m['id'] for m in result.get('models', []) if isinstance(m.get('id'), str)]

    @staticmethod
    def parse_quotas(body):
        result = {}
        for model, info in body.get('models', {}).items():
            if not isinstance(info, dict) or not isinstance(info.get('quotaInfo'), dict):
                continue
            quota = info['quotaInfo']
            fraction = quota.get('remainingFraction')
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool) or not math.isfinite(fraction) or not 0 <= fraction <= 1:
                fraction = None
            result[model] = {'remaining': fraction, 'reset': quota.get('resetTime') if isinstance(quota.get('resetTime'), str) else None}
        return result

    @staticmethod
    def parse_groups(body):
        groups = []
        for group in body.get('groups', []):
            if not isinstance(group, dict):
                continue
            title = str(group.get('displayName', ''))
            kind = 'gemini' if 'gemini' in title.lower() else 'claude' if any(s in title.lower() for s in ('claude', 'gpt')) else 'other'
            buckets = []
            for bucket in group.get('buckets', []):
                if not isinstance(bucket, dict) or bucket.get('window') not in ('weekly', '5h'):
                    continue
                value = bucket.get('remainingFraction')
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                    value = None
                buckets.append({'window': bucket['window'], 'remaining': value, 'reset': bucket.get('resetTime')})
            if buckets:
                groups.append({'name': 'Gemini' if kind == 'gemini' else 'Claude / GPT' if kind == 'claude' else title, 'kind': kind, 'buckets': buckets})
        return groups

    def quotas(self, account):
        payload = {'project': account['project_id']} if account.get('project_id') else {}
        response = self.request('/api-call', 'POST', {
            'auth_index': account['auth_index'], 'method': 'POST',
            'url': 'https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels',
            'header': {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json', 'User-Agent': 'antigravity/2.19.1 windows/amd64'},
            'data': json.dumps(payload)})
        if response.get('status_code') != 200:
            raise AccountError('Google has not returned quota data yet. Try again later.')
        try:
            body = json.loads(response.get('body', '{}'))
            if not isinstance(body.get('models'), dict):
                raise ValueError()
            result = self.parse_quotas(body)
        except (ValueError, TypeError, AttributeError):
            raise AccountError('Google returned incomplete quota data.') from None
        groups, summary_error = [], None
        try:
            summary = self.request('/api-call', 'POST', {
                'auth_index': account['auth_index'], 'method': 'POST',
                'url': 'https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary',
                'header': {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json', 'User-Agent': 'antigravity/2.19.1 windows/amd64'},
                'data': json.dumps(payload)})
            if summary.get('status_code') != 200:
                raise ValueError()
            groups = self.parse_groups(json.loads(summary.get('body', '{}')))
            if not groups:
                raise ValueError()
        except (AccountError, ValueError, TypeError, AttributeError):
            summary_error = 'Weekly quota data has not been received from Google yet.'
        # Grouped API explicitly reports exhausted 5-hour buckets as zero,
        # including cases where fetchAvailableModels omits its fraction.
        for model in result:
            kind = 'gemini' if model.startswith('gemini') else 'claude' if model.startswith(('claude', 'gpt')) else None
            for group in groups:
                if group['kind'] == kind:
                    for bucket in group['buckets']:
                        if bucket['window'] == '5h' and bucket['remaining'] is not None:
                            result[model] = {'remaining': bucket['remaining'], 'reset': bucket['reset']}
        config = yaml.safe_load((self.proxy_dir / 'config.yaml').read_text('utf-8-sig'))
        aliases = config.get('oauth', {}).get('model-alias', {}).get('antigravity', [])
        for alias in aliases:
            if alias.get('name') in result:
                result[alias['alias']] = dict(result[alias['name']])
        return {'models': result, 'groups': groups, 'summary_error': summary_error}

    def start_full_quota_windows(self, account, quotas, now=None, last_used=None):
        """Start a fresh five-hour window once per account/provider, using one output token."""
        if account.get('disabled') or account.get('access_issue'):
            return []
        now = time.time() if now is None else now
        results = []
        for group in quotas.get('groups', []):
            kind = group.get('kind')
            if kind not in ('gemini', 'claude'):
                continue
            # Never fall back to expensive Pro/Sonnet/Opus for a timer trigger.
            model = 'gemini-3-flash' if kind == 'gemini' else 'gpt-oss-120b-medium'
            if model not in quotas.get('models', {}):
                continue
            buckets = {b.get('window'): b for b in group.get('buckets', [])}
            remaining = buckets.get('5h', {}).get('remaining')
            if remaining is None:
                continue
            key = account['name'] + ':' + kind
            with self.quota_start_lock:
                state = self.quota_starts.setdefault(key, {'armed': True})
                if state.get('endpoint') != 'daily':
                    # Failed probes on the production host must not exhaust the
                    # retry budget for the working Antigravity endpoint.
                    if state.get('status') not in (None, 200):
                        state.update(armed=True, failures=0, attempt_at=0)
                    state['endpoint'] = 'daily'
                    atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
                if remaining < 1:
                    if not state.get('armed') or 'full_since' in state:
                        state.update(armed=True, failures=0)
                        state.pop('full_since', None)
                        atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
                    continue
                if remaining != 1 or buckets.get('weekly', {}).get('remaining') == 0:
                    continue
                last = state.get('attempt_at', 0)
                retry = state.get('status') != 200 and state.get('failures', 0) < 3 and now - last >= 600
                if not state.get('armed') and not retry and now - last < 5 * 3600:
                    continue
                if last and now - last < 600:
                    continue
                if 'full_since' not in state or (last and now - last >= 5 * 3600 and state['full_since'] <= last):
                    state['full_since'] = now
                    atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
                used = (last_used or {}).get(kind, 0)
                if used >= state['full_since']:
                    state.update(armed=False, attempt_at=used, status=200, failures=0)
                    state.pop('full_since', None)
                    atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
                    continue
                if now - state['full_since'] < 180:
                    continue
                # Persist the claim before sending, including across app restarts.
                state.update(armed=False, attempt_at=now, status='pending', model=model)
                atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
            payload = {'project': account.get('project_id') or 'aicode-consumers', 'model': model,
                'request': {'contents': [{'role': 'user', 'parts': [{'text': 'Hi'}]}],
                            'generationConfig': {'maxOutputTokens': 1}}}
            try:
                response = self.request('/api-call', 'POST', {'auth_index': account['auth_index'], 'method': 'POST',
                    'url': 'https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent',
                    'header': {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json',
                               'User-Agent': 'antigravity/2.19.1 windows/amd64'}, 'data': json.dumps(payload)})
                status = response.get('status_code', 0)
                issue = self.access_issue(response.get('body'))
                if issue.get('access_issue') == 'verification':
                    self.remember_verification(account['name'], issue)
            except AccountError:
                status = 0
            with self.quota_start_lock:
                state.update(status=status, failures=0 if status == 200 else state.get('failures', 0) + 1)
                atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())
            results.append({'kind': kind, 'status': status})
        return results

    def _set_disabled(self, account, disabled):
        return self.request('/auth-files/status', 'PATCH', {'name': account['name'], 'auth_index': account.get('auth_index'), 'disabled': disabled})

    def route(self, selected=None):
        accounts = self.accounts()
        if not accounts:
            raise AccountError('Add a Google account first.')
        if selected and selected not in {a['name'] for a in accounts}:
            raise AccountError('This account is no longer available. Reload the list.')
        if selected and any(a['name'] == selected and a.get('access_issue') == 'verification' for a in accounts):
            raise AccountError('Verify this Google account first, then click I verified.')
        # Enable the destination first. Restore original states if any update fails.
        changes = sorted([(a, bool(a.get('access_issue') == 'verification' or (selected and a['name'] != selected)))
                          for a in accounts], key=lambda pair: pair[1])
        changed = []
        try:
            for account, disabled in changes:
                if bool(account['disabled']) != disabled:
                    changed.append(account)
                    self._set_disabled(account, disabled)
        except AccountError:
            failed_rollback = False
            for account in reversed(changed):
                try:
                    self._set_disabled(account, bool(account['disabled']))
                except AccountError:
                    failed_rollback = True
            if failed_rollback:
                raise AccountError('Switching was only partially completed. Reload and select the account again.') from None
            raise
        self.preferences['mode'] = 'single' if selected else 'pool'
        self.preferences['selected'] = selected
        self.save()

    def pause(self, account):
        if account.get('access_issue') == 'verification':
            raise AccountError('Verify the Google account first, then click I verified.')
        self._set_disabled(account, not bool(account['disabled']))
        self.preferences['mode'] = 'custom'
        self.preferences['selected'] = None
        self.save()

    def remove_account(self, name):
        if not isinstance(name, str) or not name or not any(a['name'] == name for a in self.accounts()):
            raise AccountError('Account no longer exists. Refresh the account list.')
        # Delete the exact credential through the provider API, never a filesystem glob.
        self.request('/auth-files?' + urllib.parse.urlencode({'name': name}), 'DELETE')
        self.preferences.get('labels', {}).pop(name, None)
        if self.preferences.get('selected') == name:
            self.preferences['selected'] = None
            self.preferences['mode'] = 'custom'
        self.save()
        with self.verification_lock:
            self.verification_checks.pop(name, None)
            if self.verifications.pop(name, None) is not None:
                atomic_write(self.verification_path, dpapi(json.dumps(self.verifications).encode()))
        with self.quota_start_lock:
            for kind in ('gemini', 'claude'):
                self.quota_starts.pop(name + ':' + kind, None)
            atomic_write(self.quota_start_path, json.dumps(self.quota_starts).encode())

    def rename(self, name, label):
        self.preferences.setdefault('labels', {})[name] = label.strip()[:60]
        self.save()

    def begin_login(self):
        self.login_accounts_before = {a['name'] for a in self.accounts()}
        result = self.request('/antigravity-auth-url?is_webui=true')
        url = result.get('url', '')
        state = result.get('state', '')
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'accounts.google.com' or not state:
            raise AccountError('Could not obtain a safe Google sign-in URL.')
        query = dict(urllib.parse.parse_qsl(parts.query))
        query['prompt'] = 'select_account consent'
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))), state

    def login_status(self, state):
        return self.request('/get-auth-status?' + urllib.parse.urlencode({'state': state}))

    def reconcile_new_login(self):
        results = []
        before = getattr(self, 'login_accounts_before', set())
        for account in self.accounts():
            if account['name'] in before:
                continue
            try:
                result = self.check_verified_account(account, refresh_link=True)
            except AccountError as error:
                result = {'status': 'error', 'message': str(error)}
            results.append({'name': account['name'], **result})
        # Apply quarantine before a new identity can be picked for inference.
        self.accounts()
        if self.preferences.get('mode') == 'single' and self.preferences.get('selected'):
            self.route(self.preferences['selected'])
        return results
