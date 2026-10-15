"""Client presets and encrypted, reversible configuration backups."""
import base64
import copy
import json
import os
import re
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path
import yaml

from backend import atomic_write, dpapi, AccountError, storage_root
from model_context import extended_context, client_model_id
from tokenharbor import TokenHarbor, CLIENT_MODEL as TOKENHARBOR_MODEL, DISPLAY_NAME as TOKENHARBOR_LABEL

PRESET_ID = '228c90e2-d605-4ba1-b695-12a49c93a766'
BEGIN = '# BEGIN Gemini Accounts managed provider'
END = '# END Gemini Accounts managed provider'


class Integrations:
    def __init__(self, controller, home=None, local=None):
        self.controller = controller
        self.home = Path(home or Path.home())
        self.local = Path(local or os.environ.get('LOCALAPPDATA', storage_root()))
        self.windows_desktop = os.name == 'nt' or local is not None
        self.backup_path = controller.data_dir / 'client-config-backups.dpapi'
        self.lock = threading.RLock()
        self.available_model_choices = None

    def gemini_model_choices(self):
        if self.available_model_choices is not None:
            return self.available_model_choices
        try:
            if self.controller.key is None:
                config_path = self.controller.proxy_dir / 'config.yaml'
                secret_path = self.controller.data_dir / 'management-key.dpapi'
                if config_path.exists() and secret_path.exists():
                    config = yaml.safe_load(config_path.read_text('utf-8-sig'))
                    self.controller.base = 'http://127.0.0.1:' + str(config['server']['port'])
                    self.controller.key = dpapi(secret_path.read_bytes(), decrypt=True).decode('ascii')
            return self.controller.family_model_choices()['gemini']
        except (AccountError, OSError, KeyError, ValueError, yaml.YAMLError):
            return []

    @staticmethod
    def claude_desktop_route(model):
        """Claude Desktop accepts Anthropic-shaped route IDs, not gemini-* IDs."""
        if not model.startswith('gemini-'):
            raise ValueError('Expected a Gemini model')
        suffix = model.removeprefix('gemini-').replace('.', '-')
        # Preserve existing client route IDs; only their discovered upstreams vary.
        tier = 'haiku' if model == 'gemini-3-flash' else 'sonnet'
        return f'claude-{tier}-4-5-ga-{suffix}'

    def configure_desktop_routes(self, models, replace=True):
        payload = self.controller.request('/oauth-model-alias').get('oauth-model-alias') or {}
        entries = [dict(entry) for entry in payload.get('antigravity', [])]
        desired = {self.claude_desktop_route(model): model for model in models}
        from model_policy import select_model
        fast = select_model(models, cheap=True)
        if fast:
            # Claude Desktop probes this protocol compatibility route.
            desired['claude-haiku-4-5'] = fast
        updated = [entry for entry in entries if entry.get('alias') not in desired and
                   (not replace or not entry.get('alias', '').startswith(
                       ('claude-sonnet-4-5-ga-', 'claude-haiku-4-5-ga-')))]
        from model_names import model_name
        updated += [{'alias': alias, 'name': model, 'fork': True, 'force-mapping': True,
                     'display-name': model_name(model, {})} for alias, model in desired.items()]
        if updated != entries:
            self.controller.request('/oauth-model-alias', 'PATCH', {'provider': 'antigravity', 'aliases': updated})

    def reconcile_desktop_routes(self):
        """Restore gateway routes for a previously approved Claude Desktop preset."""
        if not self.legacy_desktop_preset():
            return False
        preset_path = self.paths()['claude_desktop'][2]
        if str(preset_path.resolve()) not in self.backups():
            return False
        menu_changed = TokenHarbor(self.controller, self).sync_desktop_model()
        preset = self.read_json(preset_path)
        routes = {entry.get('name') for entry in preset.get('inferenceModels', [])
                  if isinstance(entry, dict) and isinstance(entry.get('name'), str)
                  and re.fullmatch(r'claude-(?:sonnet|haiku)-4-5-ga-[a-z0-9-]+', entry['name'])}
        if not routes:
            return menu_changed
        from model_policy import select_model
        models = {m for m in self.connection_models() if m.startswith('gemini-')}
        known = {self.claude_desktop_route(model): model for model in models}
        fast = select_model(models, cheap=True)
        if fast:
            routes.add('claude-haiku-4-5')
            known['claude-haiku-4-5'] = fast
        unresolved = routes - known.keys()
        if unresolved:
            raise AccountError('Connected Claude models are missing from the gateway catalog. Reconnect Claude Desktop from the application.')
        live = self.controller.request('/oauth-model-alias').get('oauth-model-alias') or {}
        aliases = {entry.get('alias'): entry.get('name') for entry in live.get('antigravity', [])}
        if all(aliases.get(route) == known[route] for route in routes):
            return menu_changed
        self.configure_desktop_routes([known[route] for route in sorted(routes)], replace=False)
        return True

    def detected(self):
        return {
            'claude_desktop': self.windows_desktop and any((self.local / p).exists() for p in ('AnthropicClaude', 'Claude-3p', 'Claude')),
            'claude_cli': bool(shutil.which('claude') or (self.home / '.claude').exists()),
            'codex': bool(shutil.which('codex') or (self.home / '.codex').exists()),
        }

    def paths(self):
        library = self.local / 'Claude-3p' / 'configLibrary'
        preset_id = self.legacy_desktop_preset() or PRESET_ID
        return {
            'claude_cli': [self.home / '.claude' / 'settings.json'],
            'codex': [self.home / '.codex' / 'config.toml', self.home / '.codex' / 'gemini-accounts.config.toml',
                      self.home / '.codex' / 'gemini-accounts-models.json'],
            'claude_desktop': [self.local / 'Claude-3p' / 'claude_desktop_config.json',
                               library / '_meta.json', library / (preset_id + '.json')],
        }

    def legacy_desktop_preset(self):
        """Recognize approved Omni profiles and the original Gemini localhost preset."""
        library = self.local / 'Claude-3p' / 'configLibrary'
        try:
            preset_id = self.read_json(library / '_meta.json').get('appliedId', '')
            if not re.fullmatch(r'[a-fA-F0-9-]{36}', preset_id):
                return None
            path = library / (preset_id + '.json')
            preset = self.read_json(path)
            models = preset.get('inferenceModels', [])
            managed = (preset.get('deploymentDisplayName') in ('Omni', 'Gemini Accounts') and
                       str(path.resolve()) in self.backups())
            if (preset.get('inferenceGatewayBaseUrl', '').rstrip('/') == 'http://127.0.0.1:8317'
                    and (managed or preset.get('inferenceProvider') == 'gateway'
                         or any(m.get('labelOverride', '').startswith('Gemini') for m in models))):
                return preset_id
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def refresh_desktop_model_labels(self):
        """Refresh display labels only; preserve model IDs, credentials and defaults."""
        if not self.legacy_desktop_preset():
            return False
        path = self.paths()['claude_desktop'][2]
        preset = self.read_json(path)
        aliases = self.controller.model_aliases()
        from model_names import model_name
        changed = False
        for entry in preset.get('inferenceModels', []):
            if entry.get('name') == TOKENHARBOR_MODEL:
                continue
            model = aliases.get(entry['name'], entry['name'])
            family = 'Gemini' if model.startswith('gemini-') else 'Claude' if model.startswith('claude-') else ''
            if not family:
                continue
            label = family + ' · ' + model_name(model, {})
            if entry.get('labelOverride') != label:
                entry['labelOverride'] = label
                changed = True
            for flag in ('supports1m', 'prefer1m'):
                if entry.get(flag, False) != extended_context(model):
                    entry[flag] = extended_context(model)
                    changed = True
        if changed:
            with self.lock:
                self.remember([path])
                self.write_json(path, preset)
        return changed

    def repair_desktop_fast_slot(self):
        """Explicit repair of our preset, preserving credentials and all other slots."""
        if not self.legacy_desktop_preset():
            return False
        path = self.paths()['claude_desktop'][2]
        preset = self.read_json(path)
        return self.sync_model_menu('claude_desktop', preset, self.connection_models())

    def backups(self):
        if not self.backup_path.exists():
            return {}
        try:
            return json.loads(dpapi(self.backup_path.read_bytes(), decrypt=True))
        except (OSError, ValueError) as error:
            raise AccountError('Could not unlock the configuration backup.') from error

    def remember(self, paths):
        saved = self.backups()
        for path in paths:
            key = str(path.resolve())
            if key not in saved:
                saved[key] = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
        atomic_write(self.backup_path, dpapi(json.dumps(saved).encode()))

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text('utf-8-sig')) if path.exists() else {}

    @staticmethod
    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())

    def apply(self, clients):
        clients = list(dict.fromkeys(clients))
        if not clients or any(client not in self.paths() for client in clients):
            raise AccountError('Choose applications to connect.')
        if 'claude_desktop' in clients and not self.windows_desktop:
            raise AccountError('Automatic Claude Desktop setup is available on Windows. Use Claude Code CLI on this platform.')
        key = (self.controller.proxy_dir / 'client-key.txt').read_text('utf-8-sig').strip()
        if not key:
            raise AccountError('Local connection key not found.')
        # Validate existing documents before making any changes.
        paths = [p for client in clients for p in self.paths()[client]]
        for path in paths:
            if path.exists():
                if path.suffix == '.json':
                    self.read_json(path)
                else:
                    tomllib.loads(path.read_text('utf-8-sig'))
        with self.lock:
            before = {p: p.read_bytes() if p.exists() else None for p in paths}
            self.remember(paths)
            try:
                for client in clients:
                    getattr(self, 'configure_' + client)(key)
                self.clear_shadowed_routes()
            except Exception:
                for path, data in before.items():
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, data)
                raise
        return clients

    def clear_shadowed_routes(self):
        """Old model-picker aliases must not hijack explicit client model choices."""
        try:
            choices = set(self.controller.family_model_choices()['claude'])
        except (AccountError, OSError, KeyError, ValueError):
            return
        choices.discard('claude-sonnet-4-5')  # Gateway's Gemini default slot.
        if not choices:
            return
        payload = self.controller.request('/oauth-model-alias').get('oauth-model-alias') or {}
        entries = payload.get('antigravity', [])
        direct = [entry for entry in entries if entry.get('alias') not in choices]
        if len(direct) != len(entries):
            self.controller.request('/oauth-model-alias', 'PATCH',
                                    {'provider': 'antigravity', 'aliases': direct})

    def connection_models(self):
        """Read the serving catalog, including OAuth and API-key providers."""
        import urllib.request
        from model_policy import canonical_models
        key = (self.controller.proxy_dir / 'client-key.txt').read_text('utf-8-sig').strip()
        request = urllib.request.Request('http://127.0.0.1:8317/v1/models', headers={'Authorization': 'Bearer ' + key})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            rows = json.load(response)['data']
        if not isinstance(rows, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in rows):
            raise AccountError('The gateway model catalog is invalid.')
        return canonical_models({m['id'] for m in rows}, self.controller.model_aliases())

    def configure_claude_cli(self, key):
        path = self.paths()['claude_cli'][0]
        settings = self.read_json(path)
        from model_policy import select_model
        models = self.connection_models()
        if not models:
            raise AccountError('No models are currently available from the gateway.')
        # Claude Code can select Anthropic-shaped aliases directly. Keep those
        # routes in the gateway in sync with the live Gemini catalog as well;
        # configuring only Claude's environment leaves a stale custom model
        # visible to the client but unknown to the provider.
        self.configure_desktop_routes(sorted(m for m in models if m.startswith('gemini-')))
        env = settings.setdefault('env', {})
        env.update({'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317',
                    'ANTHROPIC_AUTH_TOKEN': key, 'ANTHROPIC_API_KEY': '',
                    'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': '1',
                    'CLAUDE_CODE_AUTO_MODE_SERVER': '0',
                    'API_TIMEOUT_MS': '604800000', 'CLAUDE_ENABLE_STREAM_WATCHDOG': '0'})
        # availableModels is a restriction shared with Desktop's Code sessions,
        # not a discovery catalog. Canonical IDs would disable desktop routes.
        settings.pop('availableModels', None)
        for field in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL'):
            from model_context import strip_context_suffix
            preferred = strip_context_suffix(env.get(field, ''))
            env[field] = select_model(models, preferred=preferred, cheap='HAIKU' in field) or select_model(models)
        self.write_json(path, settings)

    def provider_toml(self, key):
        return '\n'.join([
            '[model_providers.gemini_accounts]', 'name = "Omni"',
            'base_url = "http://127.0.0.1:8317/v1"', 'wire_api = "responses"',
            'experimental_bearer_token = ' + json.dumps(key),
            # Omni authenticates with its loopback bearer, independently of
            # the optional ChatGPT desktop identity. Never force a new login.
            'requires_openai_auth = false',
            'stream_idle_timeout_ms = 604800000', 'request_max_retries = 2',
            'supports_websockets = false', '',
        ])

    def configure_codex(self, key):
        path, profile, catalog_path = self.paths()['codex']
        text = path.read_text('utf-8-sig') if path.exists() else ''
        text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\s*', '', text, flags=re.S)
        config = tomllib.loads(text)
        if 'gemini_accounts' in config.get('model_providers', {}):
            raise AccountError('The gemini_accounts provider name is already used by another configuration.')
        split = re.search(r'^\s*\[', text, re.M)
        root, tables = (text[:split.start()], text[split.start():]) if split else (text, '')
        previous_catalog = config.get('model_catalog_json')
        root = re.sub(r'^\s*(model|model_provider|model_catalog_json)\s*=.*\n?', '', root, flags=re.M)
        from model_policy import select_model
        models = self.connection_models()
        model = select_model(models, preferred=config.get('model'))
        if not model:
            raise AccountError('No models are currently available from the gateway.')
        defaults = 'model = ' + json.dumps(model) + '\nmodel_provider = "gemini_accounts"\n'
        if self.write_codex_catalog(catalog_path, previous_catalog, live_models=models):
            defaults += 'model_catalog_json = ' + json.dumps(str(catalog_path.resolve())) + '\n'
        updated = defaults + root + '\n' + tables.rstrip() + '\n\n' + BEGIN + '\n' + self.provider_toml(key) + END + '\n'
        tomllib.loads(updated)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, updated.encode())
        atomic_write(profile, (defaults + '\n' + self.provider_toml(key)).encode())

    def write_codex_catalog(self, target, previous_catalog=None, live_models=None):
        """Extend Codex's local catalog while keeping its existing model rows."""
        cache = self.home / '.codex' / 'models_cache.json'
        source = target if live_models is not None and target.exists() else Path(previous_catalog) if previous_catalog and Path(previous_catalog) != target else cache
        if not source.exists() and target.exists():
            source = target
        if not source.exists():
            return False
        catalog = self.read_json(source)
        models = catalog.get('models')
        if not isinstance(models, list):
            return False
        if not models:
            # A confirmed empty catalog can later become populated again.
            seed = self.read_json(cache).get('models', []) if cache.exists() else []
            seed = seed or catalog.get('_omni_template', [])
            if not seed:
                return False
            models.append(copy.deepcopy(seed[0]))
        if live_models is None:
            try:
                available = self.controller.family_model_choices()
                choices = available['gemini'] + available['claude']
            except (AccountError, OSError, KeyError, ValueError):
                choices = self.gemini_model_choices()
            try:
                choices += self.controller.chatgpt_model_choices()
            except (AccountError, OSError, KeyError, ValueError):
                pass
        if live_models is not None:
            choices = sorted(live_models)
            # This file is Omni's provider menu, not Codex's native cache.
            template = copy.deepcopy(models[0])
            catalog.setdefault('_omni_template', [copy.deepcopy(template)])
            models[:] = [m for m in models if m.get('slug') in live_models]
        else:
            template = models[0]
        from model_names import model_name, reasoning_level
        from model_policy import is_disabled_model
        cache_models = {m['slug']: copy.deepcopy(m)
                        for m in self.read_json(cache).get('models', [])
                        if isinstance(m, dict) and isinstance(m.get('slug'), str)}
        for slug in list(cache_models.keys()):
            if is_disabled_model(slug):
                cache_models.pop(slug, None)

        for i, m in enumerate(models):
            slug = m.get('slug')
            if slug in cache_models:
                models[i] = copy.deepcopy(cache_models[slug])

        existing = {entry.get('slug') for entry in models}
        for model in choices:
            if model in existing or is_disabled_model(model):
                continue
            if model in cache_models:
                entry = copy.deepcopy(cache_models[model])
            else:
                entry = copy.deepcopy(template)
                family = 'Gemini ' if model.startswith('gemini-') else 'ChatGPT ' if model.startswith('gpt-') else 'Claude '
                entry.update(slug=model, display_name=family + model_name(model, {}),
                             description='Antigravity via Omni', priority=50,
                             model_messages={}, base_instructions='You are a helpful coding assistant.',
                             context_window=1048576 if model.startswith('gemini-') else 200000,
                             max_context_window=1048576 if model.startswith('gemini-') else 200000,
                             additional_speed_tiers=[], service_tiers=[], availability_nux=None,
                             upgrade=None)
                if model.startswith('gpt-'):
                    entry['default_reasoning_level'] = template.get('default_reasoning_level', 'medium')
                    entry['supported_reasoning_levels'] = copy.deepcopy(template.get('supported_reasoning_levels', []))
                else:
                    effort = reasoning_level(model)
                    entry['default_reasoning_level'] = effort
                    entry['supported_reasoning_levels'] = [{'effort': effort, 'description': effort.title() + ' reasoning'}]
            models.append(entry)
        models.sort(key=lambda m: m.get('priority', 50))
        if not target.exists() or self.read_json(target) != catalog:
            self.write_json(target, catalog)
        return True

    def sync_model_menu(self, client, doc, models):
        """Reconcile menus and retired defaults against the confirmed live catalog."""
        from model_names import model_name
        from model_policy import select_model, text_models
        from model_context import strip_context_suffix
        models = text_models(models)
        if client == 'codex':
            path, profile, target = self.paths()[client]
            before = {p: p.read_bytes() if p.exists() else None for p in (path, profile, target)}
            if not self.write_codex_catalog(target, doc.get('model_catalog_json'), live_models=models):
                raise AccountError('Codex model catalog template is not available yet.')
            for p in (path, profile):
                if not p.exists():
                    continue
                text = p.read_text('utf-8-sig')
                config = tomllib.loads(text)
                if config.get('model_provider') != 'gemini_accounts':
                    continue
                split = re.search(r'^\s*\[', text, re.M)
                root, tables = (text[:split.start()], text[split.start():]) if split else (text, '')
                selected = config.get('model')
                replacement = select_model(models, family=(selected or '').split('-')[0]) or select_model(models)
                if selected not in models and replacement:
                    root = re.sub(r'^\s*model\s*=.*\n?', '', root, flags=re.M)
                    root = 'model = ' + json.dumps(replacement) + '\n' + root
                root = re.sub(r'^\s*model_catalog_json\s*=.*\n?', '', root, flags=re.M)
                text = 'model_catalog_json = ' + json.dumps(str(target.resolve())) + '\n' + root + tables
                tomllib.loads(text)
                if p.read_text('utf-8-sig') != text:
                    atomic_write(p, text.encode())
            return any((p.read_bytes() if p.exists() else None) != data for p, data in before.items())
        path = self.paths()[client][2 if client == 'claude_desktop' else 0]
        updated = copy.deepcopy(doc)
        if client == 'claude_cli':
            env = updated.setdefault('env', {})
            env['CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY'] = '1'
            # Keep the gateway's Anthropic-shaped routes in lockstep with the
            # live Gemini catalog. Claude Code may retain a custom route in
            # its model picker even after the alias was removed upstream.
            self.configure_desktop_routes(sorted(m for m in models if m.startswith('gemini-')))
            updated.pop('availableModels', None)
            for key in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL'):
                old = strip_context_suffix(env.get(key, ''))
                if old in models:
                    continue
                family = 'gemini' if old.startswith('gemini-') or '-ga-' in old else 'claude' if old.startswith('claude-') else None
                candidates = {m for m in models if not family or m.startswith(family + '-')}
                replacement = select_model(candidates, cheap='HAIKU' in key) or select_model(candidates) or select_model(models)
                if replacement:
                    env[key] = replacement
                else:
                    env.pop(key, None)
        else:
            gemini = sorted(m for m in models if m.startswith('gemini-') and m != 'gemini-selected')
            self.configure_desktop_routes(gemini)
            # Claude Desktop validates every inferenceModels entry as an
            # Anthropic route.  The shared gateway catalog also contains
            # Codex/OpenAI and internal routes; those belong in Codex or the
            # gateway, never in Claude's picker.  Keep only Gemini routes
            # (translated to Anthropic-shaped aliases) and real claude-* IDs.
            claude_models = {m for m in models if m.startswith(('gemini-', 'claude-'))}
            desired = {self.claude_desktop_route(m) if m in gemini else m: m
                       for m in claude_models}
            existing = {m['name']: m for m in doc.get('inferenceModels', []) if isinstance(m, dict) and 'name' in m}
            updated['inferenceModels'] = [existing.get(route) or {
                'name': route, 'labelOverride': model_name(model, {}),
                'anthropicFamilyTier': 'opus' if 'opus' in model else 'haiku' if 'flash' in model or 'haiku' in model else 'sonnet',
                'isFamilyDefault': False, 'supports1m': extended_context(model), 'prefer1m': extended_context(model)
            } for route, model in sorted(desired.items())]
            for tier in ('sonnet', 'haiku', 'opus'):
                rows = [m for m in updated['inferenceModels'] if m.get('anthropicFamilyTier') == tier]
                if rows and not any(m.get('isFamilyDefault') for m in rows):
                    selected = select_model({desired[m['name']] for m in rows}, cheap=tier=='haiku')
                    selected = selected or select_model({desired[m['name']] for m in rows})
                    next(m for m in rows if desired[m['name']] == selected)['isFamilyDefault'] = True
        if updated == doc:
            return False
        self.write_json(path, updated)
        return True

    def configure_claude_desktop(self, key):
        desktop, meta_path, preset = self.paths()['claude_desktop']
        models = self.connection_models()
        if not models:
            raise AccountError('No models are currently available from the gateway.')
        doc = self.read_json(preset)
        doc.update({'deploymentDisplayName': 'Omni', 'inferenceCredentialKind': 'static',
                    'modelDiscoveryEnabled': False, 'inferenceGatewayAuthScheme': 'bearer',
                    'inferenceProvider': 'gateway', 'inferenceGatewayApiKey': key,
                    'inferenceGatewayBaseUrl': 'http://127.0.0.1:8317'})
        self.write_json(preset, doc)
        self.sync_model_menu('claude_desktop', doc, models)
        meta = self.read_json(meta_path)
        entries = meta.setdefault('entries', [])
        preset_id = preset.stem
        if not any(e.get('id') == preset_id for e in entries):
            entries.append({'id': preset_id, 'name': 'Omni'})
        meta['appliedId'] = preset_id
        self.write_json(meta_path, meta)
        settings = self.read_json(desktop)
        settings['deploymentMode'] = '3p'
        self.write_json(desktop, settings)

    def restore(self):
        with self.lock:
            saved = self.backups()
            allowed = {str(p.resolve()) for group in self.paths().values() for p in group}
            if any(path not in allowed for path in saved):
                raise AccountError('The backup contains an unexpected path. Restoration cancelled.')
            if (self.controller.proxy_dir / 'config.yaml').exists():
                TokenHarbor(self.controller, self).disconnect(update_desktop=False)
            for name, data in saved.items():
                path = Path(name)
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(path, base64.b64decode(data))
            self.backup_path.unlink(missing_ok=True)
            return len(saved)

    def restore_clients(self, clients):
        """Restore the exact pre-Omni files for explicitly selected clients."""
        clients = list(dict.fromkeys(clients))
        if not clients or any(client not in self.paths() for client in clients):
            raise AccountError('Choose applications to restore.')
        with self.lock:
            saved = self.backups()
            allowed = {str(p.resolve()) for group in self.paths().values() for p in group}
            if any(path not in allowed for path in saved):
                raise AccountError('The backup contains an unexpected path. Restoration cancelled.')
            selected = {str(p.resolve()) for client in clients for p in self.paths()[client]}
            restored = 0
            for name in list(saved):
                if name not in selected:
                    continue
                path = Path(name)
                data = saved.pop(name)
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(path, base64.b64decode(data))
                restored += 1
            if saved:
                atomic_write(self.backup_path, dpapi(json.dumps(saved).encode()))
            else:
                self.backup_path.unlink(missing_ok=True)
            return restored

    @staticmethod
    def restart_desktop(clients):
        """Restart an identified client with its original launch arguments and graceful close."""
        if os.name != 'nt':
            raise AccountError('Restart desktop clients manually on this platform.')
        env = os.environ.copy()
        env['GEMINI_ACCOUNTS_RESTART_CLIENTS'] = json.dumps(clients)
        script = r'''
$ErrorActionPreference = 'Stop'
$targets = ConvertFrom-Json $env:GEMINI_ACCOUNTS_RESTART_CLIENTS
function Get-Descendants($rootId, $all) {
    $found = @()
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue([int]$rootId)
    while ($queue.Count -gt 0) {
        $parentId = $queue.Dequeue()
        foreach ($child in @($all | Where-Object { $_.ParentProcessId -eq $parentId })) {
            $found += $child
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    return $found
}
$processes = @(Get-CimInstance Win32_Process)
foreach ($target in $targets) {
    $candidates = @($processes | Where-Object {
        if ($target -eq 'claude_desktop') {
            $_.Name -eq 'claude.exe' -and $_.ExecutablePath -like '*\AnthropicClaude\*'
        } elseif ($target -eq 'codex') {
            $_.Name -in @('ChatGPT.exe','Codex.exe') -and ($_.ExecutablePath -like '*\OpenAI.Codex_*\app\*' -or $_.ExecutablePath -like '*\OpenAI\Codex\app\*')
        }
    } | Where-Object { $_.CommandLine -notmatch '(?:^|\s)--type=' })
    if ($candidates.Count -ne 1) { throw "Cannot identify one running main process for $target" }
    $main = $candidates[0]
    $exe = $main.ExecutablePath
    # Preserve the running executable and profile switches; never select a Store entry.
    $command = $main.CommandLine.Trim()
    if ($command.StartsWith('"' + $exe + '"')) {
        $arguments = $command.Substring($exe.Length + 2).Trim()
    } elseif ($command.StartsWith($exe, [StringComparison]::OrdinalIgnoreCase)) {
        $arguments = $command.Substring($exe.Length).Trim()
    } else { throw "Cannot preserve launch arguments for $target" }
    $launch = @{FilePath=$exe; WorkingDirectory=(Split-Path -LiteralPath $exe); PassThru=$true}
    if ($arguments) { $launch.ArgumentList = $arguments }
    # Capture the complete process tree before closing.  Both clients can
    # keep their main window alive in the tray; a graceful close alone is not
    # enough to apply a changed gateway profile.
    $children = @(Get-Descendants $main.ProcessId $processes | Where-Object {
        $_.ExecutablePath -eq $exe
    })
    $process = Get-Process -Id $main.ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { throw "The identified process disappeared before restart: $target" }
    $closed = $process.CloseMainWindow()
    $exited = $process.WaitForExit($(if ($closed) { 15000 } else { 1000 }))
    if (-not $exited) {
        # Close-to-tray is common for Electron clients.  Stop only this
        # identified process tree, never another app or a Claude Code CLI.
        foreach ($child in @($children | Sort-Object @{Expression={($_.ParentProcessId -eq $main.ProcessId)}}, ProcessId -Descending)) {
            $live = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ProcessId)"
            if ($live -and $live.CreationDate -eq $child.CreationDate -and $live.ExecutablePath -eq $exe) {
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        $current = Get-Process -Id $main.ProcessId -ErrorAction SilentlyContinue
        if ($current -and $current.StartTime -eq $process.StartTime) {
            Stop-Process -InputObject $current -Force -ErrorAction SilentlyContinue
            $current.WaitForExit(5000) | Out-Null
        }
        if (Get-Process -Id $main.ProcessId -ErrorAction SilentlyContinue) {
            throw "Application did not exit after its identified process tree was stopped: $target"
        }
    }
    $started = Start-Process @launch
    Start-Sleep -Milliseconds 1000
    $live = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $exe -and $_.CommandLine -notmatch '(?:^|\s)--type='
    })
    if ($started.HasExited -and $live.Count -eq 0) { throw "Application launch could not be verified: $target" }
    # A single-instance Electron launcher can hand off to an existing child
    # and exit immediately; refresh the snapshot before the next client.
    $processes = @(Get-CimInstance Win32_Process)
}
'''
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=30 * max(1, len(clients)))
