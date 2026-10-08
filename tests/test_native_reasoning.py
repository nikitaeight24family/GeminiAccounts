import copy
import unittest
from native_reasoning import ensure_summary_rule, SUMMARY_RULE


class NativeReasoningTests(unittest.TestCase):
    def test_rule_is_scoped_to_thinking_gemini_anthropic_requests(self):
        model = SUMMARY_RULE['models'][0]
        self.assertEqual(model['protocol'], 'antigravity')
        self.assertEqual(model['from-protocol'], 'claude')
        self.assertEqual(model['exist'], ['generationConfig.thinkingConfig'])
        self.assertEqual(model['name'], 'gemini-*')

    def test_existing_rules_and_settings_preserved_and_idempotent(self):
        existing = {'models':[{'name':'gemini-*'}], 'params':{'generationConfig.thinkingConfig.includeThoughts':False}}
        config = {'requests':{'streaming':{'keepalive-seconds':5},'payload':{'default':[copy.deepcopy(existing)]}}}
        self.assertTrue(ensure_summary_rule(config))
        self.assertFalse(ensure_summary_rule(config))
        self.assertEqual(config['requests']['streaming']['keepalive-seconds'], 5)
        self.assertEqual(config['requests']['payload']['default'][0], existing)
        self.assertEqual(len(config['requests']['payload']['default']), 2)
