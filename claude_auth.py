"""Native Claude OAuth accounts, subscription usage and independent routing."""
import json
import math
import time
import urllib.parse
from datetime import datetime, timezone
from backend import AccountError, atomic_write
from chatgpt_auth import ChatGPTAuth
from quota_limits import sync_quota_limits


class ClaudeAuth(ChatGPTAuth):
    def accounts(self):
        return [item for item in self.controller.request('/auth-files').get('files', [])
                if item.get('provider', item.get('type')) in ('claude', 'anthropic')
                and not item.get('runtime_only') and item.get('source') != 'memory']

    def begin_login(self):
        result = self.controller.request('/anthropic-auth-url?is_webui=true')
        url, state = result.get('url', ''), result.get('state', '')
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname != 'claude.ai' or parts.path != '/oauth/authorize' or not state:
            raise AccountError('The gateway did not provide a safe Claude sign-in page.')
        return url, state

    @staticmethod
    def _headers(account):
        return {'Authorization': 'Bearer $TOKEN$', 'Content-Type': 'application/json',
                'anthropic-beta': 'oauth-2025-04-20', 'anthropic-version': '2023-06-01',
                'User-Agent': 'claude-cli/2.1.220 (external, cli)'}

    def api_get(self, account, endpoint):
        result = self.controller.request('/api-call', 'POST', {
            'auth_index': account['auth_index'], 'method': 'GET',
            'url': 'https://api.anthropic.com/api/oauth/' + endpoint,
            'header': self._headers(account)})
        if result.get('status_code') != 200:
            return None, 'Quota HTTP ' + str(result.get('status_code') or '?')
        body = json.loads(result.get('body') or '{}')
        if not isinstance(body, dict):
            raise ValueError('Invalid Claude quota response')
        return body, None

    @staticmethod
    def plan_name(profile):
        organization = profile.get('organization') or {}
        tier = organization.get('rate_limit_tier') or organization.get('organization_type') or profile.get('plan_type')
        if not isinstance(tier, str) or not tier.strip():
            return 'Plan unknown'
        tier = tier.lower().strip()
        if 'max' in tier:
            return 'Max 20x' if '20x' in tier else 'Max 5x' if '5x' in tier else 'Max'
        if 'pro' in tier: return 'Pro'
        if 'team' in tier: return 'Team'
        if 'enterprise' in tier: return 'Enterprise'
        if 'free' in tier: return 'Free'
        return tier.replace('_', ' ').title()[:32]

    def quota(self, account):
        body, error = self.api_get(account, 'usage')
        quota = {'windows': [], 'plan_type': account.get('plan_type'), 'error': error}
        if body is not None:
            for key, label in (('five_hour', '5h'), ('seven_day', '1w')):
                window = body.get(key)
                used = window.get('utilization') if isinstance(window, dict) else None
                if not isinstance(used, (int, float)) or isinstance(used, bool) or not math.isfinite(used):
                    continue
                try:
                    reset = datetime.fromisoformat(window['resets_at'].replace('Z', '+00:00')).timestamp()
                except (KeyError, AttributeError, ValueError, TypeError, OverflowError):
                    reset = None
                quota['windows'].append({'label': label, 'remaining': max(0, min(100, 100-used)), 'reset_at': reset})
        cache = getattr(self.controller, '_claude_plan_cache', {})
        self.controller._claude_plan_cache = cache
        previous = cache.get(account['name'])
        if previous and time.monotonic()-previous[0] < 600:
            quota['plan_type'] = previous[1]
        else:
            try:
                profile, _ = self.api_get(account, 'profile')
                if profile:
                    quota['plan_type'] = self.plan_name(profile)
                    cache[account['name']] = (time.monotonic(), quota['plan_type'])
            except (AccountError, ValueError, TypeError):
                pass
        quota['reserved'] = bool(sync_quota_limits(self.controller, account, self.quota_limit_groups(quota)))
        return quota

    @staticmethod
    def quota_limit_groups(quota):
        return [{'kind': 'claude-native', 'buckets': [
            {'window': 'weekly' if window['label']=='1w' else '5h', 'remaining': window['remaining']/100}
            for window in quota.get('windows', []) if window.get('label') in ('5h', '1w')]}]

    def start_full_quota_window(self, account, quota, now=None):
        from quota_limits import blocked_families
        if 'claude-native' in blocked_families(self.controller.preferences, account['name'], self.quota_limit_groups(quota)):
            return None
        """Start an unused full 5h window after a three-minute grace period."""
        if not account.get('auth_index') or account.get('unavailable') or account.get('cooldowns'):
            return None
        windows = {w['label']: w for w in quota.get('windows', [])}
        remaining = windows.get('5h', {}).get('remaining')
        if remaining is None:
            return None
        now = time.time() if now is None else now
        key = account['name'] + ':claude'
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
            model = select_model(models, family='claude', cheap=True)
            if not model:
                return None
            state.update(armed=False, attempt_at=now, status='pending', model=model)
            save()
        payload = {'model': model, 'max_tokens': 1, 'messages': [{'role': 'user', 'content': '.'}]}
        try:
            result = c.request('/api-call', 'POST', {'auth_index': account['auth_index'], 'method': 'POST',
                'url': 'https://api.anthropic.com/v1/messages', 'header': self._headers(account),
                'data': json.dumps(payload)})
            status = result.get('status_code', 0)
            if status == 200:
                response = json.loads(result.get('body') or '{}')
                if response.get('type') != 'message' or not response.get('content'):
                    status = 0
        except (AccountError, ValueError, TypeError):
            status = 0
        with c.quota_start_lock:
            state.update(status=status, failures=0 if status == 200 else state.get('failures', 0) + 1)
            save()
        return status

