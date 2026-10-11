"""Provider API credentials stored only in the gateway's credential configuration."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import yaml
from backend import AccountError
from tokenharbor import TokenHarbor

SERVICES = {
    'Gemini': ('gemini', 'https://generativelanguage.googleapis.com', '/v1beta/models'),
    'Claude': ('claude', 'https://api.anthropic.com', '/v1/models'),
    'OpenAI': ('openai-compatibility', 'https://api.openai.com/v1', '/models'),
    'Grok': ('xai', 'https://api.x.ai/v1', '/models'),
    'TokenHarbor': ('openai-compatibility', 'https://tokenharbor.ai/v1', '/models'),
}
PREFIX = 'omni-api-'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class APIAccounts:
    def __init__(self, controller, lock=None):
        self.controller = controller
        self.lock = lock or threading.RLock()

    def config(self):
        path = self.controller.proxy_dir / 'config.yaml'
        config = yaml.safe_load(path.read_text('utf-8-sig'))
        if not isinstance(config, dict):
            raise AccountError('Invalid gateway configuration.')
        return path, config

    @staticmethod
    def discover(service, key):
        if service not in SERVICES or not key or any(c.isspace() for c in key):
            raise AccountError('Enter a valid API key.')
        _, base, endpoint = SERVICES[service]
        headers = {'Authorization': 'Bearer '+key}
        if service == 'Gemini': headers = {'x-goog-api-key': key}
        if service == 'Claude': headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
        models = {}
        query = {}
        seen = set()
        opener = urllib.request.build_opener(NoRedirect())
        for _ in range(50):
            url = base+endpoint + ('?'+urllib.parse.urlencode(query) if query else '')
            try:
                with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
                    body = json.load(response)
            except urllib.error.HTTPError as error:
                raise AccountError(f'{service} API · HTTP {error.code}') from None
            except (OSError, ValueError):
                raise AccountError(f'{service} API unavailable.') from None
            if not isinstance(body, dict): raise AccountError('Invalid model catalog.')
            for model in body.get('models' if service=='Gemini' else 'data', []):
                if not isinstance(model, dict): continue
                name = model.get('name' if service=='Gemini' else 'id')
                if not isinstance(name, str) or not name: continue
                if service=='Gemini':
                    if 'generateContent' not in model.get('supportedGenerationMethods', []): continue
                    name = name.removeprefix('models/')
                elif service=='OpenAI' and not name.startswith(('gpt-','chatgpt-','o1','o3','o4','codex')):
                    continue
                models[name] = {'name': name, 'alias': name,
                                'display-name': model.get('displayName') or model.get('display_name') or name}
            token = body.get('nextPageToken') if service=='Gemini' else body.get('last_id') if body.get('has_more') else None
            if not token: break
            if token in seen: raise AccountError('Invalid catalog pagination.')
            seen.add(token)
            query = {'pageToken' if service=='Gemini' else 'after_id': token}
        else: raise AccountError('Model catalog is too large.')
        if not models: raise AccountError(f'{service} did not return available chat models.')
        return list(models.values())

    def add(self, service, key, label=''):
        key = key.strip()
        models = self.discover(service, key)
        channel, base, _ = SERVICES[service]
        identity = PREFIX+service.lower()+'-'+hashlib.sha256(key.encode()).hexdigest()[:16]
        models = [dict(model, alias='api-'+service.lower()+'/'+model['name'], **{'force-mapping': True}) for model in models]
        group = {'name': identity, 'base-url': base,
                 'models': models, 'keys': [{'api-key': key}], 'priority': 0}
        with self.lock:
            path, config = self.config()
            if config.get('server',{}).get('host') not in ('127.0.0.1','localhost'):
                raise AccountError('The gateway must be local.')
            groups = config.setdefault('api-keys',{}).setdefault(channel,[])
            existing = next((g for g in groups if g.get('name') == identity), None)
            if existing:
                group['priority'] = existing.get('priority', 0)
            groups[:] = [g for g in groups if g.get('name')!=identity]
            groups.append(group)
            previous = path.read_bytes()
            try:
                TokenHarbor.write_live_config(path, yaml.safe_dump(config,sort_keys=False).encode())
                for _ in range(40):
                    if self.live_index(channel, key, identity):
                        break
                    time.sleep(.15)
                else:
                    raise AccountError('Gateway did not register the API credential.')
            except Exception:
                TokenHarbor.write_live_config(path, previous)
                raise AccountError('The gateway did not accept the key. Previous settings restored.') from None
            self.controller.preferences.setdefault('api-account-labels',{})[identity] = label.strip()[:64] or service+' API'
            self.controller.save()
        return identity

    def live_index(self, channel, key, identity, snapshots=None):
        endpoint = 'openai-compatibility' if channel == 'openai-compatibility' else channel+'-api-key'
        if snapshots is not None and endpoint in snapshots:
            rows = snapshots[endpoint]
        else:
            rows = self.controller.request('/'+endpoint).get(endpoint, [])
            if snapshots is not None:
                snapshots[endpoint] = rows
        for row in rows:
            if channel == 'openai-compatibility':
                if row.get('name') != identity:
                    continue
                for entry in row.get('api-key-entries', []):
                    if entry.get('api-key') == key:
                        return entry.get('auth-index')
            elif row.get('api-key') == key:
                return row.get('auth-index')
        return None

    def accounts(self, live=False):
        _, config = self.config()
        rows = []
        labels = self.controller.preferences.get('api-account-labels',{})
        snapshots = {}
        statuses = {}
        if live:
            statuses = {a.get('auth_index'): a for a in self.controller.request('/auth-files').get('files', [])}
        for service,(channel,_,_) in SERVICES.items():
            for group in config.get('api-keys',{}).get(channel,[]) + config.get('omni-paused-api-accounts',{}).get(channel,[]):
                name = group.get('name','')
                if not name.startswith(PREFIX+service.lower()+'-'): continue
                row = {'name':name,'email':labels.get(name,service+' API'),
                             'provider':service.lower(),'priority':group.get('priority',0),
                             'models':[m.get('name','') for m in group.get('models',[])],
                             'disabled':group.get('disabled',False)}
                if live and not row['disabled']:
                    key = next((k.get('api-key') for k in group.get('keys', []) if k.get('api-key')), '')
                    index = self.live_index(channel, key, name, snapshots)
                    row['auth_index'] = index
                    row['registered'] = bool(index)
                    metadata = statuses.get(index, {})
                    for field in ('status', 'status_message', 'cooldowns', 'unavailable', 'success', 'failed'):
                        if field in metadata:
                            row[field] = metadata[field]
                rows.append(row)
        return sorted(rows,key=lambda a:(-a['priority'],a['email']))

    def remove(self, name):
        self.change(name, remove=True)

    def set_paused(self, name, paused):
        """Keep the credential in the protected config, outside the live key list."""
        if not name.startswith(PREFIX):
            raise AccountError('Unmanaged API credential.')
        with self.lock:
            path, config = self.config()
            source = config.setdefault('api-keys' if paused else 'omni-paused-api-accounts', {})
            destination = config.setdefault('omni-paused-api-accounts' if paused else 'api-keys', {})
            for channel, groups in source.items():
                for group in list(groups):
                    if group.get('name') != name:
                        continue
                    groups.remove(group)
                    if paused:
                        group['disabled'] = True
                    else:
                        group.pop('disabled', None)
                    destination.setdefault(channel, []).append(group)
                    TokenHarbor.write_live_config(path, yaml.safe_dump(config, sort_keys=False).encode())
                    return
            if any(group.get('name') == name for groups in destination.values() for group in groups):
                return
            raise AccountError('API credential no longer exists.')

    def change(self, name, delta=0, remove=False):
        if not name.startswith(PREFIX): raise AccountError('Unmanaged API credential.')
        with self.lock:
            path,config = self.config()
            found = False
            for groups in list(config.get('api-keys',{}).values()) + list(config.get('omni-paused-api-accounts',{}).values()):
                if not isinstance(groups,list): continue
                for group in list(groups):
                    if group.get('name')!=name: continue
                    found=True
                    if remove: groups.remove(group)
                    else: group['priority']=min(999,max(0,group.get('priority',0)+delta))
            if not found: raise AccountError('API credential no longer exists.')
            TokenHarbor.write_live_config(path,yaml.safe_dump(config,sort_keys=False).encode())
            if remove:
                self.controller.preferences.get('api-account-labels',{}).pop(name,None)
                self.controller.save()
