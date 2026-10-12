import json
import unittest
from account_uptime import update_uptime


class AccountUptimeTests(unittest.TestCase):
    def test_ban_freezes_across_restart_and_login_resumes(self):
        states = {}
        account = {'name': 'a', 'status': 'active', 'created_at': '1970-01-01T00:00:00Z'}
        self.assertEqual(update_uptime(states, account, 3600)[0], '1h 00m')
        account['status'] = 'blocked'
        frozen, _ = update_uptime(states, account, 7200)
        states = json.loads(json.dumps(states))
        self.assertEqual(update_uptime(states, account, 10000)[0], frozen)
        account['status'] = 'active'
        update_uptime(states, account, 10000)
        self.assertEqual(update_uptime(states, account, 13600)[0], '3h 00m')

    def test_401_stops_but_quota_wait_and_pause_do_not(self):
        states = {}
        account = {'name': 'a', 'status': 'active'}
        update_uptime(states, account, 1000)
        account['disabled'] = True
        self.assertEqual(update_uptime(states, account, 4600)[0], '1h 00m')
        account['disabled'] = False
        account['quota'] = {'error': 'Quota HTTP 401'}
        frozen, _ = update_uptime(states, account, 5000)
        self.assertEqual(update_uptime(states, account, 9000)[0], frozen)
        account['quota'] = {'error': 'Quota HTTP 503'}
        self.assertEqual(update_uptime(states, account, 9500)[0], frozen)

    def test_new_key_starts_now_and_stable_ticks_do_not_write(self):
        states = {}
        account = {'name': 'key', 'status': 'active'}
        self.assertTrue(update_uptime(states, account, 1000)[1])
        self.assertFalse(update_uptime(states, account, 1060)[1])
        self.assertEqual(update_uptime(states, account, 1060)[0], '0h 01m')
