"""Classify provider failures without exposing or persisting their raw bodies."""
import json


def failure_reason(code, body=None):
    if code != 429:
        return None
    try:
        value = json.loads(body) if isinstance(body, (str, bytes)) else body
    except (ValueError, TypeError):
        value = None
    error = value.get('error', value) if isinstance(value, dict) else {}
    if not isinstance(error, dict):
        error = {}
    details = error.get('details')
    details = details if isinstance(details, list) else []
    reasons = {str(d.get('reason', '')).upper() for d in details if isinstance(d, dict)}
    message = str(error.get('message', '')).lower()
    if reasons & {'RATE_LIMIT_EXCEEDED', 'RESOURCE_EXHAUSTED_TEMPORARILY'} or 'rate limit' in message or 'too many requests' in message:
        return 'Google 429: temporary request rate limit; waiting to retry'
    if reasons & {'MODEL_CAPACITY_EXHAUSTED', 'CAPACITY_EXHAUSTED'} or any(s in message for s in ('capacity', 'high demand', 'overloaded')):
        return 'Google 429: model capacity unavailable; waiting to retry'
    if reasons & {'QUOTA_EXHAUSTED', 'QUOTA_EXCEEDED'} or 'quota' in message and any(s in message for s in ('exhausted', 'exceeded')):
        return 'Google 429: quota exhausted for this model'
    return 'Google 429: provider restricted this model; exact cause unavailable'
