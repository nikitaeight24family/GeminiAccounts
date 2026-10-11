"""Import a user-selected Codex auth.json into the local ChatGPT OAuth gateway."""
import base64
import hashlib
import json
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from backend import AccountError


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
              'plan_type': identity.get('chatgpt_plan_type') or raw.get('plan_type') or 'free',
              'last_refresh': raw.get('last_refresh') or datetime.now(timezone.utc).isoformat(),
              'expired': expire}
    return result


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

    def cancel_login(self, state):
        return self.controller.request('/oauth-session?' + urllib.parse.urlencode({'state': state}), 'DELETE')

    def accounts_with_quotas(self):
        accounts = self.accounts()
        eligible = [account for account in accounts if not account.get('disabled') and account.get('auth_index')]
        def load(account):
            try:
                return self.quota(account)
            except (AccountError, ValueError, TypeError):
                return {'windows': [], 'error': 'Quota unavailable'}
        if eligible:
            with ThreadPoolExecutor(max_workers=min(4, len(eligible))) as pool:
                for account, quota in zip(eligible, pool.map(load, eligible)):
                    account['quota'] = quota
        return accounts

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
            label = '5h' if seconds == 18000 else '1w' if seconds == 604800 else (
                f'{seconds // 3600}h' if isinstance(seconds, int) and seconds >= 3600 else name)
            windows.append({'label': label, 'remaining': max(0, min(100, 100 - used)),
                            'reset_at': window.get('reset_at')})
        credits = body.get('rate_limit_reset_credits') or {}
        quota = {'windows': windows, 'reset_credits': credits.get('available_count'),
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
        return quota

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
            cleared = self.controller.request('/routing/cooldown/reset', 'POST', {'auth_index': account['auth_index']})
            if cleared.get('status') != 'ok' or cleared.get('auth_index') != account['auth_index']:
                raise AccountError('Cooldown reset not confirmed.')
        except AccountError:
            raise AccountError('ChatGPT applied the reset, but the gateway cooldown could not be cleared. Refresh the account; do not spend another reset.') from None
        return body.get('windows_reset', 0)

    def import_file(self, source):
        path = Path(source)
        try:
            if path.suffix.lower() != '.json' or path.stat().st_size > 2_000_000:
                raise AccountError('Choose a Codex auth.json file smaller than 2 MB.')
            credential = gateway_credential(json.loads(path.read_text('utf-8-sig')))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AccountError('Cannot read this auth.json file.') from error
        suffix = hashlib.sha256(credential['account_id'].encode('utf-8')).hexdigest()[:16]
        name = 'codex-import-' + suffix + '.json'
        payload = json.dumps(credential, ensure_ascii=False).encode('utf-8')
        self.controller.upload_auth_file(name, payload)
        accounts = self.accounts()
        if not any(item.get('name') == name and not item.get('disabled') for item in accounts):
            raise AccountError('The gateway did not activate this ChatGPT account.')
        return credential['email'], accounts
