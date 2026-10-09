import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routing import rank_accounts, quota_projection


class RoutingTests(unittest.TestCase):
    def test_nearest_five_hour_reset_wins_independently_of_weekly_reset(self):
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        accounts = [{'name': 'a'}, {'name': 'b'}]
        caches = {}
        for name, gemini_hours, claude_hours, week_hours in [('a', 4, 1, .1), ('b', 1, 4, 100)]:
            caches[name] = {'at': now, 'data': {'groups': [
                {'kind': group, 'buckets': [
                    {'window': '5h', 'remaining': .5, 'reset': (now + timedelta(hours=hours)).isoformat()},
                    {'window': 'weekly', 'remaining': .5, 'reset': (now + timedelta(hours=week_hours)).isoformat()}]}
                for group, hours in [('gemini', gemini_hours), ('claude', claude_hours)]]}}
        self.assertEqual(rank_accounts(accounts, caches, 'gemini', now)[0]['name'], 'b')
        self.assertEqual(rank_accounts(accounts, caches, 'claude', now)[0]['name'], 'a')
        self.assertEqual(rank_accounts(accounts, caches, 'gemini', now)[0]['reset'], (now + timedelta(hours=1)).isoformat())

    def test_weekly_projection_restores_used_portions_at_cumulative_percentages(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        entries = [
            {'remaining': value, 'reset': (now + timedelta(days=days)).isoformat(),
             'weekly_remaining': 1}
            for value, days in ((.3, 2), (.6, 1), (1, 3))
        ]
        result = quota_projection(entries, now, exhausted_only=False)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['reset'], (now + timedelta(days=1)).isoformat())
        self.assertAlmostEqual(result[0]['remaining'], 2.3 / 3)
        self.assertAlmostEqual(result[1]['remaining'], 1)
        self.assertEqual(quota_projection(entries, now), [])

    def test_provider_weekly_lock_overrides_dust_remaining_without_crossing_families(self):
        from routing import quota_entry
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        week = (now + timedelta(days=4)).isoformat()
        bucket = {'remaining': 1, 'reset': (now + timedelta(hours=2)).isoformat()}
        weekly = {'remaining': .0023603332, 'reset': week}
        account = {'cooldowns': [{'scope': 'model', 'model_key': 'gemini-pro-agent',
                    'reason': 'quota', 'retry_at': week}]}
        entry = quota_entry(account, bucket, weekly, 'gemini', now)
        self.assertEqual(entry['remaining'], 0)
        self.assertEqual(quota_projection([entry], now), [{'remaining': 1, 'reset': week}])
        account['cooldowns'][0]['model_key'] = 'claude-opus-4-6-thinking'
        self.assertEqual(quota_entry(account, bucket, weekly, 'gemini', now)['remaining'], 1)
        account['cooldowns'][0].update(model_key='gemini-pro-agent', retry_at=(now - timedelta(seconds=1)).isoformat())
        self.assertEqual(quota_entry(account, bucket, weekly, 'gemini', now)['remaining'], 1)

    def test_weekly_exhaustion_blocks_full_partial_and_expired_five_hour_buckets(self):
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        week = (now + timedelta(days=3)).isoformat()
        for remaining in (0, .5, 1):
            for hours in (-1, 2):
                with self.subTest(remaining=remaining, hours=hours):
                    result = quota_projection([{'remaining': remaining,
                        'reset': (now + timedelta(hours=hours)).isoformat(),
                        'weekly_remaining': 0, 'weekly_reset': week}], now)
                    self.assertEqual(result, [{'reset': week, 'remaining': 1}])
        later = (now + timedelta(days=4)).isoformat()
        self.assertEqual(quota_projection([{'remaining': 0, 'reset': later,
            'weekly_remaining': 0, 'weekly_reset': week}], now)[0]['reset'], later)
        self.assertEqual(quota_projection([{'remaining': 1, 'weekly_remaining': 0}], now), [])

    def test_projection_restores_each_account_and_waits_for_weekly_reset(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        def entry(remaining, hours, weekly=1):
            return {'remaining': remaining, 'reset': (now + timedelta(hours=hours)).isoformat(),
                    'weekly_remaining': weekly, 'weekly_reset': (now + timedelta(days=3)).isoformat()}
        result = quota_projection([entry(.2, 1), entry(0, 2), entry(0, 1, 0)], now)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]['remaining'], 1.2 / 3)
        self.assertAlmostEqual(result[1]['remaining'], 2.2 / 3)
        self.assertEqual(result[0]['reset'], (now + timedelta(hours=2)).isoformat())
        self.assertEqual(result[1]['reset'], (now + timedelta(days=3)).isoformat())
        # Unknown weekly limits and elapsed reset times do not invent quota.
        unknown = entry(0, 1, None)
        expired = entry(0, -1)
        self.assertEqual(quota_projection([unknown, expired], now), [])
        self.assertEqual(quota_projection([entry(1, 2)], now), [])
        self.assertEqual(quota_projection([entry(.001, 2)], now), [])

    def test_usable_quota_before_fast_but_exhausted_account(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        accounts = [{'name': n, 'disabled': n == 'disabled'} for n in ('slow', 'fast', 'empty', 'weekly-empty', 'unknown', 'disabled')]
        caches = {}
        def quota(name, hours, remaining=.5, weekly=.5):
            caches[name] = {'at': now, 'data': {'groups': [{'kind': 'gemini', 'buckets': [
                {'window': '5h', 'remaining': remaining, 'reset': (now + timedelta(hours=hours)).isoformat()},
                {'window': 'weekly', 'remaining': weekly, 'reset': (now + timedelta(days=2)).isoformat()}]}]}}
        quota('slow', 4)
        quota('fast', 2)
        quota('empty', 1, 0)
        quota('weekly-empty', 1, weekly=0)
        quota('disabled', .5)
        rows = rank_accounts(accounts, caches, 'gemini', now)
        self.assertEqual([r['name'] for r in rows], ['fast', 'slow', 'unknown', 'empty', 'weekly-empty'])
        self.assertEqual(rows[0]['priority'], 5)
        self.assertEqual(rows[-1]['reset'], (now + timedelta(days=2)).isoformat())
        caches['fast']['at'] = now - timedelta(minutes=4)
        self.assertEqual(rank_accounts(accounts, caches, 'gemini', now)[0]['name'], 'slow')
        quota('fast', -1)
        self.assertEqual(rank_accounts(accounts, caches, 'gemini', now)[0]['name'], 'slow')
        self.assertTrue(all(r['tier'] == 2 for r in rank_accounts(accounts, caches, 'claude', now)))

    def test_model_cooldown_only_blocks_matching_group(self):
        now = datetime.now(timezone.utc)
        account = {'name': 'a', 'cooldowns': [{'scope': 'model', 'model_key': 'gemini-3.1-pro-low', 'retry_at': (now + timedelta(hours=1)).isoformat()}]}
        self.assertEqual(rank_accounts([account], {}, 'gemini', now)[0]['tier'], 3)
        self.assertEqual(rank_accounts([account], {}, 'claude', now)[0]['tier'], 2)


if __name__ == '__main__':
    unittest.main()
