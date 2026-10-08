"""Offline installer; client configuration consent belongs to the account manager."""
import ctypes
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import bcrypt
import yaml
from backend import dpapi, atomic_write, Controller
from integrations import Integrations


def prepare_update(root):
    root = Path(root)
    secret = root / 'GeminiAccounts' / 'management-key.dpapi'
    if secret.exists():
        key = dpapi(secret.read_bytes(), decrypt=True).decode()
        request = urllib.request.Request('http://127.0.0.1:8317/v0/management/quota-wait', headers={'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                if json.load(response).get('jobs'):
                    raise RuntimeError('Requests are running. Wait for them to finish before updating.')
        except OSError:
            pass
    env = os.environ.copy()
    env['GEMINI_ACCOUNTS_UPDATE_PATHS'] = json.dumps([str(root / 'GeminiAccounts' / 'GeminiAccounts.exe'), str(root / 'ClaudeGemini' / 'GeminiQuotaQueue.exe'), str(root / 'ClaudeGemini' / 'cli-proxy-api.exe')])
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', '$paths=ConvertFrom-Json $env:GEMINI_ACCOUNTS_UPDATE_PATHS; Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -in $paths} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}'], env=env, creationflags=subprocess.CREATE_NO_WINDOW, check=True)


def install(payload, root, shortcuts=True):
    payload, root = Path(payload), Path(root)
    manager, proxy = root / 'GeminiAccounts', root / 'ClaudeGemini'
    manager.mkdir(parents=True, exist_ok=True)
    proxy.mkdir(parents=True, exist_ok=True)
    (proxy / 'auth').mkdir(exist_ok=True)
    if shortcuts and (proxy / 'config.yaml').exists():
        prepare_update(root)
    for name, dest in [('GeminiAccounts.exe', manager), ('GeminiQuotaQueue.exe', proxy),
                       ('cli-proxy-api.exe', proxy), ('start-proxy.ps1', proxy), ('CLIProxyAPI-LICENSE.txt', proxy)]:
        for attempt in range(15):
            try:
                shutil.copyfile(payload / name, dest / name)
                break
            except PermissionError:
                if attempt == 14:
                    raise
                time.sleep(.2)
    config_path = proxy / 'config.yaml'
    if not config_path.exists():
        key, management = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        atomic_write(proxy / 'client-key.txt', key.encode())
        atomic_write(manager / 'management-key.dpapi', dpapi(management.encode()))
        config = {
            'config-version': 8, 'server': {'host': '127.0.0.1', 'port': 8318},
            'access': {'api-keys': [key]},
            'management': {'allow-remote': False, 'disable-control-panel': True,
                           'secret-key': bcrypt.hashpw(management.encode(), bcrypt.gensalt()).decode()},
            'oauth': {'auth-dir': str((proxy / 'auth').resolve()), 'model-alias': {'antigravity': [
                {'name': 'gemini-3.1-pro-low', 'alias': 'claude-sonnet-4-5', 'display-name': 'Gemini Pro', 'fork': True, 'force-mapping': True},
                {'name': 'gemini-3-flash', 'alias': 'claude-haiku-4-5', 'display-name': 'Gemini Flash', 'fork': True, 'force-mapping': True}]}},
            'routing': {'strategy': 'fill-first', 'cooldown': {'save-cooldown-status': True},
                        'retry': {'request-retry': 0, 'max-retry-interval': 0}},
            'quota-exceeded': {'switch-project': True},
            'requests': {'streaming': {'keepalive-seconds': 5}},
        }
        atomic_write(config_path, yaml.safe_dump(config, sort_keys=False).encode())
    atomic_write(manager / 'installation.json', json.dumps({'version': '1.3.0'}).encode())
    if shortcuts:
        # PowerShell receives paths as environment data, never executable interpolation.
        env = os.environ.copy()
        env['GEMINI_ACCOUNTS_INSTALLED_EXE'] = str(manager / 'GeminiAccounts.exe')
        script = "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Gemini Accounts.lnk')); $s.TargetPath=$env:GEMINI_ACCOUNTS_INSTALLED_EXE; $s.WorkingDirectory=Split-Path $s.TargetPath; $s.IconLocation=$s.TargetPath; $s.Save()"
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    return manager / 'GeminiAccounts.exe'


def main():
    payload = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload'
    root = Controller().data_dir.parent
    window = tk.Tk()
    window.title('Install Gemini Accounts')
    window.geometry('510x270')
    window.configure(bg='#191f2b')
    tk.Label(window, text='Gemini Accounts', font=('Segoe UI', 24, 'bold'), bg='#191f2b', fg='#edf2fa').pack(pady=(25, 15))
    tk.Label(window, text='Account manager and local Claude / Codex connection.\nClient settings are changed only with your consent.\nUpdating restarts Gemini Accounts services.\nSaved sign-ins and configurations are preserved.', font=('Segoe UI', 11), bg='#191f2b', fg='#9daec4').pack()
    def perform():
        button.configure(state='disabled', text='Installing…')
        window.update_idletasks()
        try:
            controller = Controller(proxy_dir=root / 'ClaudeGemini', data_dir=root / 'GeminiAccounts')
            integrations = Integrations(controller)
            backups = integrations.backups()
            clients = [name for name, paths in integrations.paths().items()
                       if any(str(p.resolve()) in backups for p in paths)]
            if integrations.legacy_desktop_preset() and 'claude_desktop' not in clients:
                clients.append('claude_desktop')
            update_clients = clients and messagebox.askyesno('Update connected applications?',
                'Update connected client model names and context windows?\n\n'
                'This modifies their configuration files. Original settings are backed up and can be restored '
                'from Gemini Accounts. Restart clients afterwards to load the changes.', parent=window)
            executable = install(payload, root)
            if update_clients:
                integrations.apply(clients)
            subprocess.Popen([str(executable)], creationflags=subprocess.CREATE_NO_WINDOW)
            window.destroy()
        except Exception as error:
            button.configure(state='normal', text='Install')
            messagebox.showerror('Installation failed', 'Close Gemini Accounts before updating.\n' + str(error), parent=window)
    button = tk.Button(window, text='Install', command=perform, font=('Segoe UI', 13, 'bold'), bg='#739aff', fg='#10141d', relief='flat', padx=45, pady=8)
    button.pack(pady=24)
    window.mainloop()


if __name__ == '__main__':
    main()
