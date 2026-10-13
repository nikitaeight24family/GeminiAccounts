"""Persist pending ChatGPT OAuth states so callbacks survive app restarts."""
import json
import time

from backend import atomic_write


OAUTH_SESSION_TTL = 30 * 60


class PendingChatGPTLogins:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self.sessions = {}
        self._load()

    def _load(self):
        try:
            rows = json.loads(self.path.read_text('utf-8'))
        except (OSError, ValueError, TypeError):
            rows = []
        now = self.clock()
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            state, expires_at = row.get('state'), row.get('expires_at')
            if (isinstance(state, str) and state and isinstance(expires_at, (int, float))
                    and expires_at > now):
                self.sessions[state] = {'state': state, 'url': str(row.get('url') or ''),
                                        'created_at': float(row.get('created_at', now)),
                                        'expires_at': float(expires_at),
                                        'provider': row.get('provider', 'openai'),
                                        'user_code': str(row.get('user_code') or '')}
        self.save()

    def save(self):
        self.prune()
        rows = sorted(self.sessions.values(), key=lambda row: row['created_at'])
        atomic_write(self.path, json.dumps(rows, ensure_ascii=False, indent=2).encode('utf-8'))

    def prune(self):
        now = self.clock()
        for state in tuple(self.sessions):
            if self.sessions[state]['expires_at'] <= now:
                del self.sessions[state]

    def add(self, state, url, provider='openai', user_code=''):
        now = self.clock()
        self.prune()
        self.sessions[state] = {'state': state, 'url': url, 'created_at': now,
                                'expires_at': now + OAUTH_SESSION_TTL,
                                'provider': provider, 'user_code': user_code}
        self.save()

    def get(self, state):
        self.prune()
        return self.sessions.get(state)

    def all(self):
        self.prune()
        return sorted(self.sessions.values(), key=lambda row: row['created_at'], reverse=True)

    def remove(self, state):
        existed = self.sessions.pop(state, None) is not None
        self.save()
        return existed
