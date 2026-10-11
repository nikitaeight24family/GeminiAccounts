"""Refresh configured ChatGPT reserves before routing generation requests."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from chatgpt_auth import ChatGPTAuth
from quota_limits import sync_quota_limits

class QuotaGuard:
    def __init__(self, controller):
        self.controller = controller
        self.lock = threading.Lock()

    def __call__(self, model):
        if not model.startswith('gpt-'):
            return
        with self.lock:
            c = self.controller
            c.preferences = json.loads(c.settings_path.read_text(encoding='utf-8'))
            floors = c.preferences.get('quota-floors', {})
            if not isinstance(floors, dict) or not any(isinstance(v, dict) and 'openai' in v for v in floors.values()):
                return
            auth = ChatGPTAuth(c)
            accounts = [a for a in auth.accounts() if not a.get('disabled') and
                        isinstance(floors.get(a['name']), dict) and 'openai' in floors[a['name']]]
            def refresh(account):
                quota = auth.quota(account)
                if quota.get('error'):
                    # Unknown quota is held when a nonzero reserve is configured.
                    sync_quota_limits(c, account, [])
            if accounts:
                with ThreadPoolExecutor(max_workers=min(4, len(accounts))) as pool:
                    list(pool.map(refresh, accounts))
