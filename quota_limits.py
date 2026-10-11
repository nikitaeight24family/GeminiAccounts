"""User-defined minimum remaining quota, independent for each account/window."""
import math


def quota_floor(preferences, name, group, window):
    limits = preferences.get('quota-floors', {})
    if not isinstance(limits, dict):
        return 0
    account = limits.get(name, {})
    family = account.get(group, {}) if isinstance(account, dict) else {}
    value = family.get(window, 0) if isinstance(family, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 else 0


def blocked_families(preferences, name, groups):
    blocked = set()
    indexed = {group['kind']: {bucket.get('window'): bucket for bucket in group.get('buckets', [])} for group in groups}
    limits = preferences.get('quota-floors', {})
    configured = limits.get(name, {}) if isinstance(limits, dict) else {}
    for kind in set(indexed) | (set(configured) if isinstance(configured, dict) else set()):
        for window in ('5h', 'weekly'):
            bucket = indexed.get(kind, {}).get(window, {'window': window})
            floor = quota_floor(preferences, name, kind, bucket.get('window'))
            remaining = bucket.get('remaining')
            if floor and (not isinstance(remaining, (int, float)) or isinstance(remaining, bool)
                          or not math.isfinite(remaining) or remaining * 100 <= floor + 1e-7):
                blocked.add(kind)
    return blocked


def sync_quota_limits(controller, account, groups):
    preferences = controller.preferences
    configured = preferences.get('quota-floors', {})
    if not isinstance(configured, dict) or account['name'] not in configured:
        return set()
    import urllib.parse
    blocked = blocked_families(preferences, account['name'], groups)
    patterns = {'gemini': ['gemini*'], 'claude': ['claude*', 'gpt-oss*'], 'openai': ['*']}
    desired = sorted({pattern for kind in blocked for pattern in patterns.get(kind, [])})
    # The authenticated management API reads metadata locally; tokens never enter UI/storage.
    metadata = controller.request('/auth-files/download?' + urllib.parse.urlencode({'name': account['name']}))
    original = metadata.get('excluded_models', metadata.get('excluded-models', [])) or []
    managed = metadata.get('omni_quota_exclusions', []) or []
    base = [item for item in original if item not in managed]
    merged = sorted(set(base + desired))
    owned = [item for item in desired if item not in base]
    if merged != sorted(original) or owned != sorted(managed):
        controller.request('/auth-files/fields', 'PATCH', {
            'name': account['name'], 'excluded_models': merged, 'omni_quota_exclusions': owned})
    return blocked
