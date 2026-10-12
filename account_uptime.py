"""Persistent account lifetime, frozen only by confirmed credential loss."""
from datetime import datetime
from account_status import account_status


def update_uptime(states, account, now):
    name = account['name']
    label, _, _ = account_status({**account, 'disabled': False}, now)
    stopped = label in ('Account blocked', 'Sign in again')
    changed = name not in states
    if changed:
        try:
            added = datetime.fromisoformat(account['created_at'].replace('Z', '+00:00')).timestamp()
            added = min(now, added)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            added = now
        states[name] = {'seconds': 0, 'running_since': added}
    state = states[name]
    since = state.get('running_since')
    if stopped and since is not None:
        state['seconds'] += max(0, now - since)
        state['running_since'] = None
        changed = True
    elif not stopped and since is None:
        # Unknown/errors must not accidentally resume a logged-out account.
        quota = account.get('quota') or {}
        if not quota.get('error') and label in ('Available', 'Paused', 'Limit exhausted', 'Rate limited'):
            state['running_since'] = now
            changed = True
    seconds = state['seconds'] + (max(0, now - state['running_since']) if state.get('running_since') is not None else 0)
    minutes = int(seconds // 60)
    days, hours, minutes = minutes // 1440, minutes // 60 % 24, minutes % 60
    duration = f'{days}d {hours}h' if days else f'{hours}h {minutes:02}m'
    return duration + (' ⏸' if state.get('running_since') is None else ''), changed
