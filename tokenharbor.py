"""Optional TokenHarbor free-route connection for Claude clients."""
import json
import os
import time
import urllib.error
import urllib.request

import yaml

from backend import AccountError, atomic_write


PROVIDER = 'gemini-accounts-tokenharbor-free'
BASE_URL = 'https://tokenharbor.ai'
UPSTREAM_MODEL = 'claude-haiku-5.5:free'
CLIENT_MODEL = 'claude-haiku-5-5-tokenharbor-free'
DISPLAY_NAME = 'TokenHarbor · Claude Haiku 5.5 Free'


class TokenHarbor:
    def __init__(self, controller, integrations):
        self.controller = controller
        self.integrations = integrations

    def config(self):
        path = self.controller.proxy_dir / 'config.yaml'
        return path, yaml.safe_load(path.read_text('utf-8-sig'))

    @staticmethod
    def write_live_config(path, data):
        """Keep the watched file in place so CLIProxyAPI reloads its configuration."""
        with path.open('r+b') as config_file:
            config_file.seek(0)
            config_file.write(data)
            config_file.truncate()
            config_file.flush()
            os.fsync(config_file.fileno())

    def connected(self):
        try:
            _, config = self.config()
            return any(group.get('name') == PROVIDER for group in
                       config.get('api-keys', {}).get('claude', []))
        except (OSError, ValueError, AttributeError, yaml.YAMLError):
            return False

    @staticmethod
    def verify_key(key):
        """Exercise the exact free Anthropic route before saving a credential."""
        payload = json.dumps({'model': UPSTREAM_MODEL, 'max_tokens': 1,
                              'messages': [{'role': 'user', 'content': '.'}]}).encode()
        request = urllib.request.Request(BASE_URL + '/v1/messages', data=payload,
            headers={'Authorization': 'Bearer ' + key, 'Anthropic-Version': '2023-06-01',
                     'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
                if response.status != 200 or result.get('type') != 'message':
                    raise AccountError('TokenHarbor did not confirm the free model.')
        except urllib.error.HTTPError as error:
            # Do not include request headers or credential-bearing URLs in UI errors.
            raise AccountError('TokenHarbor rejected the free-model test (HTTP ' +
                               str(error.code) + '). Check the key and enable free models in TokenHarbor.') from error
        except (OSError, ValueError) as error:
            raise AccountError('Could not reach TokenHarbor to check the free model.') from error

    @staticmethod
    def group(key):
        return {'name': PROVIDER, 'base-url': BASE_URL,
                'models': [{'name': UPSTREAM_MODEL, 'alias': CLIENT_MODEL,
                            'display-name': DISPLAY_NAME, 'max-context-length': 1000000,
                            'force-mapping': True}],
                'keys': [{'api-key': key}]}

    def approved_desktop_preset(self):
        if not self.integrations.legacy_desktop_preset():
            return None
        path = self.integrations.paths()['claude_desktop'][2]
        return path if str(path.resolve()) in self.integrations.backups() else None

    def model_listed(self):
        key = (self.controller.proxy_dir / 'client-key.txt').read_text('utf-8-sig').strip()
        request = urllib.request.Request(self.controller.base + '/v1/models',
                                         headers={'Authorization': 'Bearer ' + key})
        with urllib.request.urlopen(request, timeout=3) as response:
            return any(item.get('id') == CLIENT_MODEL for item in json.load(response).get('data', []))

    def probe_gateway(self):
        """Confirm that Claude's local route reaches the free upstream model."""
        key = (self.controller.proxy_dir / 'client-key.txt').read_text('utf-8-sig').strip()
        payload = json.dumps({'model': CLIENT_MODEL, 'max_tokens': 1,
                              'messages': [{'role': 'user', 'content': '.'}]}).encode()
        request = urllib.request.Request(self.controller.base + '/v1/messages', data=payload,
            headers={'Authorization': 'Bearer ' + key, 'Anthropic-Version': '2023-06-01',
                     'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200 and json.load(response).get('type') == 'message'

    def connect(self, key):
        key = key.strip()
        if not key.startswith('thk_') or any(character.isspace() for character in key):
            raise AccountError('Enter a TokenHarbor Universal Key beginning with thk_.')
        self.verify_key(key)
        with self.integrations.lock:
            path, config = self.config()
            if config.get('server', {}).get('host') not in ('127.0.0.1', 'localhost'):
                raise AccountError('The local gateway is not restricted to this computer.')
            previous = path.read_bytes()
            groups = config.setdefault('api-keys', {}).setdefault('claude', [])
            if any(group.get('name') != PROVIDER and
                   any(model.get('alias') == CLIENT_MODEL for model in group.get('models', []))
                   for group in groups):
                raise AccountError('Another provider already uses the TokenHarbor model name.')
            if any(item.get('alias') == CLIENT_MODEL for channel in
                   config.get('oauth', {}).get('model-alias', {}).values()
                   for item in channel):
                raise AccountError('A Google model already uses the TokenHarbor model name.')
            groups[:] = [group for group in groups if group.get('name') != PROVIDER]
            groups.append(self.group(key))
            preset_path = self.approved_desktop_preset()
            preset = self.integrations.read_json(preset_path) if preset_path else None
            original_preset = preset_path.read_bytes() if preset_path else None
            if preset is not None:
                models = preset.setdefault('inferenceModels', [])
                models[:] = [model for model in models if model.get('name') != CLIENT_MODEL]
                models.append({'name': CLIENT_MODEL, 'labelOverride': DISPLAY_NAME,
                               'anthropicFamilyTier': 'haiku', 'isFamilyDefault': False,
                               'supports1m': True, 'prefer1m': True})
            try:
                self.write_live_config(path, yaml.safe_dump(config, sort_keys=False).encode())
                # CLIProxyAPI hot-reloads the file; confirm its model menu includes the new route.
                for _ in range(20):
                    try:
                        if self.model_listed():
                            break
                    except OSError:
                        pass
                    time.sleep(.25)
                else:
                    raise AccountError('The gateway did not load TokenHarbor. Previous settings were restored.')
                for _ in range(12):
                    try:
                        if self.probe_gateway():
                            break
                    except urllib.error.HTTPError as error:
                        status = error.code
                    except OSError:
                        status = 0
                    else:
                        status = 0
                    time.sleep(.25)
                else:
                    raise AccountError('The local free-model test failed (HTTP ' + str(status) +
                                       '). Previous settings were restored.')
                if preset_path:
                    self.integrations.write_json(preset_path, preset)
            except Exception:
                self.write_live_config(path, previous)
                if preset_path:
                    atomic_write(preset_path, original_preset)
                raise
            return bool(preset_path)

    def disconnect(self, update_desktop=True):
        """Remove only the managed provider and its managed Claude menu entry."""
        with self.integrations.lock:
            path, config = self.config()
            groups = config.get('api-keys', {}).get('claude', [])
            kept = [group for group in groups if group.get('name') != PROVIDER]
            removed = len(kept) != len(groups)
            if removed:
                config['api-keys']['claude'] = kept
                self.write_live_config(path, yaml.safe_dump(config, sort_keys=False).encode())
            if update_desktop:
                preset_path = self.approved_desktop_preset()
                if preset_path:
                    preset = self.integrations.read_json(preset_path)
                    models = preset.get('inferenceModels', [])
                    filtered = [model for model in models if model.get('name') != CLIENT_MODEL]
                    if len(filtered) != len(models):
                        preset['inferenceModels'] = filtered
                        self.integrations.write_json(preset_path, preset)
            return removed
