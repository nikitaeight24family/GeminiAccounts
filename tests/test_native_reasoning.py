import copy
import unittest
from native_reasoning import remove_legacy_summary_rule, SUMMARY_RULE

class NativeReasoningTests(unittest.TestCase):
    def test_fresh_configuration_is_not_modified(self):
        config = {'requests': {'streaming': {'keepalive-seconds': 5}}}
        original = copy.deepcopy(config)
        self.assertFalse(remove_legacy_summary_rule(config))
        self.assertEqual(config, original)

    def test_only_our_exact_rule_is_removed_and_migration_is_idempotent(self):
        own = copy.deepcopy(SUMMARY_RULE)
        custom = {'models':[{'name':'gemini-*'}], 'params':{'generationConfig.thinkingConfig.includeThoughts':False}}
        config = {'requests':{'payload':{'default':[own, custom]}}}
        self.assertTrue(remove_legacy_summary_rule(config))
        self.assertEqual(config['requests']['payload']['default'], [custom])
        self.assertFalse(remove_legacy_summary_rule(config))
