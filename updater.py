"""Verified GitHub release updates for the installed Windows desktop application."""
import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from backend import AccountError
from runtime import VERSION

REPO = 'nikitaeight24family/GeminiAccounts'
API = 'https://api.github.com/repos/' + REPO + '/releases/latest'


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise ValueError('Invalid release version')
    return tuple(map(int, match.groups()))


def check_update():
    request = urllib.request.Request(API, headers={'User-Agent':'GeminiAccounts/' + VERSION, 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    if release.get('draft') or release.get('prerelease') or version(release['tag_name']) <= version(VERSION):
        return None
    asset = next((a for a in release.get('assets', []) if a['name'] == 'GeminiAccounts-Setup.exe'), None)
    if not asset or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or ''):
        raise AccountError('The release has no verified Windows installer.')
    prefix = 'https://github.com/' + REPO + '/releases/download/' + release['tag_name'] + '/'
    if asset.get('browser_download_url') != prefix + 'GeminiAccounts-Setup.exe':
        raise AccountError('Unexpected update download location.')
    return {'version': release['tag_name'], 'url': asset['browser_download_url'], 'sha256':asset['digest'][7:]}


def download_update(controller, release):
    directory = controller.data_dir / 'updates'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('GeminiAccounts-Setup-' + release['version'] + '.exe')
    temporary = target.with_suffix('.download')
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(release['url'], timeout=60) as response, temporary.open('wb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != release['sha256']:
            raise AccountError('Update checksum mismatch. No files were replaced.')
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def launch_update(controller, installer):
    subprocess.Popen([str(installer), '--auto-update', '--root', str(controller.data_dir.parent)],
                     creationflags=subprocess.CREATE_NO_WINDOW)
