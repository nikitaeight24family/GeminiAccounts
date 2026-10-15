"""Account-scoped gateway catalog; failed reads never mean model retirement."""
import time
import urllib.parse


class ModelInventory:
    def __init__(self, controller, state, clock=time.time):
        self.controller, self.state, self.clock = controller, state, clock

    def refresh(self, public_models=None, aliases=None):
        from concurrent.futures import ThreadPoolExecutor
        files = self.controller.request('/auth-files')['files']
        if not isinstance(files, list):
            raise ValueError('Invalid account catalog')
        current = {}
        active = [a for a in files if not a.get('disabled')]

        def fetch_models(account):
            name = account['name']
            response = self.controller.request('/auth-files/models?' + urllib.parse.urlencode({'name': name}))
            entries = response.get('models', [])
            if not isinstance(entries, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in entries):
                raise ValueError('Invalid model catalog')
            return name, {
                'provider': account.get('provider', account.get('type', '')),
                'models': sorted({m['id'] for m in entries})
            }

        if active:
            with ThreadPoolExecutor(max_workers=min(12, len(active))) as pool:
                for name, data in pool.map(fetch_models, active):
                    current[name] = data
        observed = {m for a in current.values() for m in a['models']}
        if public_models is not None:
            # Include API-key services and exclude routes the serving endpoint
            # cannot currently supply, even if an account catalog is stale.
            observed = set(public_models)
        if aliases is not None:
            from model_policy import canonical_models
            observed = canonical_models(observed, aliases)
        now = self.clock()
        previous = set(self.state.get('models', []))
        missing = self.state.get('missing', {})
        pending = {m: missing.get(m, now) for m in previous - set(observed)}
        # A second complete snapshot at least one minute later confirms retirement.
        retained = {m for m, since in pending.items() if now - since < 60}
        if aliases is not None:
            retained = canonical_models(retained, aliases)
        self.state.update(accounts=current, models=sorted(set(observed) | retained),
                          missing=pending, checkedAt=now)
        return set(self.state['models'])
