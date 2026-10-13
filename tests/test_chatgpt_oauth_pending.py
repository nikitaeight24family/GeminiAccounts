import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_auth import ChatGPTAuth
from chatgpt_oauth_pending import OAUTH_SESSION_TTL, PendingChatGPTLogins


class PendingChatGPTLoginTests(unittest.TestCase):
    def test_keeps_multiple_states_across_restart_and_expires_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending.json'
            now = [1000.0]
            store = PendingChatGPTLogins(path, clock=lambda: now[0])
            store.add('old', 'https://auth.openai.com/authorize?state=old')
            now[0] += 100
            store.add('new', 'https://auth.openai.com/authorize?state=new')

            now[0] += OAUTH_SESSION_TTL - 100
            restored = PendingChatGPTLogins(path, clock=lambda: now[0])

            self.assertEqual([row['state'] for row in restored.all()], ['new'])
            self.assertEqual(restored.get('new')['url'], 'https://auth.openai.com/authorize?state=new')
            self.assertEqual(restored.get('new')['provider'], 'openai')

    def test_removes_only_the_finished_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PendingChatGPTLogins(Path(directory) / 'pending.json', clock=lambda: 1)
            store.add('first', 'url-1', 'gemini')
            store.add('second', 'url-2')
            store.remove('first')
            self.assertEqual([row['state'] for row in store.all()], ['second'])
            self.assertEqual(store.get('first'), None)
            self.assertEqual(json.loads(store.path.read_text('utf-8'))[0]['state'], 'second')

    def test_callback_state_is_extracted_from_older_wrapped_links(self):
        self.assertEqual(ChatGPTAuth.callback_state(
            r'Blocked URL: \http://localhost:1455/auth/callback?code=abc\&state=older'), 'older')
        self.assertIsNone(ChatGPTAuth.callback_state('authorization-code-only'))


if __name__ == '__main__':
    unittest.main()
