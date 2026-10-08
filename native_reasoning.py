"""Request separately marked Gemini thought summaries at the native boundary."""
import copy

SUMMARY_RULE = {
    'models': [{'name': 'gemini-*', 'protocol': 'antigravity',
                'from-protocol': 'claude', 'exist': ['generationConfig.thinkingConfig']}],
    'params': {'generationConfig.thinkingConfig.includeThoughts': True},
}


def ensure_summary_rule(config):
    """Default only: retain explicit visibility choices and existing payload rules."""
    rules = config.setdefault('requests', {}).setdefault('payload', {}).setdefault('default', [])
    if SUMMARY_RULE in rules:
        return False
    rules.append(copy.deepcopy(SUMMARY_RULE))
    return True
