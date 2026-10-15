"""Bounded, automatic maintenance of explicitly connected local clients.

Inspection never sends prompts. It verifies configuration and the live model
catalog, not successful generation. Restarts always require separate consent.
"""
import base64
import copy
import json
import re
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from backend import AccountError, atomic_write, dpapi
from integrations import BEGIN, END
from model_context import strip_context_suffix
from model_inventory import ModelInventory

CLIENTS = {'codex': 'Codex', 'claude_desktop': 'Claude Desktop', 'claude_cli': 'Claude Code CLI'}


class ConnectionHealth:
    def __init__(self, integrations, clock=time.monotonic):
        self.integrations = integrations
        self.controller = integrations.controller
        self.clock = clock
        self.lock = threading.RLock()
        self.path = self.controller.data_dir / 'connection-health.dpapi'
        self.state = {'snapshots': {}, 'restart': {}}
        if self.path.exists():
            self.state.update(json.loads(dpapi(self.path.read_bytes(), decrypt=True)))
        self.last = []
        self.retry_after = {}
        self.inventory = ModelInventory(self.controller, self.state.setdefault('inventory', {}))
        self.catalog_after = 0

    def save(self):
        atomic_write(self.path, dpapi(json.dumps(self.state).encode()))

    def probe(self):
        key = (self.controller.proxy_dir / 'client-key.txt').read_text('utf-8-sig').strip()
        req = urllib.request.Request('http://127.0.0.1:8317/v1/models',
                                     headers={'Authorization': 'Bearer ' + key})
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as response:
                data = json.load(response)
            if not isinstance(data.get('data'), list):
                return {'error': 'invalid_gateway_response'}
            return {'models': {item['id'] for item in data['data'] if isinstance(item, dict) and isinstance(item.get('id'), str)}, 'key': key}
        except urllib.error.HTTPError as exc:
            return {'error': 'gateway_auth' if exc.code in (401, 403) else 'gateway_busy' if exc.code in (429, 503) else 'gateway_error'}
        except (OSError, ValueError):
            return {'error': 'gateway_unavailable'}

    def read(self, client):
        paths = self.integrations.paths()[client]
        path = paths[2] if client == 'claude_desktop' else paths[0]
        if not path.exists():
            return path, None
        text = path.read_text('utf-8-sig')
        return path, tomllib.loads(text) if client == 'codex' else json.loads(text)

    def owned(self, client):
        paths = self.integrations.paths()[client]
        backups = self.integrations.backups()
        return client in self.state['snapshots'] or any(str(p.resolve()) in backups for p in paths)

    def remember_good(self, client):
        snapshot = {str(p.resolve()): base64.b64encode(p.read_bytes()).decode()
                    for p in self.integrations.paths()[client] if p.exists()}
        if self.state['snapshots'].get(client) != snapshot:
            self.state['snapshots'][client] = snapshot
            self.save()

    def expected(self, client, doc, key):
        """Only transport settings are managed here; never change model selection."""
        if client == 'codex':
            provider = doc.get('model_providers', {}).get('gemini_accounts', {})
            values = {'base_url': 'http://127.0.0.1:8317/v1', 'wire_api': 'responses', 'experimental_bearer_token': key,
                      'requires_openai_auth': False}
            return provider, values
        if client == 'claude_cli':
            return doc.get('env', {}), {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317', 'ANTHROPIC_AUTH_TOKEN': key, 'ANTHROPIC_API_KEY': ''}
        return doc, {'inferenceGatewayBaseUrl': 'http://127.0.0.1:8317', 'inferenceGatewayApiKey': key,
                     'inferenceProvider': 'gateway', 'inferenceGatewayAuthScheme': 'bearer', 'inferenceCredentialKind': 'static'}

    def models(self, client, doc):
        if client == 'codex':
            return [doc.get('model', '')]
        if client == 'claude_cli':
            env = doc.get('env', {})
            return list(dict.fromkeys(env[k] for k in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL') if env.get(k)))
        return [item['name'] for item in doc.get('inferenceModels', []) if isinstance(item, dict) and isinstance(item.get('name'), str)]

    def inspect(self, client, gateway):
        paths = self.integrations.paths()[client]
        if client == 'codex':
            file_roles = ['Codex settings', 'Omni provider profile', 'Omni model catalog']
        elif client == 'claude_desktop':
            file_roles = ['Claude Desktop settings', 'Active profile index', 'Omni model profile']
        else:
            file_roles = ['Claude Code CLI settings']
        row = {'id': client, 'name': CLIENTS[client], 'detected': self.integrations.detected().get(client, False),
               'connected': self.owned(client), 'status': 'not_connected', 'issues': [],
               'restartRequired': bool(self.state['restart'].get(client)), 'generationVerified': False,
               'files': [{'role': role, 'path': str(path), 'exists': path.exists()}
                         for role, path in zip(file_roles, paths)],
               'gatewayModelCount': len(gateway.get('models', [])) if not gateway.get('error') else None}
        row['managedSettings'] = ([
            {'name': 'model_provider', 'value': 'gemini_accounts'},
            {'name': 'base_url', 'value': 'http://127.0.0.1:8317/v1'},
            {'name': 'wire_api', 'value': 'responses'},
            {'name': 'requires_openai_auth', 'value': 'false'},
            {'name': 'model_catalog_json', 'value': str(paths[2])},
            {'name': 'Gateway credential', 'value': 'Stored in Codex config; secret is hidden'}] if client == 'codex' else [
            {'name': 'ANTHROPIC_BASE_URL', 'value': 'http://127.0.0.1:8317'},
            {'name': 'ANTHROPIC_AUTH_TOKEN', 'value': 'Stored in settings; secret is hidden'},
            {'name': 'ANTHROPIC_API_KEY', 'value': '(empty; Omni gateway token is used)'},
            {'name': 'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY', 'value': '1'}] if client == 'claude_cli' else [
            {'name': 'inferenceGatewayBaseUrl', 'value': 'http://127.0.0.1:8317'},
            {'name': 'inferenceProvider', 'value': 'gateway'},
            {'name': 'inferenceGatewayAuthScheme', 'value': 'bearer'},
            {'name': 'inferenceCredentialKind', 'value': 'static'},
            {'name': 'inferenceModels', 'value': 'Synced from the live Omni catalog'},
            {'name': 'Gateway credential', 'value': 'Stored in profile; secret is hidden'}])
        if not row['connected']:
            return row
        try:
            _, doc = self.read(client)
        except (OSError, ValueError, TypeError):
            row.update(status='invalid_config', issues=['invalid_config'])
            return row
        if doc is None:
            row.update(status='missing_config', issues=['missing_config'])
            return row
        if not isinstance(doc, dict):
            row.update(status='invalid_config', issues=['invalid_config'])
            return row
        # A deliberate switch to another provider is not a broken Omni connection.
        if client == 'codex' and doc.get('model_provider') not in (None, 'gemini_accounts'):
            row.update(status='other_provider', connected=False)
            return row
        if gateway.get('error'):
            row.update(status=gateway['error'], issues=[gateway['error']])
            return row
        actual, expected = self.expected(client, doc, gateway['key'])
        if not isinstance(actual, dict) or any(actual.get(k) != v for k, v in expected.items()):
            row['issues'].append('transport_settings')
        if client == 'codex' and doc.get('model_provider') != 'gemini_accounts':
            row['issues'].append('provider_selection')
        models = [strip_context_suffix(m) for m in self.models(client, doc)]
        row['configuredModels'] = models
        row['unavailableModels'] = sorted(set(m for m in models if m not in gateway['models']) |
                                          set(self.state.get('retiredDefaults', {}).get(client, [])))
        if row['unavailableModels']:
            row['issues'].append('model_unavailable')
        row['status'] = row['issues'][0] if row['issues'] else 'configured'
        return row

    def restore_routes(self, row, gateway):
        missing = row.get('unavailableModels', [])
        if not missing:
            return False
        known = {self.integrations.claude_desktop_route(m): m for m in gateway['models'] if m.startswith('gemini-')}
        # A stale catalog entry alone is never evidence that a model can be used.
        targets = [known[m] for m in missing if m in known and known[m] in gateway['models']]
        if not targets:
            return False
        self.integrations.configure_desktop_routes(targets, replace=False)
        return True

    def repair_config(self, client, row, gateway):
        path, doc = None, None
        try:
            path, doc = self.read(client)
        except (OSError, ValueError, TypeError):
            pass
        paths = self.integrations.paths()[client]
        path = paths[2] if client == 'claude_desktop' else paths[0]
        if not isinstance(doc, dict):
            # Restore only an exact verified document, never synthesize lost user settings.
            saved = self.state['snapshots'].get(client, {}).get(str(path.resolve()))
            if not saved:
                return False
            atomic_write(path, base64.b64decode(saved))
            return True
        actual, expected = self.expected(client, doc, gateway['key'])
        if client != 'codex':
            updated = copy.deepcopy(doc)
            (updated.setdefault('env', {}) if client == 'claude_cli' else updated).update(expected)
            self.integrations.write_json(path, updated)
            return True
        text = path.read_text('utf-8-sig')
        block = re.search(re.escape(BEGIN) + r'.*?' + re.escape(END), text, re.S)
        if not block:
            # Do not guess the boundaries of an unmanaged TOML table.
            return False
        old = block.group()
        new = old
        for k, value in expected.items():
            pattern = r'(?m)^\s*' + re.escape(k) + r'\s*=.*$'
            replacement = k + ' = ' + json.dumps(value)
            if re.search(pattern, new):
                new = re.sub(pattern, lambda _: replacement, new)
            else:
                new = new.replace(END, replacement + '\n' + END)
        text = text[:block.start()] + new + text[block.end():]
        if doc.get('model_provider') is None:
            text = 'model_provider = "gemini_accounts"\n' + text
        tomllib.loads(text)
        atomic_write(path, text.encode())
        return True

    def maintain(self):
        with self.lock:
            try:
                gateway = self.probe()
            except (OSError, ValueError):
                gateway = {'error': 'gateway_unavailable'}
            catalog = None
            if not gateway.get('error') and self.clock() >= self.catalog_after:
                self.catalog_after = self.clock() + 60
                try:
                    catalog = self.inventory.refresh(gateway['models'], self.controller.model_aliases())
                    self.save()
                except (AccountError, OSError, ValueError, KeyError, TypeError):
                    # A failed or partial catalog must never clear application menus.
                    pass
            rows = []
            for client in CLIENTS:
                try:
                    row = self.inspect(client, gateway)
                    repaired = False
                    if catalog is not None and row['connected'] and row['status'] not in ('other_provider', 'invalid_config', 'missing_config'):
                        _, doc = self.read(client)
                        paths = self.integrations.paths()[client]
                        before = {p: p.read_bytes() if p.exists() else None for p in paths}
                        self.state['beforeCatalogSync'] = {str(p): base64.b64encode(data).decode() if data is not None else None for p, data in before.items()}
                        self.save()
                        try:
                            if self.integrations.sync_model_menu(client, doc, catalog):
                                self.state['restart'][client] = True
                            self.state.get('retiredDefaults', {}).pop(client, None)
                            self.save()
                        except Exception:
                            for p, data in before.items():
                                if data is None:
                                    p.unlink(missing_ok=True)
                                else:
                                    atomic_write(p, data)
                            raise
                        gateway = self.probe()
                        row = self.inspect(client, gateway)
                    if row['connected'] and not gateway.get('error') and self.clock() >= self.retry_after.get(client, 0):
                        repaired = self.restore_routes(row, gateway)
                        if repaired:
                            gateway = self.probe()
                            row = self.inspect(client, gateway)
                        if not gateway.get('error') and any(i in row['issues'] for i in ('transport_settings', 'provider_selection', 'invalid_config', 'missing_config')):
                            paths = self.integrations.paths()[client]
                            before = {p: p.read_bytes() if p.exists() else None for p in paths}
                            # Encrypted last-repair snapshot supports recovery without leaking tokens.
                            self.state['beforeRepair'] = {str(p): base64.b64encode(data).decode() if data is not None else None for p, data in before.items()}
                            self.save()
                            try:
                                changed = self.repair_config(client, row, gateway)
                                verified = self.inspect(client, gateway)
                                if changed and any(i in verified['issues'] for i in ('transport_settings', 'provider_selection', 'invalid_config', 'missing_config')):
                                    raise AccountError('Configuration repair did not pass verification.')
                                if changed:
                                    self.state['restart'][client] = True
                                    self.save()
                                    repaired = True
                            except Exception:
                                for p, data in before.items():
                                    if data is None:
                                        p.unlink(missing_ok=True)
                                    else:
                                        atomic_write(p, data)
                                raise
                        row = self.inspect(client, gateway)
                        row['repaired'] = repaired
                        if not repaired and row.get('status') in ('missing_config', 'invalid_config'):
                            row['connected'] = False
                        if row['issues']:
                            self.retry_after[client] = self.clock() + 300
                    if row['status'] == 'configured':
                        self.remember_good(client)
                    rows.append(row)
                except Exception:
                    self.retry_after[client] = self.clock() + 300
                    rows.append({'id': client, 'name': CLIENTS[client], 'status': 'check_failed', 'connected': False,
                                 'issues': ['check_failed'], 'restartRequired': False, 'generationVerified': False})
            self.last = rows
            return rows

    def connect(self, client):
        if client not in CLIENTS:
            raise AccountError('Unknown application.')
        with self.lock:
            self.integrations.apply([client])
            self.state['restart'][client] = True
            self.save()
            self.retry_after.pop(client, None)
            return self.maintain()

    def restart(self, client, confirmed=False):
        if client != 'all' and client not in CLIENTS or confirmed is not True:
            raise AccountError('Restart requires explicit confirmation.')
        if client == 'all':
            # A catalog sync can mark several desktop clients at once.  A
            # single approved restart action applies the same generation to
            # every connected desktop client; CLI is intentionally excluded
            # because its running terminal cannot be safely replaced.
            targets = [name for name in ('codex', 'claude_desktop')
                       if self.owned(name) and self.state['restart'].get(name)]
            if targets:
                self.integrations.restart_desktop(targets)
                for name in targets:
                    self.state['restart'].pop(name, None)
                self.save()
            return {'restartRequested': bool(targets), 'sessionVerified': bool(targets), 'clients': targets}
        if client == 'claude_cli':
            return {'manual': True, 'message': 'Start a new Claude Code session after saving your current work.'}
        if not self.owned(client):
            raise AccountError('This application is not connected.')
        self.integrations.restart_desktop([client])
        # A process starting does not prove that its profile or login loaded.
        # Retain the pending state until a client-level check confirms recovery.
        return {'restartRequested': True, 'sessionVerified': False}
