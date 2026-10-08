"""Client presets and encrypted, reversible configuration backups."""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path

from backend import atomic_write, dpapi, AccountError, storage_root

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
            'codex': [self.home / '.codex' / 'config.toml', self.home / '.codex' / 'gemini-accounts.config.toml'],
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
        if changed:
            with self.lock:
                self.remember([path])
                self.write_json(path, preset)
        return changed

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
        settings.setdefault('env', {}).update({
            'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317',
            'ANTHROPIC_AUTH_TOKEN': key, 'ANTHROPIC_API_KEY': '',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-5',
            'ANTHROPIC_DEFAULT_SONNET_MODEL': 'claude-sonnet-4-5',
            'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'claude-selected' if self.controller.preferences.get('claude-model') else 'claude-haiku-4-5',
            'ANTHROPIC_DEFAULT_OPUS_MODEL': 'claude-selected' if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking',
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
        path, profile = self.paths()['codex']
        text = path.read_text('utf-8-sig') if path.exists() else ''
        text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\s*', '', text, flags=re.S)
        config = tomllib.loads(text)
        if 'gemini_accounts' in config.get('model_providers', {}):
            raise AccountError('The gemini_accounts provider name is already used by another configuration.')
        split = re.search(r'^\s*\[', text, re.M)
        root, tables = (text[:split.start()], text[split.start():]) if split else (text, '')
        root = re.sub(r'^\s*(model|model_provider)\s*=.*\n?', '', root, flags=re.M)
        model = 'gemini-selected' if self.controller.preferences.get('gemini-model') else self.controller.preferences.get('pro-model') or self.controller.model_aliases().get('claude-sonnet-4-5', 'gemini-3.1-pro-low')
        defaults = 'model = ' + json.dumps(model) + '\nmodel_provider = "gemini_accounts"\n'
        updated = defaults + root + '\n' + tables.rstrip() + '\n\n' + BEGIN + '\n' + self.provider_toml(key) + END + '\n'
        tomllib.loads(updated)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, updated.encode())
        atomic_write(profile, (defaults + '\n' + self.provider_toml(key)).encode())

    def configure_claude_desktop(self, key):
        desktop, meta_path, preset = self.paths()['claude_desktop']
        family_models = self.controller.selected_family_models()
        from model_names import model_name
        models = [('claude-sonnet-4-5', 'Gemini · ' + model_name(family_models['gemini'], {}), 'sonnet', True),
                  ('claude-selected' if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking',
                   'Claude · ' + model_name(family_models['claude'] if self.controller.preferences.get('claude-model') else 'claude-opus-4-6-thinking', {}), 'opus', True)]
        self.write_json(preset, {
            'deploymentDisplayName': 'Gemini Accounts', 'inferenceCredentialKind': 'static',
            'modelDiscoveryEnabled': False, 'inferenceGatewayAuthScheme': 'bearer',
            'inferenceProvider': 'gateway', 'inferenceGatewayApiKey': key,
            'inferenceGatewayBaseUrl': 'http://127.0.0.1:8317',
            'claudeAiImport': {'bannerBehavior': 'detect', 'exportEnabled': True, 'enabled': True},
            'inferenceModels': [
                {'name': name, 'labelOverride': label, 'anthropicFamilyTier': tier, 'isFamilyDefault': default}
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
