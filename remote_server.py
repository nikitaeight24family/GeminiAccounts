"""Remote server backend management: SSH connectivity, one-click Ubuntu deployment,
account migration, and client connection snippets.
"""
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from backend import AccountError


def _safe_text(value):
    return str(value or '').strip()


def build_ssh_command(config, remote_cmd=''):
    """Build OpenSSH command line supporting Windows native FIDO keys and system agent."""
    host = _safe_text(config.get('host'))
    port = str(config.get('port') or '22').strip()
    user = _safe_text(config.get('user') or 'root')
    key_path = _safe_text(config.get('key_path'))
    use_fido = bool(config.get('use_fido'))

    if not host:
        raise AccountError('Server host or IP address is required.')

    ssh_bin = (shutil.which('ssh.exe') or
               shutil.which('ssh') or
               r'C:\Windows\System32\OpenSSH\ssh.exe')
    if not os.path.exists(ssh_bin) and not shutil.which(ssh_bin):
        ssh_bin = 'ssh'

    args = [
        ssh_bin,
        '-p', port,
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ConnectTimeout=15',
    ]

    if key_path and os.path.exists(key_path):
        args.extend(['-i', key_path])

    if use_fido:
        # Avoid BatchMode so native Windows WebAuthn prompt appears if needed
        pass
    elif not config.get('password') and not key_path:
        args.extend(['-o', 'BatchMode=yes'])

    destination = f'{user}@{host}' if user else host
    args.append(destination)
    if remote_cmd:
        args.append(remote_cmd)
    return args


def run_ssh_command(config, remote_cmd, stdin_data=None, timeout=120):
    """Execute command on remote server via paramiko or OpenSSH fallback."""
    password = _safe_text(config.get('password'))
    key_path = _safe_text(config.get('key_path'))
    use_fido = bool(config.get('use_fido'))

    # If FIDO is enabled or password is not provided but keys/agent are used,
    # prefer OpenSSH to allow native Windows Hello / Security Key dialog.
    if use_fido or (not password and not key_path):
        cmd = build_ssh_command(config, remote_cmd)
        try:
            res = subprocess.run(
                cmd,
                input=stdin_data.encode('utf-8') if isinstance(stdin_data, str) else stdin_data,
                capture_output=True,
                timeout=timeout
            )
            stdout = res.stdout.decode('utf-8', errors='replace').strip()
            stderr = res.stderr.decode('utf-8', errors='replace').strip()
            if res.returncode != 0:
                msg = stderr or stdout or f'SSH failed with exit code {res.returncode}'
                raise AccountError(msg)
            return stdout
        except subprocess.TimeoutExpired:
            raise AccountError('SSH connection timed out. Check host and security key confirmation.') from None
        except FileNotFoundError:
            raise AccountError('OpenSSH client (ssh.exe) was not found on this system.') from None

    # For password or explicit key file, use paramiko for in-process reliable execution
    try:
        import paramiko
    except ImportError:
        # Fall back to ssh subprocess
        cmd = build_ssh_command(config, remote_cmd)
        res = subprocess.run(cmd, input=stdin_data.encode('utf-8') if stdin_data else None,
                             capture_output=True, timeout=timeout)
        if res.returncode != 0:
            raise AccountError(res.stderr.decode('utf-8', errors='replace').strip() or 'SSH command failed')
        return res.stdout.decode('utf-8', errors='replace').strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = _safe_text(config.get('host'))
    port = int(config.get('port') or 22)
    user = _safe_text(config.get('user') or 'root')

    pkey = None
    if key_path and os.path.exists(key_path):
        for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = key_class.from_private_key_file(key_path, password=password or None)
                break
            except Exception:
                continue

    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password or None,
            pkey=pkey,
            timeout=15,
            allow_agent=True,
            look_for_keys=True
        )
        stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=timeout)
        if stdin_data:
            if isinstance(stdin_data, str):
                stdin_data = stdin_data.encode('utf-8')
            stdin.write(stdin_data)
            stdin.flush()
            stdin.channel.shutdown_write()
        out_text = stdout.read().decode('utf-8', errors='replace').strip()
        err_text = stderr.read().decode('utf-8', errors='replace').strip()
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise AccountError(err_text or out_text or f'Remote command exited with code {code}')
        return out_text
    except Exception as exc:
        if isinstance(exc, AccountError):
            raise
        raise AccountError(f'SSH connection failed: {exc}') from exc
    finally:
        client.close()


def test_ssh_connection(config):
    """Verify SSH connection and identify remote OS and user."""
    test_cmd = "uname -s && whoami && (lsb_release -d 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 || true)"
    out = run_ssh_command(config, test_cmd, timeout=25)
    lines = [line.strip().strip('"') for line in out.splitlines() if line.strip()]
    kernel = lines[0] if lines else 'Linux'
    user = lines[1] if len(lines) > 1 else config.get('user', '')
    os_name = lines[2].replace('Description:', '').strip() if len(lines) > 2 else 'Ubuntu/Linux'
    return {
        'connected': True,
        'kernel': kernel,
        'user': user,
        'os': os_name,
        'host': config.get('host'),
        'port': config.get('port', 22)
    }


def get_client_snippets(server_ip, client_key):
    """Generate ready-to-run terminal snippets and configurations for all supported clients."""
    server_ip = _safe_text(server_ip) or 'YOUR_SERVER_IP'
    client_key = _safe_text(client_key) or 'YOUR_GATEWAY_KEY'
    base_url = f'http://{server_ip}:8317'
    responses_url = f'{base_url}/v1'

    claude_cli_ps = f'''[IO.File]::WriteAllText("$HOME\\.claude\\settings.json", '{{"env":{{"ANTHROPIC_BASE_URL":"{base_url}","ANTHROPIC_AUTH_TOKEN":"{client_key}","ANTHROPIC_API_KEY":"","CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY":"1","API_TIMEOUT_MS":"604800000","CLAUDE_ENABLE_STREAM_WATCHDOG":"0"}}}}')'''

    claude_cli_bash = f'''mkdir -p ~/.claude && cat << 'EOF' > ~/.claude/settings.json
{{
  "env": {{
    "ANTHROPIC_BASE_URL": "{base_url}",
    "ANTHROPIC_AUTH_TOKEN": "{client_key}",
    "ANTHROPIC_API_KEY": "",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
    "API_TIMEOUT_MS": "604800000",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0"
  }}
}}
EOF'''

    codex_ps = f'''Add-Content "$HOME\\.codex\\config.toml" @"

model = "gpt-6.1-sol"
model_provider = "omni_server"

[model_providers.omni_server]
name = "Omni Server"
base_url = "{responses_url}"
wire_api = "responses"
experimental_bearer_token = "{client_key}"
requires_openai_auth = false
stream_idle_timeout_ms = 604800000
request_max_retries = 2
supports_websockets = false
"@'''

    codex_bash = f'''cat << 'EOF' >> ~/.codex/config.toml

model = "gpt-6.1-sol"
model_provider = "omni_server"

[model_providers.omni_server]
name = "Omni Server"
base_url = "{responses_url}"
wire_api = "responses"
experimental_bearer_token = "{client_key}"
requires_openai_auth = false
stream_idle_timeout_ms = 604800000
request_max_retries = 2
supports_websockets = false
EOF'''

    claude_desktop_json = f'''{{
  "inferenceGatewayBaseUrl": "{base_url}",
  "inferenceGatewayApiKey": "{client_key}",
  "inferenceProvider": "gateway",
  "inferenceGatewayAuthScheme": "bearer",
  "inferenceCredentialKind": "static"
}}'''

    return {
        'server_ip': server_ip,
        'client_key': client_key,
        'gateway_url': base_url,
        'responses_url': responses_url,
        'claude_code_ps': claude_cli_ps,
        'claude_code_bash': claude_cli_bash,
        'codex_ps': codex_ps,
        'codex_bash': codex_bash,
        'claude_desktop_json': claude_desktop_json
    }


def collect_accounts_payload(controller):
    """Bundle local auth files into a structured payload for migration."""
    auth_dir = controller.proxy_dir / 'auth'
    accounts = {}
    if auth_dir.exists():
        for path in auth_dir.glob('*.json'):
            try:
                accounts[path.name] = path.read_text(encoding='utf-8')
            except Exception:
                continue
    return accounts


def deploy_to_server(config, controller, progress_callback=None):
    """Deploy Omni gateway service and migrate existing accounts to Ubuntu server in one batch."""
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    log('Testing remote server connectivity...')
    info = test_ssh_connection(config)
    log(f"Connected to {info.get('os', 'Linux')} as {info.get('user', 'root')}.")

    # 1. Collect accounts to transfer
    log('Bundling accounts and authentication tokens...')
    accounts = collect_accounts_payload(controller)
    accounts_json = json.dumps(accounts, ensure_ascii=False)

    # 2. Prepare single batched deployment script
    log('Executing remote setup and deploying gateway service...')
    setup_script = r'''#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="$HOME/.omni-server"
mkdir -p "$TARGET_DIR/auth" "$TARGET_DIR/bin" "$HOME/.config/systemd/user"
chmod 700 "$TARGET_DIR" "$TARGET_DIR/auth"

# Download latest linux-x64 binary if not present
if [ ! -f "$TARGET_DIR/bin/cli-proxy-api" ]; then
    echo "Fetching Linux gateway binary..."
    URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.16/CLIProxyAPI_8.0.16_linux_amd64.tar.gz"
    curl -fsSL "$URL" | tar -xz -C "$TARGET_DIR/bin" cli-proxy-api 2>/dev/null || true
    if [ ! -f "$TARGET_DIR/bin/cli-proxy-api" ]; then
        # Try fallback release zip
        ZIP_URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.16/CLIProxyAPI_8.0.16_linux_amd64.zip"
        curl -fsSL "$ZIP_URL" -o "$TARGET_DIR/bin/cliproxy.zip" && unzip -q -o "$TARGET_DIR/bin/cliproxy.zip" -d "$TARGET_DIR/bin" && rm -f "$TARGET_DIR/bin/cliproxy.zip" || true
    fi
    chmod +x "$TARGET_DIR/bin/cli-proxy-api" 2>/dev/null || true
fi

# Ensure client-key exists
if [ ! -f "$TARGET_DIR/client-key.txt" ]; then
    head -c 32 /dev/urandom | xxd -p > "$TARGET_DIR/client-key.txt" 2>/dev/null || date +%s%N | sha256sum | head -c 64 > "$TARGET_DIR/client-key.txt"
fi
CLIENT_KEY=$(cat "$TARGET_DIR/client-key.txt" | tr -d '[:space:]')

# Write gateway config
cat << 'CFG_EOF' > "$TARGET_DIR/config.yaml"
config-version: 8
server:
    host: 0.0.0.0
    port: 8317
access:
    api-keys:
        - __CLIENT_KEY__
routing:
    strategy: fill-first
    cooldown:
        save-cooldown-status: true
    retry:
        request-retry: 0
        max-retry-interval: 0
quota-exceeded:
    switch-project: true
oauth:
    auth-dir: __AUTH_DIR__
    providers:
        aistudio:
            ws-auth: true
    model-alias:
        antigravity:
            - name: gemini-3.8-flash-high
              alias: claude-sonnet-4-5
              fork: true
              display-name: 3.8 Flash High
              force-mapping: true
            - name: gemini-3.8-flash-high
              alias: gemini-selected
              fork: true
CFG_EOF

sed -i "s|__CLIENT_KEY__|$CLIENT_KEY|g" "$TARGET_DIR/config.yaml"
sed -i "s|__AUTH_DIR__|$TARGET_DIR/auth|g" "$TARGET_DIR/config.yaml"

# Unpack transferred accounts from STDIN
python3 -c "
import sys, json, os
data = json.loads(sys.stdin.read())
target = os.path.expanduser('~/.omni-server/auth')
os.makedirs(target, exist_ok=True)
for name, content in data.items():
    p = os.path.join(target, name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(p, 0o600)
print(f'Imported {len(data)} accounts')
"

# Create systemd user service
cat << 'SVC_EOF' > "$HOME/.config/systemd/user/omni.service"
[Unit]
Description=Omni AI Gateway Service
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/.omni-server
ExecStart=%h/.omni-server/bin/cli-proxy-api -config %h/.omni-server/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SVC_EOF

# Enable lingering and start service
loginctl enable-linger "$(whoami)" 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now omni.service 2>/dev/null || {
    # If systemd user session is unavailable, start in background
    pkill -f "cli-proxy-api -config" || true
    nohup "$TARGET_DIR/bin/cli-proxy-api" -config "$TARGET_DIR/config.yaml" > "$TARGET_DIR/server.log" 2>&1 &
}

sleep 1
echo "OMNI_DEPLOY_OK:$CLIENT_KEY"
'''

    log('Deploying service and migrating accounts...')
    out = run_ssh_command(config, setup_script, stdin_data=accounts_json, timeout=120)

    match = re.search(r'OMNI_DEPLOY_OK:([a-zA-Z0-9_-]+)', out)
    if not match:
        client_key = 'omni-secret-token'
    else:
        client_key = match.group(1).strip()

    server_ip = config.get('host')
    log(f'Backend successfully deployed to {server_ip}!')
    log('Gateway listening on port 8317.')

    snippets = get_client_snippets(server_ip, client_key)

    # Save remote server settings in preferences
    prefs = controller.preferences
    server_pref = {
        'host': server_ip,
        'port': config.get('port', 22),
        'user': config.get('user', 'root'),
        'key_path': config.get('key_path', ''),
        'use_fido': bool(config.get('use_fido')),
        'client_key': client_key,
        'last_deployed': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    prefs['remote-server'] = server_pref
    controller.save()

    return {
        'success': True,
        'server_ip': server_ip,
        'client_key': client_key,
        'snippets': snippets
    }
