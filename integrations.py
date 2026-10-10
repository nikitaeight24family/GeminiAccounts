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
        """Recognize our original localhost preset without adopting unrelated gateways."""
        library = self.local / 'Claude-3p' / 'configLibrary'
        try:
            preset_id = self.read_json(library / '_meta.json').get('appliedId', '')
            if not re.fullmatch(r'[a-fA-F0-9-]{36}', preset_id):
                return None
            preset = self.read_json(library / (preset_id + '.json'))
            models = preset.get('inferenceModels', [])
            if (preset.get('inferenceGatewayBaseUrl', '').rstrip('/') == 'http://127.0.0.1:8317'
                    and any(m.get('labelOverride', '').startswith('Gemini') for m in models)):
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
        models = preset.setdefault('inferenceModels', [])
        flash = {'name': 'gemini-3-flash', 'labelOverride': 'Gemini · 3 Flash',
                 'anthropicFamilyTier': 'haiku', 'isFamilyDefault': True,
                 'supports1m': True, 'prefer1m': True}
        indices = [i for i, m in enumerate(models) if m.get('anthropicFamilyTier') == 'haiku'
                   or m.get('name') in ('claude-haiku-4-5', 'gemini-3-flash')]
        if len(indices) == 1 and models[indices[0]] == flash:
            return False
        models[:] = [m for i, m in enumerate(models) if i not in indices]
        models.insert(indices[0] if indices else len(models), flash)
        with self.lock:
            self.remember([path])
            self.write_json(path, preset)
        return True

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
            except Exception:
                for path, data in before.items():
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, data)
                raise
        return clients

    def configure_claude_cli(self, key):
        path = self.paths()['claude_cli'][0]
        settings = self.read_json(path)
        families = self.controller.selected_family_models()
        gemini = client_model_id('claude-sonnet-4-5', families['gemini'])
        claude = client_model_id('claude-selected', families['claude'])
        settings.setdefault('env', {}).update({
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317',
            'ANTHROPIC_AUTH_TOKEN': key, 'ANTHROPIC_API_KEY': '',
            'ANTHROPIC_MODEL': gemini,
            'ANTHROPIC_DEFAULT_SONNET_MODEL': gemini,
            'ANTHROPIC_DEFAULT_HAIKU_MODEL': client_model_id('gemini-3-flash', 'gemini-3-flash'),
            'ANTHROPIC_DEFAULT_OPUS_MODEL': claude if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking',
            'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY': '1',
            'API_TIMEOUT_MS': '604800000', 'CLAUDE_ENABLE_STREAM_WATCHDOG': '0',
        })
        self.write_json(path, settings)

    def provider_toml(self, key):
        return '\n'.join([
            '[model_providers.gemini_accounts]', 'name = "Gemini Accounts"',
            'base_url = "http://127.0.0.1:8317/v1"', 'wire_api = "responses"',
            'experimental_bearer_token = ' + json.dumps(key),
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
        model = 'gemini-selected' if self.controller.preferences.get('gemini-model') else self.controller.preferences.get('pro-model') or self.controller.model_aliases().get('claude-sonnet-4-5', 'gemini-3.1-pro-low')
        defaults = 'model = ' + json.dumps(model) + '\nmodel_provider = "gemini_accounts"\n'
        if self.write_codex_catalog(catalog_path, previous_catalog):
            defaults += 'model_catalog_json = ' + json.dumps(str(catalog_path.resolve())) + '\n'
        updated = defaults + root + '\n' + tables.rstrip() + '\n\n' + BEGIN + '\n' + self.provider_toml(key) + END + '\n'
        tomllib.loads(updated)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, updated.encode())
        atomic_write(profile, (defaults + '\n' + self.provider_toml(key)).encode())

    def write_codex_catalog(self, target, previous_catalog=None):
        """Extend Codex's local catalog while keeping its existing model rows."""
        cache = self.home / '.codex' / 'models_cache.json'
        source = Path(previous_catalog) if previous_catalog and Path(previous_catalog) != target else cache
        if not source.exists() and target.exists():
            source = target
        if not source.exists():
            return False
        catalog = self.read_json(source)
        models = catalog.get('models')
        if not isinstance(models, list) or not models:
            return False
        choices = self.gemini_model_choices()
        from model_names import model_name, reasoning_level
        existing = {entry.get('slug') for entry in models}
        template = models[0]
        for model in choices:
            if model in existing:
                continue
            entry = copy.deepcopy(template)
            entry.update(slug=model, display_name='Gemini ' + model_name(model, {}),
                         description='Antigravity via Gemini Accounts', priority=50,
                         model_messages={}, base_instructions='You are a helpful coding assistant.',
                         context_window=1048576, max_context_window=1048576,
                         additional_speed_tiers=[], service_tiers=[], availability_nux=None,
                         upgrade=None)
            effort = reasoning_level(model)
            entry['default_reasoning_level'] = effort
            entry['supported_reasoning_levels'] = [{'effort': effort, 'description': effort.title() + ' reasoning'}]
            models.append(entry)
        self.write_json(target, catalog)
        return True

    def configure_claude_desktop(self, key):
        desktop, meta_path, preset = self.paths()['claude_desktop']
        family_models = self.controller.selected_family_models()
        from model_names import model_name
        models = [('claude-sonnet-4-5', 'Gemini · ' + model_name(family_models['gemini'], {}), 'sonnet', True),
                  ('claude-selected' if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking',
                   'Claude · ' + model_name(family_models['claude'] if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking', {}), 'opus', True),
                  ('gemini-3-flash', 'Gemini · 3 Flash', 'haiku', True)]
        choices = self.gemini_model_choices()
        seen = {item[0] for item in models}
        for model in choices:
            if (model not in seen and model != family_models['gemini'] and
                    ('-flash-high' in model or '-flash-medium' in model or '-flash-low' in model or
                     model in ('gemini-3-flash-agent', 'gemini-3.5-flash-extra-low'))):
                models.append((model, 'Gemini · ' + model_name(model, {}), 'sonnet', False))
                seen.add(model)
        self.write_json(preset, {
            'deploymentDisplayName': 'Gemini Accounts', 'inferenceCredentialKind': 'static',
            'modelDiscoveryEnabled': False, 'inferenceGatewayAuthScheme': 'bearer',
            'inferenceProvider': 'gateway', 'inferenceGatewayApiKey': key,
            'inferenceGatewayBaseUrl': 'http://127.0.0.1:8317',
            'claudeAiImport': {'bannerBehavior': 'detect', 'exportEnabled': True, 'enabled': True},
            'inferenceModels': [
                {'name': name, 'labelOverride': label, 'anthropicFamilyTier': tier, 'isFamilyDefault': default,
                 'supports1m': extended_context(name if name not in ('claude-sonnet-4-5', 'claude-selected') else
                     family_models['gemini'] if name == 'claude-sonnet-4-5' else family_models['claude']),
                 'prefer1m': extended_context(name if name not in ('claude-sonnet-4-5', 'claude-selected') else
                     family_models['gemini'] if name == 'claude-sonnet-4-5' else family_models['claude'])}
                for name, label, tier, default in models],
        })
        meta = self.read_json(meta_path)
        entries = meta.setdefault('entries', [])
        preset_id = preset.stem
        if not any(e.get('id') == preset_id for e in entries):
            entries.append({'id': preset_id, 'name': 'Gemini Accounts'})
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
            for name, data in saved.items():
                path = Path(name)
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(path, base64.b64decode(data))
            self.backup_path.unlink(missing_ok=True)
            return len(saved)

    @staticmethod
    def restart_desktop(clients):
        """Called only after separate, explicit consent to interrupt running clients."""
        if os.name != 'nt':
            raise AccountError('Restart desktop clients manually on this platform.')
        env = os.environ.copy()
        env['GEMINI_ACCOUNTS_RESTART_CLIENTS'] = json.dumps(clients)
        script = r'''
$targets = ConvertFrom-Json $env:GEMINI_ACCOUNTS_RESTART_CLIENTS
$processes = Get-CimInstance Win32_Process
if ('claude_desktop' -in $targets) {
    $matches = @($processes | Where-Object {$_.Name -eq 'claude.exe' -and $_.ExecutablePath -like '*\AnthropicClaude\*'})
    $exe = $matches | Select-Object -First 1 -ExpandProperty ExecutablePath
    $matches | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
    if ($exe) {Start-Sleep -Milliseconds 500; Start-Process -FilePath $exe}
}
if ('codex' -in $targets) {
    $matches = @($processes | Where-Object {$_.Name -in @('ChatGPT.exe','Codex.exe') -and ($_.ExecutablePath -like '*\OpenAI.Codex_*\app\*' -or $_.ExecutablePath -like '*\OpenAI\Codex\app\*')})
    if ($matches.Count) {
        $exe = $matches | Select-Object -First 1 -ExpandProperty ExecutablePath
        $matches | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
        Start-Sleep -Milliseconds 500
        $app = Get-StartApps | Where-Object {$_.AppID -like 'OpenAI.Codex*'} | Select-Object -First 1
        if ($app) {Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\' + $app.AppID)} else {Start-Process -FilePath $exe}
    }
}
'''
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=30)
