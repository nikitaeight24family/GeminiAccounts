"""Context limits of the bundled Antigravity provider catalog (CLIProxyAPI 8.0.16).

Claude's supported extended-context switch uses a 1,000,000-token budget,
conservatively within Gemini's 1,048,576-token input window.
"""
CONTEXT_WINDOWS = {
    'claude-haiku-4-5': 200000,
    'claude-sonnet-4-6': 200000,
    'claude-opus-4-6-thinking': 200000,
    'claude-sonnet-5-5-high': 1000000,
    'claude-opus-5-5-high': 1000000,
    'gemini-pro-agent': 1048576,
    'gemini-3.1-pro-low': 1048576,
    'gemini-3-flash': 1048576,
    'gemini-3.1-flash-lite': 1048576,
    'gemini-3.5-flash-lite': 1048576,
    'gemini-3-flash-agent': 1048576,
    'gemini-3.5-flash-low': 1048576,
    'gemini-3.5-flash-extra-low': 1048576,
    'gemini-3.6-flash-high': 1048576,
    'gemini-3.7-flash-high': 1048576,
    'gemini-3.8-flash-high': 1048576,
    'gemini-3.6-flash-medium': 1048576,
    'gemini-3.6-flash-low': 1048576,
    'gemini-3.7-flash-medium': 1048576,
    'gemini-3.7-flash-low': 1048576,
    'gemini-3.8-flash-medium': 1048576,
    'gemini-3.8-flash-low': 1048576,
    'gpt-oss-120b-medium': 114000,
}


def extended_context(model):
    return CONTEXT_WINDOWS.get(model, 0) >= 1000000


def client_model_id(alias, upstream):
    return alias + '[1m]' if extended_context(upstream) else alias


def strip_context_suffix(model):
    return model[:-4] if isinstance(model, str) and model.lower().endswith('[1m]') else model
