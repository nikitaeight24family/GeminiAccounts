import base64
import json
import tempfile
import unittest
from pathlib import Path

from account_archive import AccountError, read_archive, write_archive


def jwt(email, account_id):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=').decode()
    return part({'alg': 'none'}) + '.' + part({'email': email, 'https://api.openai.com/auth': {
        'chatgpt_account_id': account_id, 'chatgpt_plan_type': 'free'}}) + '.signature'


class AccountArchiveTests(unittest.TestCase):
    def test_cross_platform_round_trip_keeps_one_google_and_one_openai_record(self):
        records = [
            {'provider': 'antigravity', 'name': 'antigravity-google@example.com.json', 'payload': {
                'type': 'antigravity', 'email': 'google@example.com', 'access_token': 'access',
                'refresh_token': 'refresh', 'project_id': 'project'}, 'metadata': {'priority': 2}},
            {'provider': 'codex', 'name': 'codex-import-openai.json', 'payload': {
                'type': 'codex', 'email': 'openai@example.com', 'account_id': 'account-id',
                'id_token': jwt('openai@example.com', 'account-id'), 'access_token': 'access',
                'refresh_token': 'refresh', 'expired': '2030-01-01T00:00:00Z'}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'accounts.omni-archive'
            result = write_archive(path, records, 'portable-test-password', [{
                'email': 'openai@example.com', 'password': 'password', 'secret': 'JBSWY3DPEHPK3PXP'}])
            self.assertEqual(result['accounts'], 2)
            restored = read_archive(path, 'portable-test-password')
        self.assertEqual([item['provider'] for item in restored['records']], ['antigravity', 'codex'])
        self.assertEqual(restored['records'][0]['payload']['refresh_token'], 'refresh')
        self.assertEqual(restored['records'][1]['payload']['account_id'], 'account-id')
        self.assertEqual(restored['automatic_credentials'][0]['email'], 'openai@example.com')

    def test_wrong_password_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'accounts.omni-archive'
            write_archive(path, [{'provider': 'antigravity', 'name': 'google.json', 'payload': {
                'type': 'antigravity', 'email': 'google@example.com', 'access_token': 'a',
                'refresh_token': 'r'}}], 'portable-test-password')
            with self.assertRaises(AccountError):
                read_archive(path, 'wrong-password')


if __name__ == '__main__':
    unittest.main()
