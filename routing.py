"""Rank available credentials by quota restoration time."""
import math
from datetime import datetime, timezone


def reset_date(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, AttributeError):
        return None


def quota_projection(entries, now=None, exhausted_only=True):
    """Potential pooled quota after known resets; usage can change this estimate."""
    now = now or datetime.now(timezone.utc)
    if not entries:
        return []
    total = sum(entry['remaining'] for entry in entries)
    increases = {}
    for entry in entries:
        if entry['remaining'] >= 1 or (exhausted_only and entry['remaining'] != 0):
            continue
        moment = reset_date(entry.get('reset'))
        if not moment or moment <= now:
            continue
        weekly = entry.get('weekly_remaining')
        if weekly is None:
            continue
        if weekly == 0:
            weekly_reset = reset_date(entry.get('weekly_reset'))
            if not weekly_reset or weekly_reset <= now:
                continue
            moment = max(moment, weekly_reset)
        increases[moment] = increases.get(moment, 0) + 1 - entry['remaining']
    result = []
    for moment, increase in sorted(increases.items()):
        total += increase
        result.append({'reset': moment.isoformat(), 'remaining': min(1, total / len(entries))})
    return result


def rank_accounts(accounts, caches, group, now=None):
    now = now or datetime.now(timezone.utc)
    rows = []
    for account in accounts:
        if account.get('disabled'):
            continue
        cached = caches.get(account['name'], {})
        at = cached.get('at')
        fresh = at and 0 <= (now - at).total_seconds() <= 180 and not cached.get('error') and not cached.get('data', {}).get('summary_error')
        groups = cached.get('data', {}).get('groups', []) if fresh else []
        buckets = next((g['buckets'] for g in groups if g.get('kind') == group), [])
        buckets = [b for b in buckets if b.get('window') in ('5h', 'weekly')]
        def valid(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1
        known = [b for b in buckets if valid(b.get('remaining'))]
        zero = [b for b in known if b['remaining'] == 0]
        resets = [reset_date(b.get('reset')) for b in known]
        upcoming = [date for date in resets if date and date > now]
        expired = any(date and date <= now for date in resets)
        if zero:
            blocked_dates = [reset_date(b.get('reset')) for b in zero]
            if all(date and date > now for date in blocked_dates):
                reset = max(blocked_dates)
                tier, reason = 3, 'Quota exhausted; waiting for all blocking windows to reset'
            else:
                reset = None
                tier, reason = 2, 'Reset reached or unknown; fresh quota data required'
        elif len({b['window'] for b in known}) != 2 or expired:
            reset = None
            tier, reason = 2, 'No fresh complete quota data'
        else:
            reset = min(upcoming) if upcoming else None
            tier = 0 if reset else 1
            reason = 'Quota available; earliest reset' if reset else 'Quota available; reset time unknown'
        cooldowns = []
        for cooldown in account.get('cooldowns') or []:
            model = cooldown.get('model_key', '')
            matches = cooldown.get('scope') == 'credential' or model.startswith('gemini') if group == 'gemini' else cooldown.get('scope') == 'credential' or model.startswith(('claude', 'gpt'))
            retry = reset_date(cooldown.get('retry_at'))
            if matches and retry and retry > now:
                cooldowns.append(retry)
        if cooldowns:
            reset = max(cooldowns + ([reset] if tier == 3 and reset else []))
            tier, reason = 3, 'Proxy temporarily excluded this account for this group'
        rows.append({'name': account['name'], 'reset': reset.isoformat() if reset else None,
                     'tier': tier, 'reason': reason, 'remaining': min((b['remaining'] for b in known), default=None),
                     '_sort': (tier, reset.timestamp() if reset else float('inf'), min((b['remaining'] for b in known), default=1), account['name'])})
    rows.sort(key=lambda r: r['_sort'])
    for index, row in enumerate(rows):
        row.pop('_sort')
        row['priority'] = len(rows) - index
    return rows
