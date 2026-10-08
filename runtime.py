"""Portable local runtime: pinned native binaries, private storage and services."""
import hashlib
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

import bcrypt
import yaml
from backend import AccountError, atomic_write, dpapi

VERSION = '1.3.1'
UPSTREAM_VERSION = '8.0.16'
ARCHIVES = {
    ('Windows', 'amd64'): ('windows_amd64.zip', 'e0d999703c9af70067b15bf50e6521e76392da604d1543541361e6891c676c43'),
    ('Windows', 'aarch64'): ('windows_aarch64.zip', '7e2c6864ba63dccd861fe429e9e15c1a5be186fe2efabddaa95cfff629c4213a'),
    ('Darwin', 'amd64'): ('darwin_amd64.tar.gz', '2c5a7e73f31d784f5732b6d24998286706b0dd60e7c6c1724988d9aeae2a4a0e'),
    ('Darwin', 'aarch64'): ('darwin_aarch64.tar.gz', 'b2c48e27b62bc94c71387e43be287c742b0336f21e2fe203568233593983d495'),
    ('Linux', 'amd64'): ('linux_amd64.tar.gz', 'affb5a189184e41b4335549e498df6f4f1c7f15dd0d04a28286becc2dfa78579'),
    ('Linux', 'aarch64'): ('linux_aarch64.tar.gz', 'e84f37c92bf48a057e5c2ff3e2a30851a4e43c64efcf442473ea04a43b9ddebb'),
}


def native_asset(system=None, machine=None):
    machine = (machine or platform.machine()).lower()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}.get(machine)
    try:
        return ARCHIVES[(system or platform.system(), arch)]
    except KeyError:
        raise AccountError('Unsupported platform. Supported: Windows, macOS and Linux on x64 or ARM64.') from None


def native_path(controller):
    return controller.proxy_dir / ('cli-proxy-api.exe' if os.name == 'nt' else 'cli-proxy-api')


def install_native(controller):
    target = native_path(controller)
    if target.exists():
        return target
    asset, expected = native_asset()
    name = f'CLIProxyAPI_{UPSTREAM_VERSION}_{asset}'
    url = f'https://github.com/router-for-me/CLIProxyAPI/releases/download/v{UPSTREAM_VERSION}/{name}'
    print(f'Downloading CLIProxyAPI {UPSTREAM_VERSION} ({asset})…', flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = response.read(150 * 1024 * 1024)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise AccountError('Native service download failed checksum verification.')
    wanted = {target.name: target, 'LICENSE': controller.proxy_dir / 'CLIProxyAPI-LICENSE.txt'}
    found = {}
    if asset.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            for item in zipped.infolist():
                base = Path(item.filename).name
                if base in wanted and not item.is_dir():
                    found[base] = zipped.read(item)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for item in tar.getmembers():
                base = Path(item.name).name
                if base in wanted and item.isfile():
                    with tar.extractfile(item) as file:
                        found[base] = file.read()
    if set(found) != set(wanted):
        raise AccountError('Native service archive is missing required files.')
    for name, dest in wanted.items():
        atomic_write(dest, found[name])
    if os.name != 'nt':
        target.chmod(0o700)
    return target


def initialize(controller):
    controller.proxy_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    controller.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    auth = controller.proxy_dir / 'auth'
    auth.mkdir(exist_ok=True, mode=0o700)
    config_path = controller.proxy_dir / 'config.yaml'
    if not config_path.exists():
        key, management = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        atomic_write(controller.proxy_dir / 'client-key.txt', key.encode())
        atomic_write(controller.data_dir / 'management-key.dpapi', dpapi(management.encode()))
        config = {
            'config-version': 8, 'server': {'host': '127.0.0.1', 'port': 8318},
            'access': {'api-keys': [key]},
            'management': {'allow-remote': False, 'disable-control-panel': True,
                           'secret-key': bcrypt.hashpw(management.encode(), bcrypt.gensalt()).decode()},
            'oauth': {'auth-dir': str(auth.resolve()), 'model-alias': {'antigravity': [
                {'name': 'gemini-3.1-pro-low', 'alias': 'claude-sonnet-4-5', 'display-name': 'Gemini Pro', 'fork': True, 'force-mapping': True},
                {'name': 'gemini-3-flash', 'alias': 'claude-haiku-4-5', 'display-name': 'Gemini Flash', 'fork': True, 'force-mapping': True}]}},
            'routing': {'strategy': 'fill-first', 'cooldown': {'save-cooldown-status': True},
                        'retry': {'request-retry': 0, 'max-retry-interval': 0}},
            'quota-exceeded': {'switch-project': True},
            'requests': {'streaming': {'keepalive-seconds': 5}},
        }
        atomic_write(config_path, yaml.safe_dump(config, sort_keys=False).encode())
    return config_path


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            return True
    except OSError:
        return False


def ready(port, endpoint, key):
    request = urllib.request.Request(f'http://127.0.0.1:{port}{endpoint}', headers={'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def start_services(controller):
    config = yaml.safe_load((controller.proxy_dir / 'config.yaml').read_text('utf-8-sig'))
    if config.get('server', {}).get('host') not in ('127.0.0.1', 'localhost'):
        raise AccountError('The native service must listen on localhost only.')
    key = dpapi((controller.data_dir / 'management-key.dpapi').read_bytes(), decrypt=True).decode()
    native_port = config['server']['port']
    env = os.environ.copy()
    env['GEMINI_ACCOUNTS_HOME'] = str(controller.data_dir.parent)
    source = Path(__file__).resolve().parent
    tasks = [
        (native_port, '/v0/management/auth-files', [str(native_path(controller)), '-config', str(controller.proxy_dir / 'config.yaml')], 'native'),
        (8317, '/v0/management/quota-wait', [sys.executable, '--internal-queue'] if getattr(sys, 'frozen', False)
         else [sys.executable, str(source / 'quota_queue.py')], 'queue'),
    ]
    owned = []
    try:
        for port, endpoint, command, name in tasks:
            if ready(port, endpoint, key):
                continue
            if port_open(port):
                raise AccountError(f'Port {port} is used by another service. Stop that service or use your existing installation.')
            with (controller.data_dir / (name + '.log')).open('ab') as log:
                child = subprocess.Popen(command, cwd=controller.proxy_dir, env=env, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
            owned.append(child)
            for _ in range(80):
                if ready(port, endpoint, key):
                    break
                if child.poll() is not None:
                    raise AccountError(f'{name.title()} service failed to start. Check {name}.log in {controller.data_dir}.')
                time.sleep(.15)
            else:
                raise AccountError(f'{name.title()} service did not become ready.')
    except Exception:
        stop_owned(owned)
        raise
    controller.key = key
    controller.base = f'http://127.0.0.1:{native_port}'
    return owned


def stop_owned(processes):
    for child in reversed(processes):
        if child.poll() is None:
            if os.name == 'nt':
                # Frozen one-file workers have a bootloader and a Python child.
                # Only stop descendants of the exact process we started.
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                    creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
