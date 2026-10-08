"""Migration for the retired experimental thought-summary override."""

SUMMARY_RULE = {
    'models': [{'name': 'gemini-*', 'protocol': 'antigravity',
                'from-protocol': 'claude', 'exist': ['generationConfig.thinkingConfig']}],
    'params': {'generationConfig.thinkingConfig.includeThoughts': True},
}


def remove_legacy_summary_rule(config):
    """Remove only the exact experimental rule installed by versions 1.3.2–1.3.3."""
    rules = config.get('requests', {}).get('payload', {}).get('default', [])
    if not isinstance(rules, list) or SUMMARY_RULE not in rules:
        return False
    rules[:] = [rule for rule in rules if rule != SUMMARY_RULE]
    return True
