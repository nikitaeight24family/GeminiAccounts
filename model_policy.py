"""Select only advertised text models; never invent a version or a fallback ID."""
import re


def text_models(models):
    return {m for m in models if isinstance(m, str) and m and
            not any(word in m.lower() for word in ('image', 'embedding', 'audio', 'video'))}


def version_key(model):
    return tuple(int(n) for n in re.findall(r'\d+', model))


def select_model(models, preferred=None, family=None, cheap=False):
    candidates = text_models(models)
    if family:
        candidates = {m for m in candidates if m.startswith(family + '-')}
    if preferred in candidates:
        return preferred
    if cheap:
        for tier in ('lite', 'luna', 'haiku', 'gpt-oss', 'extra-low', 'low', 'mini', 'flash'):
            tier_models = {m for m in candidates if tier in m and
                           (tier == 'gpt-oss' or not m.endswith(('-high', '-medium')))}
            if tier_models:
                return max(tier_models, key=lambda m: (version_key(m), m))
        return None
    return max(candidates, key=lambda m: (version_key(m), m), default=None)


def canonical_models(models, aliases):
    # An alias is a route, not an additional model in the model picker.
    return text_models(m for m in models if '-4-5-ga-' not in m and
                       m not in ('gemini-selected', 'claude-selected') and
                       (m not in aliases or aliases[m] == m))
