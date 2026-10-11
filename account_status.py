"""Present provider state without treating normal quota waits as failures."""
import re
import time
from datetime import datetime
from provider_errors import unpack_error


def safe_detail(value):
    text = str(value or '')
    text = re.sub(r'(?i)bearer\s+\S+|\beyJ[\w-]+\.[\w-]+(?:\.[\w-]+)?|\b(?:sk-|thk_)[\w-]+', '[hidden]', text)
    text = re.sub(r'(?i)(["\']?(?:access_token|refresh_token|id_token|api_key|authorization)["\']?\s*[:=]\s*)["\']?[^\s,}\n]+', r'\1[hidden]', text)
    return ' '.join(text.split())[:600]


def account_status(account, now=None):
    """Return label, severity and reason. Unknown states remain visible."""
    now = time.time() if now is None else now
    raw = str(account.get('status') or '').strip()
    state = raw.lower()
    message = account.get('status_message') or ''
    error = unpack_error(message)
    code = error.get('code') or error.get('type') or error.get('status') or ''
    detail = safe_detail(error.get('message') or message)
    signals = (str(code) + ' ' + str(error.get('type') or '') + ' ' + detail + ' ' + state).lower()
    issue = account.get('access_issue')
    # Explicit credential restrictions take precedence over unrelated quota data.
    if issue == 'verification' or any(s in signals for s in ('validation_required', 'verification_required')):
        return 'Verification required', 'warning', detail
    if any(s in signals for s in ('account_deactivated', 'account_suspended', 'account_banned', 'account_blocked')) or state in ('banned', 'blocked', 'suspended', 'deactivated'):
        return 'Account blocked', 'error', detail or safe_detail(code or raw)
    if issue == 'login' or str(code) == '401' or any(s in signals for s in ('token_expired', 'invalid_token', 'invalid_grant', 'refresh_token_reused', 'authentication_error')):
        return 'Sign in again', 'error', detail
    if issue == 'denied' or str(code) == '403' or state in ('forbidden', 'denied'):
        return 'Access denied', 'error', detail
    if account.get('disabled'):
        return 'Paused', 'muted', ''
    cooldowns = []
    for entry in account.get('cooldowns') or []:
        if not isinstance(entry, dict):
            continue
        until = entry.get('retry_at')
        try:
            active = datetime.fromisoformat(until.replace('Z', '+00:00')).timestamp() > now if until else float(entry.get('remaining_seconds', 1)) > 0
        except (ValueError, TypeError, AttributeError, OverflowError):
            active = True
        if active:
            cooldowns.append(entry)
    quota = account.get('quota') or {}
    depleted = []
    for window in quota.get('windows') or []:
        try:
            if float(window['remaining']) <= 0 and float(window.get('reset_at') or 0) > now:
                depleted.append(str(window.get('label') or ''))
        except (KeyError, ValueError, TypeError):
            pass
    reasons = {str(c.get('reason') or '').lower() for c in cooldowns}
    http_codes = {str(c.get('http_status') or '') for c in cooldowns}
    if '401' in http_codes:
        return 'Sign in again', 'error', detail or 'HTTP 401'
    if '403' in http_codes:
        return 'Access denied', 'error', detail or 'HTTP 403'
    known_quota = bool(reasons & {'quota', 'credential_quota', 'quota_exhausted', 'usage_limit'}) or any(s in signals for s in ('usage_limit_reached', 'insufficient_quota', 'quota_exhausted'))
    real_error = state == 'error' and bool(detail or code) and not known_quota and str(code) != '429'
    if real_error:
        return 'Request error', 'error', detail or safe_detail(code)
    if known_quota or (depleted and not real_error):
        return 'Limit exhausted', 'warning', ''
    if str(code) == '429' or '429' in http_codes or reasons & {'rate_limit', 'rate_limit_exceeded'}:
        return 'Rate limited', 'warning', detail
    if cooldowns:
        reason = '; '.join(dict.fromkeys(safe_detail(c.get('reason') or 'unknown') for c in cooldowns))
        return 'Waiting to retry', 'warning', reason
    if state in ('error', 'failed'):
        return 'Request error', 'error', detail or 'Provider did not report the cause'
    if account.get('unavailable'):
        return 'Temporarily unavailable', 'warning', detail or safe_detail(raw)
    if state in ('active', 'ready', 'available', 'ok'):
        return 'Available', 'normal', ''
    if not state or state in ('waiting', 'pending', 'initializing'):
        return 'Waiting', 'muted', detail
    return 'Provider status: ' + safe_detail(raw), 'warning', detail


def google_account_status(account, groups):
    """Google credentials can serve independent Gemini and Claude quotas."""
    status = account_status(account)
    label, severity, detail = status
    if severity == 'error' or label in ('Paused', 'Verification required'):
        return status
    exhausted = set()
    for group in groups:
        kind = group.get('kind')
        if kind not in ('gemini', 'claude'):
            continue
        values = [b.get('remaining') for b in group.get('buckets', [])
                  if isinstance(b.get('remaining'), (int, float))]
        if values:
            if any(value <= 0 for value in values):
                exhausted.add(kind)
    if len(exhausted) == 2:
        return 'Limit exhausted', 'warning', ''
    if exhausted:
        provider = 'Gemini' if 'gemini' in exhausted else 'Claude'
        return provider + ' quota exhausted', 'warning', ''
    if label == 'Limit exhausted':
        # A model cooldown does not prove that all models or providers are depleted.
        return 'Model quota restricted', 'warning', ''
    return status
