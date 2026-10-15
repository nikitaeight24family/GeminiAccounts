"""Model and plan routing helpers for ChatGPT OAuth accounts.

The gateway is the source of truth for the model catalog.  These helpers keep
the UI and request guard independent of any particular model name.
"""


def normalized_plan(account):
    quota = account.get('quota') or {}
    id_token = account.get('id_token') or {}
    value = quota.get('plan_type') or account.get('plan_type') or id_token.get('plan_type') or ''
    return str(value).strip().lower().replace('_', ' ').replace('-', ' ')


def is_free_account(account):
    value = normalized_plan(account)
    return value in {'free', 'free tier', 'chatgpt free'} or value.startswith('free ')


def supported_models(account):
    """Return provider-reported GPT model ids for one account.

    Different gateway versions expose this catalog under different metadata
    fields, so accept all known shapes and ignore non-model values.
    """
    values = []
    for key in ('supported_models', 'models', 'model_ids'):
        raw = account.get(key)
        if isinstance(raw, dict):
            values.extend(raw.keys())
        elif isinstance(raw, (list, tuple, set)):
            values.extend(raw)
    quota = account.get('quota') or {}
    for key in ('model_quotas', 'models'):
        raw = quota.get(key)
        if isinstance(raw, dict):
            values.extend(raw.keys())
        elif isinstance(raw, (list, tuple, set)):
            values.extend(raw)
    return frozenset(value.strip() for value in values
                     if isinstance(value, str) and value.strip().startswith('gpt-'))


def free_model_catalog(accounts):
    """Union of models supported by currently enabled free accounts."""
    result = set()
    for account in accounts:
        if not account.get('disabled') and is_free_account(account):
            result.update(supported_models(account))
    return frozenset(result)


def accounts_for_model(accounts, model):
    """Keep Free credentials away from paid-only GPT model requests.

    A missing or stale Free catalog must fail closed.  Previously an empty
    catalog made this function return every account, allowing a paid model
    such as Sol to be attempted on a Free credential before the next catalog
    refresh completed.
    """
    free = free_model_catalog(accounts)
    if model not in free:
        return [account for account in accounts
                if not account.get('disabled') and not is_free_account(account)]
    return [account for account in accounts
            if not account.get('disabled') and is_free_account(account)
            and model in supported_models(account)]
