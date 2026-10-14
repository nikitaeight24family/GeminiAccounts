"""Concrete upstream model names, retaining version and variant information."""
DEFAULT_ALIASES = {'claude-sonnet-4-5': 'gemini-3.1-pro-low', 'claude-haiku-4-5': 'gemini-3-flash'}


def model_name(model, aliases=None):
    model = (DEFAULT_ALIASES if aliases is None else aliases).get(model, model)
    known = {
        'gemini-pro-agent': '3.1 Pro High',
        'gemini-3-flash-agent': '3.5 Flash High',
        'gemini-3.5-flash-low': '3.5 Flash Medium',
        'gemini-3.5-flash-extra-low': '3.5 Flash Low',
        'claude-haiku-4-5': 'Haiku 4.5',
        'claude-sonnet-4-6': 'Sonnet 4.6',
        'claude-opus-4-6-thinking': 'Opus 4.6 Thinking',
    }
    if model in known:
        return known[model]
    if model.startswith('gemini-'):
        return ' '.join(word.title() for word in model[7:].split('-'))
    # Do not truncate or strip model variants from other providers.
    return model


def reasoning_level(model):
    if model == 'gemini-3-flash-agent':
        return 'high'
    if model == 'gemini-3.5-flash-low':
        return 'medium'
    if model == 'gemini-3.5-flash-extra-low':
        return 'low'
    return next((level for level in ('high', 'medium', 'low') if model.endswith('-' + level)), 'medium')
