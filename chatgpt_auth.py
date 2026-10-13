"""Import a user-selected Codex auth.json into the local ChatGPT OAuth gateway."""
import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request
import urllib.error
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from backend import AccountError, atomic_write
from routing import rank_accounts
from chatgpt_routing import is_free_account


def jwt_claims(token):
    try:
        payload = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError):
        raise AccountError('The ChatGPT identity token in auth.json is invalid.') from None


def gateway_credential(raw):
    """Accept Codex's nested auth.json or an existing flat Codex OAuth record."""
    if not isinstance(raw, dict):
        raise AccountError('Choose a Codex ChatGPT auth.json file.')
    if raw.get('type') == 'codex':
        tokens = raw
    elif raw.get('auth_mode') == 'chatgpt':
        tokens = raw.get('tokens') or {}
    else:
        raise AccountError('This auth.json is not a ChatGPT account sign-in.')
    if not isinstance(tokens, dict) or any(not isinstance(tokens.get(field), str) or not tokens[field]
                                           for field in ('id_token', 'access_token', 'refresh_token')):
        raise AccountError('The auth.json file has no complete ChatGPT sign-in tokens.')
    claims = jwt_claims(tokens['id_token'])
    identity = claims.get('https://api.openai.com/auth') or {}
    account_id = tokens.get('account_id') or identity.get('chatgpt_account_id')
    if (tokens.get('account_id') and identity.get('chatgpt_account_id') and
            tokens['account_id'] != identity['chatgpt_account_id']):
        raise AccountError('The account ID does not match the ChatGPT identity token.')
    email = raw.get('email') or claims.get('email')
    if not isinstance(account_id, str) or not account_id:
        raise AccountError('The auth.json file has no ChatGPT account ID.')
    if not isinstance(email, str) or not email:
        raise AccountError('The auth.json file has no account email.')
    expire = tokens.get('expires_at') or claims.get('exp')
    if isinstance(expire, (int, float)):
        try:
            expire = datetime.fromtimestamp(expire, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            expire = ''
    elif not isinstance(expire, str):
        expire = ''
    result = {'type': 'codex', 'id_token': tokens['id_token'],
              'access_token': tokens['access_token'], 'refresh_token': tokens['refresh_token'],
              'account_id': account_id, 'email': email,
              'plan_type': identity.get('chatgpt_plan_type') or raw.get('plan_type') or '',
              'last_refresh': raw.get('last_refresh') or datetime.now(timezone.utc).isoformat(),
              'expired': expire}
    return result


def same_oauth_session(left, right):
    """Compare local credentials without exposing token material."""
    left = left.get('tokens', left) if isinstance(left, dict) else {}
    right = right.get('tokens', right) if isinstance(right, dict) else {}
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if left.get('refresh_token') and left['refresh_token'] == right.get('refresh_token'):
        return True
    try:
        first = jwt_claims(left.get('access_token', '')).get('session_id')
        second = jwt_claims(right.get('access_token', '')).get('session_id')
    except (AccountError, AttributeError):
        return False
    return bool(first and second and first == second)


class ChatGPTAuth:
    def __init__(self, controller):
        self.controller = controller

    def accounts(self):
        return [item for item in self.controller.request('/auth-files').get('files', [])
                if item.get('provider', item.get('type')) == 'codex']

    def begin_login(self):
        result = self.controller.request('/codex-auth-url?is_webui=true')
        url, state = result.get('url', ''), result.get('state', '')
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'auth.openai.com' or not state:
            raise AccountError('The gateway did not provide a safe ChatGPT sign-in page.')
        return url, state

    def login_status(self, state):
        return self.controller.request('/get-auth-status?' + urllib.parse.urlencode({'state': state}))

    def complete_login(self, value, state):
        """Forward a browser callback (or pasted code) to the local OAuth listener."""
        value = str(value or '').strip()
        # MoreLogin/Codex and browser policy pages commonly wrap the callback
        # in a label, a leading slash, or escaped ampersands when copied.
        value = value.removeprefix('Blocked URL:').strip()
        value = value.lstrip('\\').replace('\\&', '&')
        if not value:
            raise AccountError('Paste the callback address or authorization code.')
        if '://' in value:
            parts = urllib.parse.urlsplit(value)
            if (parts.scheme != 'http' or parts.hostname not in ('localhost', '127.0.0.1')
                    or parts.port != 1455 or parts.path != '/auth/callback'):
                raise AccountError('Paste the localhost:1455 ChatGPT callback from the browser.')
            query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            if query.get('state', [None]) != [state]:
                raise AccountError('This callback belongs to another ChatGPT sign-in.')
            code = query.get('code', [None])
            if len(code) != 1 or not code[0]:
                raise AccountError('The callback does not contain an authorization code.')
            target = value
        else:
            if any(char.isspace() for char in value) or len(value) < 8:
                raise AccountError('Enter the authorization code shown by ChatGPT.')
            target = 'http://127.0.0.1:1455/auth/callback?' + urllib.parse.urlencode({'code': value, 'state': state})
        request = urllib.request.Request(target, method='GET')
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=12) as response:
                response.read(4096)
        except urllib.error.HTTPError as error:
            raise AccountError('The local ChatGPT sign-in listener rejected the code (HTTP %s).' % error.code) from None
        except OSError:
            raise AccountError('The local ChatGPT sign-in listener is not responding. Start a new sign-in.') from None
        return {'accepted': True}

    @staticmethod
    def callback_state(value):
        """Return the OAuth state embedded in a pasted callback URL, if present."""
        value = str(value or '').strip().removeprefix('Blocked URL:').strip()
        value = value.lstrip('\\').replace('\\&', '&')
        if '://' not in value:
            return None
        try:
            parts = urllib.parse.urlsplit(value)
            query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            states = query.get('state', [])
            return states[0] if len(states) == 1 and states[0] else None
        except (TypeError, ValueError):
            return None

    def cancel_login(self, state):
        return self.controller.request('/oauth-session?' + urllib.parse.urlencode({'state': state}), 'DELETE')

    def accounts_with_quotas(self, maintain_pool=False, on_quota=None):
        accounts = self.accounts()
        eligible = [account for account in accounts if not account.get('disabled') and account.get('auth_index')]
        def load(account):
            try:
                quota = self.quota(account)
                # Keep routing data alongside the quota.  The catalog is
                # provider-reported, so new models are picked up automatically.
                try:
                    account['supported_models'] = self.controller.models(account)
                except (AccountError, ValueError, TypeError):
                    account['supported_models'] = []
                if on_quota:
                    on_quota({**account, 'quota': quota})
                if maintain_pool and self.start_full_quota_window(account, quota) == 200:
                    quota = self.quota(account)
                return quota
            except (AccountError, ValueError, TypeError):
                quota = {'windows': [], 'error': 'Quota unavailable'}
                if on_quota:
                    on_quota({**account, 'quota': quota})
                return quota
        if eligible:
            with ThreadPoolExecutor(max_workers=min(4, len(eligible))) as pool:
                for account, quota in zip(eligible, pool.map(load, eligible)):
                    account['quota'] = quota
        if maintain_pool and eligible:
            self.apply_reset_priority(accounts)
        return accounts

    def apply_reset_priority(self, accounts):
        """Rank the ChatGPT pool independently of Google's manual account mode."""
        now = datetime.now(timezone.utc)
        caches = {}
        for account in accounts:
            quota = account.get('quota') or {}
            buckets = []
            for window in quota.get('windows', []):
                if window.get('label') not in ('5h', '1w'):
                    continue
                try:
                    reset = datetime.fromtimestamp(window['reset_at'], timezone.utc).isoformat()
                except (KeyError, ValueError, TypeError, OverflowError, OSError):
                    reset = None
                buckets.append({'window': 'weekly' if window['label'] == '1w' else '5h',
                                'remaining': window['remaining'] / 100, 'reset': reset})
            caches[account['name']] = {'at': now, 'error': quota.get('error'),
                'data': {'groups': [{'kind': 'claude', 'buckets': buckets}]}}
        rows = rank_accounts(accounts, caches, 'claude', now,
                             priorities=self.controller.preferences.get('account-priorities', {}))
        # A provider-confirmed available account without a 5h window is used
        # before timed pools, until the provider actually refuses requests.
        from quota_limits import blocked_families
        unmetered = set()
        for account in accounts:
            quota = account.get('quota') or {}
            windows = quota.get('windows') or []
            if (quota.get('allowed') is True and not quota.get('limit_reached') and
                    not quota.get('error') and not account.get('disabled') and
                    not account.get('unavailable') and account.get('status') != 'error' and
                    not account.get('cooldowns') and
                    not any(w.get('label') == '5h' for w in windows) and
                    'openai' not in blocked_families(self.controller.preferences, account['name'],
                                                   self.quota_limit_groups(quota))):
                unmetered.add(account['name'])
        rows.sort(key=lambda row: 0 if row['name'] in unmetered else 1)
        # Free subscriptions are the first pool for GPT models they advertise.
        # The gateway's per-account model catalog prevents this ordering from
        # sending an unsupported model to a free credential.
        free_names = {account['name'] for account in accounts if is_free_account(account)}
        rows.sort(key=lambda row: 0 if row['name'] in free_names else 1)
        for index, row in enumerate(rows):
            row['priority'] = len(rows) - index
        fresh = {a['name']: a for a in self.accounts() if not a.get('disabled')}
        if set(fresh) != {row['name'] for row in rows}:
            return False
        if self.controller.request('/routing/strategy').get('strategy') != 'fill-first':
            self.controller.request('/routing/strategy', 'PUT', {'value': 'fill-first'})
        changes = []
        try:
            for row in rows:
                account = fresh[row['name']]
                if (account.get('priority') or 0) != row['priority']:
                    changes.append((account, account.get('priority') or 0))
                    self.controller.request('/auth-files/fields', 'PATCH', {'name': row['name'], 'priority': row['priority']})
                    next(a for a in accounts if a['name'] == row['name'])['priority'] = row['priority']
        except AccountError:
            for account, priority in reversed(changes):
                self.controller.request('/auth-files/fields', 'PATCH', {'name': account['name'], 'priority': priority})
            raise
        return True

    def start_full_quota_window(self, account, quota, now=None):
        # Free OAuth credentials must never receive synthetic generation
        # requests.  They are monitored through the read-only usage endpoint;
        # probing them with "Hi" can look like automated abuse and may cause
        # the provider to revoke otherwise valid sessions.
        if is_free_account(account):
            return None
        from quota_limits import blocked_families
        if 'openai' in blocked_families(self.controller.preferences, account['name'], self.quota_limit_groups(quota)):
            return None
        """Start an unused full 5h window after a three-minute grace period."""
        if account.get('disabled') or not account.get('auth_index') or account.get('unavailable') or account.get('cooldowns'):
            return None
        windows = {w['label']: w for w in quota.get('windows', [])}
        remaining = windows.get('5h', {}).get('remaining')
        if remaining is None:
            return None
        now = time.time() if now is None else now
        key = account['name'] + ':codex'
        c = self.controller
        with c.quota_start_lock:
            state = c.quota_starts.setdefault(key, {'armed': True})
            def save():
                atomic_write(c.quota_start_path, json.dumps(c.quota_starts).encode())
            successes = account.get('success') or 0
            if remaining < 100:
                state.update(armed=True, failures=0, successes=successes)
                state.pop('full_since', None)
                save()
                return None
            if remaining != 100 or windows.get('1w', {}).get('remaining', 0) <= 0:
                return None
            last = state.get('attempt_at', 0)
            if state.get('failures', 0) >= 3 and now - last < 18000:
                return None
            if last and now - last < 600:
                return None
            if not state.get('armed') and state.get('status') == 200 and now - last < 18000:
                return None
            if 'full_since' not in state or (last and now - last >= 18000 and state['full_since'] <= last):
                state.update(full_since=now, successes=successes)
                save()
            if successes > state.get('successes', 0):
                state.update(armed=False, attempt_at=now, status=200, failures=0, successes=successes)
                state.pop('full_since', None)
                save()
                return None
            if now - state['full_since'] < 180:
                return None
            models = c.models(account)
            from model_policy import select_model
            model = select_model(models, family='gpt', cheap=True)
            if not model:
                return None
            state.update(armed=False, attempt_at=now, probe_sent_at=now, status='pending', model=model)
            save()
        payload = {'model': model, 'instructions': 'Reply with a single dot.',
                   'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Hi'}]}],
                   'max_output_tokens': 16, 'reasoning': {'effort': 'none'}, 'stream': True, 'store': False}
        try:
            result = c.request('/api-call', 'POST', {'auth_index': account['auth_index'], 'method': 'POST',
                'url': 'https://chatgpt.com/backend-api/codex/responses',
                'header': {**self._headers(account), 'Accept': 'text/event-stream', 'Originator': 'codex_cli_rs'},
                'data': json.dumps(payload)})
            status = result.get('status_code', 0)
            if status == 200 and 'response.completed' not in (result.get('body') or ''):
                status = 0
        except AccountError:
            status = 0
        with c.quota_start_lock:
            state.update(status=status, failures=0 if status == 200 else state.get('failures', 0) + 1)
            save()
        return status

    def quota(self, account):
        headers = self._headers(account)
        result = self.controller.request('/api-call', 'POST', {
            'auth_index': account['auth_index'], 'method': 'GET',
            'url': 'https://chatgpt.com/backend-api/wham/usage', 'header': headers})
        if result.get('status_code') != 200:
            return {'windows': [], 'error': 'Quota HTTP ' + str(result.get('status_code') or '?')}
        body = json.loads(result.get('body') or '{}')
        rate = body.get('rate_limit') or {}
        windows = []
        for name in ('primary_window', 'secondary_window'):
            window = rate.get(name)
            if not isinstance(window, dict):
                continue
            seconds = window.get('limit_window_seconds')
            used = window.get('used_percent')
            if not isinstance(used, (int, float)) or isinstance(used, bool):
                continue
            label = '5h' if seconds == 18000 else '1w' if seconds == 604800 else '1mo' if isinstance(seconds, int) and 28 * 86400 <= seconds <= 31 * 86400 else (
                f'{seconds // 3600}h' if isinstance(seconds, int) and seconds >= 3600 else name)
            windows.append({'label': label, 'remaining': max(0, min(100, 100 - used)),
                            'reset_at': window.get('reset_at')})
        credits = body.get('rate_limit_reset_credits') or {}
        quota = {'windows': windows, 'allowed': rate.get('allowed'), 'limit_reached': rate.get('limit_reached'),
                 'plan_type': body.get('plan_type'), 'reset_credits': credits.get('available_count'),
                 'reset_applicable': credits.get('applicable_available_count')}
        if isinstance(quota['reset_credits'], int) and quota['reset_credits'] > 0:
            try:
                quota['reset_options'] = self.list_reset_credits(account)
                if quota['reset_applicable'] == 0:
                    quota['reset_options'] = []
                    quota['reset_error'] = 'No usage reset applies right now'
            except (AccountError, ValueError, TypeError):
                quota['reset_options'] = []
                quota['reset_error'] = 'Reset details unavailable'
        from quota_limits import sync_quota_limits
        quota['reserved'] = bool(sync_quota_limits(self.controller, account, self.quota_limit_groups(quota)))
        self.recover_reset_quota(account, quota)
        return quota

    def recover_reset_quota(self, account, quota):
        """Reconcile a full provider reset with stale local quota cooldowns."""
        blocks = account.get('cooldowns') or []
        windows = {w['label']: w['remaining'] for w in quota.get('windows', [])}
        if (account.get('disabled') or not account.get('auth_index') or not blocks or
                account.get('access_issue') in ('login', 'denied', 'verification') or
                quota.get('allowed') is not True or quota.get('limit_reached') is not False or
                windows.get('5h') != 100 or windows.get('1w') != 100 or
                any(b.get('reason') not in ('quota', 'credential_quota', 'quota_exhausted', 'usage_limit')
                    or b.get('http_status') not in (None, 429) for b in blocks)):
            return False
        self.clear_quota_cooldown(account)
        fresh = next((a for a in self.accounts() if a.get('auth_index') == account['auth_index']), None)
        if fresh is not None:
            account.update(fresh)
        return True

    def clear_quota_cooldown(self, account):
        # Controller uses /v0/management. The v8 /routing/cooldown/reset alias
        # is not registered there in the pinned gateway version.
        cleared = self.controller.request('/reset-quota', 'POST', {'auth_index': account['auth_index']})
        if cleared.get('status') != 'ok' or cleared.get('auth_index') != account['auth_index']:
            raise AccountError('Cooldown reset not confirmed.')

    @staticmethod
    def quota_limit_groups(quota):
        return [{'kind': 'openai', 'buckets': [
            {'window': 'weekly' if window['label'] == '1w' else '5h', 'remaining': window['remaining'] / 100}
            for window in quota.get('windows', []) if window.get('label') in ('5h', '1w')]}]

    @staticmethod
    def _headers(account):
        headers = {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json',
                   'User-Agent': 'codex_cli_rs/0.76.0 (Windows; x86_64) WindowsTerminal'}
        if account.get('account'):
            headers['ChatGPT-Account-Id'] = account['account']
        return headers

    def list_reset_credits(self, account):
        result = self.controller.request('/api-call', 'POST', {
            'auth_index': account['auth_index'], 'method': 'GET',
            'url': 'https://chatgpt.com/backend-api/wham/rate-limit-reset-credits',
            'header': self._headers(account)})
        if result.get('status_code') != 200:
            raise AccountError('ChatGPT reset details are unavailable right now.')
        body = json.loads(result.get('body') or '{}')
        if not isinstance(body, dict) or not isinstance(body.get('credits'), list):
            raise AccountError('ChatGPT did not return a reset list.')
        if body.get('applicable_available_count') == 0:
            return []
        now = datetime.now(timezone.utc)
        available = []
        for credit in body['credits']:
            if (not isinstance(credit, dict) or credit.get('reset_type') != 'codex_rate_limits' or
                    credit.get('status') != 'available' or not isinstance(credit.get('id'), str) or not credit['id']):
                continue
            expires = credit.get('expires_at')
            if expires:
                try:
                    if datetime.fromisoformat(expires.replace('Z', '+00:00')) <= now:
                        continue
                except (AttributeError, TypeError, ValueError):
                    continue
            available.append({'id': credit['id'], 'title': credit.get('title') or 'Full usage reset',
                              'expires_at': expires})
        return available

    def use_reset_credit(self, account):
        """Redeem one confirmed credit for one account; never retry a POST automatically."""
        if account.get('disabled') or not account.get('auth_index'):
            raise AccountError('Enable this ChatGPT account before using a reset.')
        if not self.quota(account).get('reset_options'):
            raise AccountError('This reset is no longer available. Refresh the account.')
        # The provider chooses the credit; its consume endpoint accepts a redeem ID.
        payload = json.dumps({'redeem_request_id': str(uuid.uuid4())})
        try:
            result = self.controller.request('/api-call', 'POST', {
                'auth_index': account['auth_index'], 'method': 'POST',
                'url': 'https://chatgpt.com/backend-api/wham/rate-limit-reset-credits/consume',
                'header': {**self._headers(account), 'Content-Type': 'application/json'},
                'data': payload})
        except AccountError:
            raise AccountError('Reset status is unknown. Refresh this account before trying again.') from None
        if result.get('status_code') != 200:
            raise AccountError('ChatGPT did not apply the reset (HTTP ' + str(result.get('status_code') or '?') + ').')
        try:
            body = json.loads(result.get('body') or '{}')
        except (ValueError, TypeError):
            raise AccountError('Reset status is unknown. Refresh this account before trying again.') from None
        if not isinstance(body, dict) or body.get('code') not in ('reset', 'already_redeemed'):
            raise AccountError('ChatGPT did not confirm the reset. Refresh this account.')
        try:
            self.clear_quota_cooldown(account)
        except AccountError:
            raise AccountError('ChatGPT applied the reset, but the gateway cooldown could not be cleared. Refresh the account; do not spend another reset.') from None
        return body.get('windows_reset', 0)

    def import_file(self, source, codex_auth_path=None):
        path = Path(source)
        try:
            if path.suffix.lower() != '.json' or path.stat().st_size > 2_000_000:
                raise AccountError('Choose a Codex auth.json file smaller than 2 MB.')
            credential = gateway_credential(json.loads(path.read_text('utf-8-sig')))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AccountError('Cannot read this auth.json file.') from error
        suffix = hashlib.sha256(credential['account_id'].encode('utf-8')).hexdigest()[:16]
        name = 'codex-import-' + suffix + '.json'
        local_auth = Path(codex_auth_path) if codex_auth_path is not None else (
            Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'auth.json')
        try:
            shared = same_oauth_session(credential, json.loads(local_auth.read_text('utf-8-sig')))
        except (OSError, UnicodeError, json.JSONDecodeError):
            shared = False
        if shared:
            raise AccountError('This session is also stored in Codex. Sign in through Omni to create a separate session instead of importing this auth.json.')
        for account in self.accounts():
            if account.get('name') != name and account.get('email') and account['email'] != credential['email']:
                continue
            existing = self.controller.request('/auth-files/download?' + urllib.parse.urlencode({'name': account['name']}))
            if same_oauth_session(credential, existing):
                raise AccountError('This session is already connected. Use the existing entry or sign in through Omni to create a separate session; reimporting can replace renewed tokens with an old copy.')
        payload = json.dumps(credential, ensure_ascii=False).encode('utf-8')
        self.controller.upload_auth_file(name, payload)
        accounts = self.accounts()
        if not any(item.get('name') == name and not item.get('disabled') for item in accounts):
            raise AccountError('The gateway did not activate this ChatGPT account.')
        return credential['email'], accounts
