"""Concrete upstream model names, retaining version and variant information."""
DEFAULT_ALIASES = {'claude-sonnet-4-5': 'gemini-3.1-pro-low', 'claude-haiku-4-5': 'gemini-3-flash'}


def model_name(model, aliases=None):
    model = (DEFAULT_ALIASES if aliases is None else aliases).get(model, model)
    known = {
        'claude-sonnet-4-6': 'Sonnet 4.6',
        'claude-opus-4-6-thinking': 'Opus 4.6 Thinking',
    }
    if model in known:
        return known[model]
    if model.startswith('gemini-'):
        return ' '.join(word.title() for word in model[7:].split('-'))
    # Do not truncate or strip model variants from other providers.
    return model
