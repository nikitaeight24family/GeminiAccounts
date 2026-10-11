import tempfile
import unittest
from pathlib import Path
from token_capacity import TokenCapacity


class TokenCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'capacity.json'
        self.calculator = TokenCapacity(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def observe(self, remaining, tokens, reset='2099-01-01T00:00:00+00:00', plan='plus', window='5h'):
        self.calculator.observe('one', 'OpenAI', plan,
            [{'kind': 'openai', 'buckets': [{'window': window, 'remaining': remaining, 'reset': reset}]}], tokens)

    def test_capacity_is_weighted_by_consumed_quota_and_survives_restart(self):
        self.observe(1, {'model': 100})
        self.observe(.99, {'model': 1100})
        self.observe(.97, {'model': 3100})
        self.observe(.96, {'model': 4100})
        row = TokenCapacity(self.path).rows()[0]
        self.assertEqual(row['capacity'], 100000)
        self.assertEqual(row['samples'], 3)
        self.assertTrue(row['ready'])
        self.assertEqual(row['tokens'], 4000)
        self.observe(.96, {'model': 4100})
        self.assertEqual(self.calculator.rows()[0]['samples'], 3)

    def test_rounding_accumulates_tokens_until_quota_changes(self):
        self.observe(1, {'model': 0})
        self.observe(1, {'model': 300})
        self.observe(.995, {'model': 500})
        self.assertFalse(self.calculator.rows())
        self.observe(.99, {'model': 1000})
        self.assertEqual(self.calculator.rows()[0]['capacity'], 100000)
        self.assertFalse(self.calculator.rows()[0]['ready'])

    def test_reset_mixed_models_and_external_only_usage_do_not_create_samples(self):
        self.observe(1, {'a': 0, 'b': 0})
        self.observe(.98, {'a': 1000, 'b': 1000})
        self.observe(.96, {'a': 1000, 'b': 1000})
        self.observe(1, {'a': 1000, 'b': 1000})
        self.observe(.98, {'a': 2000, 'b': 1000}, reset='2099-02-01T00:00:00+00:00')
        self.assertFalse(self.calculator.rows())
        self.observe(.97, {'a': 3000, 'b': 1000}, reset='2099-02-01T00:00:02+00:00')
        self.assertEqual(self.calculator.rows()[0]['capacity'], 100000)

    def test_plan_and_window_are_separate_and_missing_window_stays_unknown(self):
        self.observe(1, {'a': 0}, window='weekly')
        self.observe(.99, {'a': 2000}, window='weekly')
        self.observe(.9, {'a': 2000}, plan='pro')
        self.observe(.89, {'a': 3000}, plan='pro')
        rows = self.calculator.rows()
        self.assertEqual([(r['plan'], r['window'], r['capacity']) for r in rows],
                         [('plus', 'weekly', 200000), ('pro', '5h', 100000)])

    def test_invalid_percentages_and_counter_reset_do_not_create_samples(self):
        for value in (None, True, float('nan'), -1, 2):
            self.observe(value, {'a': 100})
        self.assertFalse(self.calculator.state['baselines'])
        self.observe(1, {'a': 1000})
        self.observe(.98, {'a': 100})
        self.assertFalse(self.calculator.rows())
