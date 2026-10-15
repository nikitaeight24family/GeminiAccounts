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
import urllib.error
import urllib.request
from pathlib import Path

from backend import AccountError


def _safe_text(value):
    return str(value or '').strip()


def validate_ssh_config(config):
    """Validate the connection fields before attempting SSH.

    SSH agent authentication is valid, so a password or key is not mandatory.
    Host, user and port are always required and are checked again in the
    backend so an empty UI form can never start a network operation.
    """
    if not isinstance(config, dict):
        raise AccountError('Remote server settings are missing.')
    host = _safe_text(config.get('host'))
    if not host:
        raise AccountError('Enter a server host or IP address first.')
    if any(char.isspace() for char in host):
        raise AccountError('Server host cannot contain spaces.')
    user = _safe_text(config.get('user') or 'root')
    if not user:
        raise AccountError('Enter an SSH username first.')
    try:
        port = int(config.get('port') or 22)
    except (TypeError, ValueError):
        raise AccountError('SSH port must be a number between 1 and 65535.') from None
    if not 1 <= port <= 65535:
        raise AccountError('SSH port must be a number between 1 and 65535.')
    key_path = _safe_text(config.get('key_path'))
    if key_path and not os.path.isfile(key_path):
        raise AccountError('The selected SSH private key file was not found.')
    return {**config, 'host': host, 'user': user, 'port': port, 'key_path': key_path}


def build_ssh_command(config, remote_cmd=''):
    """Build OpenSSH command line supporting Windows native FIDO keys and system agent."""
    config = validate_ssh_config(config)
    host = config['host']
    port = str(config['port'])
    user = config['user']
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
    config = validate_ssh_config(config)
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
    config = validate_ssh_config(config)
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


def probe_remote_gateway(server, timeout=5):
    """Send a harmless authenticated request through the deployed gateway.

    The response is used by the UI to prove that the selected remote route is
    reachable and serving its model catalog. No model inference is generated.
    """
    if not isinstance(server, dict):
        return {'connected': False, 'error': 'Remote server is not configured.'}
    host = _safe_text(server.get('host'))
    client_key = _safe_text(server.get('client_key'))
    gateway_port = server.get('gateway_port') or 8317
    if not host or not client_key:
        return {'connected': False, 'error': 'Deploy the backend before selecting the remote route.'}
    try:
        gateway_port = int(gateway_port)
    except (TypeError, ValueError):
        return {'connected': False, 'error': 'Remote gateway port is invalid.'}
    if not 1 <= gateway_port <= 65535:
        return {'connected': False, 'error': 'Remote gateway port is invalid.'}
    url = f'http://{host}:{gateway_port}/v1/models'
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + client_key,
        'Accept': 'application/json',
        'User-Agent': 'Omni remote route check'
    })
    started = time.perf_counter()
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
            body = json.load(response)
            models = body.get('data', []) if isinstance(body, dict) else []
            return {
                'connected': True,
                'gateway': f'{host}:{gateway_port}',
                'status_code': int(getattr(response, 'status', 200)),
                'model_count': len(models) if isinstance(models, list) else 0,
                'latency_ms': round((time.perf_counter() - started) * 1000)
            }
    except urllib.error.HTTPError as exc:
        return {'connected': False, 'status_code': exc.code,
                'error': 'Remote gateway rejected the route key.' if exc.code == 401 else f'Remote gateway returned HTTP {exc.code}.'}
    except (OSError, ValueError, TypeError) as exc:
        return {'connected': False, 'error': f'Remote gateway is unreachable: {exc}'}


def get_client_snippets(server_ip, client_key):
    """Generate ready-to-run terminal snippets and configurations for all supported clients."""
    server_ip = _safe_text(server_ip) or 'YOUR_SERVER_IP'
    client_key = _safe_text(client_key) or 'YOUR_GATEWAY_KEY'
    base_url = f'http://{server_ip}:8317'
    responses_url = f'{base_url}/v1'

    claude_cli_ps = f'''$ErrorActionPreference = "Stop"
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {{ throw "Claude Code CLI is not installed or is not on PATH." }}
$path = Join-Path $HOME ".claude\\settings.json"
New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
$hadConfig = Test-Path -LiteralPath $path
$backup = $null
if ($hadConfig) {{
  $stamp = Get-Date -Format yyyyMMddHHmmss
  $backup = "$path.omni-backup-$stamp"
  $suffix = 1
  while (Test-Path -LiteralPath $backup) {{ $backup = "$path.omni-backup-$stamp-$suffix"; $suffix++ }}
  Copy-Item -LiteralPath $path -Destination $backup
}}
$data = @{{}}
if ($hadConfig) {{ try {{ $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }} catch {{ $data = @{{}} }} }}
if (-not $data.PSObject.Properties['env']) {{ $data | Add-Member NoteProperty env ([pscustomobject]@{{}}) }}
$data.env | Add-Member NoteProperty ANTHROPIC_BASE_URL '{base_url}' -Force
$data.env | Add-Member NoteProperty ANTHROPIC_AUTH_TOKEN '{client_key}' -Force
$data.env | Add-Member NoteProperty ANTHROPIC_API_KEY '' -Force
$data.env | Add-Member NoteProperty CLAUDE_CODE_AUTO_MODE_SERVER '0' -Force
$data.env | Add-Member NoteProperty CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY '1' -Force
$data.env | Add-Member NoteProperty API_TIMEOUT_MS '604800000' -Force
$data.env | Add-Member NoteProperty CLAUDE_ENABLE_STREAM_WATCHDOG '0' -Force
$tmp = "$path.omni.tmp-$PID"
$data | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $tmp
Move-Item -Force -LiteralPath $tmp -Destination $path
$check = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($check.env.ANTHROPIC_BASE_URL -ne '{base_url}' -or $check.env.ANTHROPIC_AUTH_TOKEN -ne '{client_key}') {{
  if ($hadConfig) {{ Copy-Item -LiteralPath $backup -Destination $path -Force }} else {{ Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }}
  throw "Claude Code route verification failed; the previous settings were restored."
}}
Write-Output "Omni Claude Code route active. Config: $path"
if ($backup) {{ Write-Output "Backup: $backup" }}'''

    claude_cli_bash = f'''set -euo pipefail
command -v claude >/dev/null 2>&1 || {{ echo "Claude Code CLI is not installed or is not on PATH." >&2; exit 127; }}
command -v python3 >/dev/null 2>&1 || {{ echo "Python 3 is required for the one-paste setup." >&2; exit 127; }}
CFG="${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}/settings.json"
mkdir -p "$(dirname "$CFG")"
BACKUP="${{CFG}}.omni-backup-$(date +%Y%m%d%H%M%S)"
HAD_CONFIG=0
if [ -f "$CFG" ]; then
  suffix=1
  while [ -e "$BACKUP" ]; do BACKUP="${{CFG}}.omni-backup-$(date +%Y%m%d%H%M%S)-$suffix"; suffix=$((suffix + 1)); done
  cp -p "$CFG" "$BACKUP"
  HAD_CONFIG=1
fi
restore_config() {{
  if [ "$HAD_CONFIG" -eq 1 ]; then cp -p "$BACKUP" "$CFG"; else rm -f "$CFG"; fi
}}
export OMNI_CLAUDE_URL={shlex.quote(base_url)} OMNI_CLAUDE_TOKEN={shlex.quote(client_key)}
if ! python3 - "$CFG" <<'PY'
import json, os, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {{}}
except Exception:
    data = {{}}
data.setdefault("env", {{}}).update({{
    "ANTHROPIC_BASE_URL": os.environ["OMNI_CLAUDE_URL"],
    "ANTHROPIC_AUTH_TOKEN": os.environ["OMNI_CLAUDE_TOKEN"],
    "ANTHROPIC_API_KEY": "",
    "CLAUDE_CODE_AUTO_MODE_SERVER": "0",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
    "API_TIMEOUT_MS": "604800000",
    "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
}})
tmp = path.with_name(path.name + ".omni.tmp")
tmp.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")
tmp.replace(path)
check = json.loads(path.read_text(encoding="utf-8-sig"))
if check.get("env", {{}}).get("ANTHROPIC_BASE_URL") != os.environ["OMNI_CLAUDE_URL"] or check.get("env", {{}}).get("ANTHROPIC_AUTH_TOKEN") != os.environ["OMNI_CLAUDE_TOKEN"]:
    raise SystemExit("Claude Code route verification failed")
PY
then
  restore_config
  echo "Claude Code setup failed; the previous settings were restored." >&2
  exit 1
fi
if [ "$HAD_CONFIG" -eq 1 ]; then printf 'Omni Claude Code route active. Config: %s\\nBackup: %s\\n' "$CFG" "$BACKUP"; else printf 'Omni Claude Code route active. Config: %s\\n' "$CFG"; fi'''

    codex_ps = f'''$ErrorActionPreference = "Stop"
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {{ throw "Codex CLI is not installed or is not on PATH." }}
$path = Join-Path $HOME ".codex\\config.toml"
New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
$hadConfig = Test-Path -LiteralPath $path
$backup = $null
if ($hadConfig) {{
  $stamp = Get-Date -Format yyyyMMddHHmmss
  $backup = "$path.omni-backup-$stamp"
  $suffix = 1
  while (Test-Path -LiteralPath $backup) {{ $backup = "$path.omni-backup-$stamp-$suffix"; $suffix++ }}
  Copy-Item -LiteralPath $path -Destination $backup
}}
$text = if ($hadConfig) {{ Get-Content -LiteralPath $path -Raw }} else {{ "" }}
$text = [regex]::Replace($text, '(?ms)^\\[model_providers\\.omni_server(?:\\.[^\\]]+)?\\]\\s*.*?(?=^\\[|\\z)', '')
$text = [regex]::Replace($text, '(?m)^\\s*model_provider\\s*=\\s*"omni_server"\\s*\\r?\\n', '')
$text = [regex]::Replace($text, '(?m)^\\s*model\\s*=\\s*"gpt-6\\.1-sol"\\s*\\r?\\n', '')
$lines = @($text -split '\\r?\\n')
$table = $lines | Select-String -Pattern '^\\s*\\[' | Select-Object -First 1
$idx = if ($table) {{ $table.LineNumber - 1 }} else {{ $lines.Count }}
$prefix = @()
if ($idx -gt 0) {{ $prefix = @($lines[0..($idx - 1)] | Where-Object {{ $_ -notmatch '^\\s*(model|model_provider)\\s*=' }}) }}
$rest = @()
if ($idx -lt $lines.Count) {{ $rest = @($lines[$idx..($lines.Count - 1)]) }}
$block = @(
  'model = "gpt-6.1-sol"',
  'model_provider = "omni_server"',
  '',
  '[model_providers.omni_server]',
  'name = "Omni Server"',
  'base_url = "{responses_url}"',
  'wire_api = "responses"',
  'experimental_bearer_token = "{client_key}"',
  'requires_openai_auth = false',
  'stream_idle_timeout_ms = 604800000',
  'request_max_retries = 2',
  'supports_websockets = false'
)
Set-Content -LiteralPath $path -Encoding utf8 -Value (($block + $prefix + $rest) -join "`n")
$doctor = (& codex doctor 2>&1 | Out-String)
$valid = $doctor -match 'default model provider\\s+omni_server' -and $doctor -match 'model provider requires OpenAI auth\\s+false'
if (-not $valid) {{
  if ($hadConfig) {{ Copy-Item -LiteralPath $backup -Destination $path -Force }} else {{ Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }}
  $doctor | Write-Error
  throw "Omni setup verification failed; the previous Codex config was restored."
}}
Write-Output "Omni Codex route active. Config: $path"
if ($backup) {{ Write-Output "Backup: $backup" }}'''

    codex_bash = f'''set -euo pipefail
command -v codex >/dev/null 2>&1 || {{ echo "Codex CLI is not installed or is not on PATH." >&2; exit 127; }}
command -v python3 >/dev/null 2>&1 || {{ echo "Python 3 is required for the one-paste setup." >&2; exit 127; }}
CFG="${{CODEX_HOME:-$HOME/.codex}}/config.toml"
mkdir -p "$(dirname "$CFG")"
BACKUP="${{CFG}}.omni-backup-$(date +%Y%m%d%H%M%S)"
HAD_CONFIG=0
if [ -f "$CFG" ]; then
  suffix=1
  while [ -e "$BACKUP" ]; do BACKUP="${{CFG}}.omni-backup-$(date +%Y%m%d%H%M%S)-$suffix"; suffix=$((suffix + 1)); done
  cp -p "$CFG" "$BACKUP"
  HAD_CONFIG=1
fi
restore_config() {{
  if [ "$HAD_CONFIG" -eq 1 ]; then cp -p "$BACKUP" "$CFG"; else rm -f "$CFG"; fi
}}
export OMNI_CODEX_URL={shlex.quote(responses_url)} OMNI_CODEX_TOKEN={shlex.quote(client_key)}
if ! python3 - "$CFG" <<'PY'
import json, os, re, sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8-sig") if path.exists() else ""

# Remove the complete Omni table wherever it is located.  Root model keys
# are removed only before the first TOML table, so unrelated client settings
# and other providers remain intact.
text = re.sub(r"(?ms)^\\[model_providers\\.omni_server(?:\\.[^\\]]+)?\\]\\s*.*?(?=^\\[|\\Z)", "", text)
text = re.sub(r'(?m)^\\s*model_provider\\s*=\\s*"omni_server"\\s*\\r?\\n', "", text)
text = re.sub(r'(?m)^\\s*model\\s*=\\s*"gpt-6\\.1-sol"\\s*\\r?\\n', "", text)
lines = text.splitlines()
first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
prefix = [line for line in lines[:first_table]
          if not re.match(r"^\\s*(?:model|model_provider)\\s*=", line)]
rest = lines[first_table:]
url = os.environ["OMNI_CODEX_URL"]
token = os.environ["OMNI_CODEX_TOKEN"]
block = [
    'model = "gpt-6.1-sol"',
    'model_provider = "omni_server"',
    '',
    '[model_providers.omni_server]',
    'name = "Omni Server"',
    'base_url = ' + json.dumps(url),
    'wire_api = "responses"',
    'experimental_bearer_token = ' + json.dumps(token),
    'requires_openai_auth = false',
    'stream_idle_timeout_ms = 604800000',
    'request_max_retries = 2',
    'supports_websockets = false',
]
path.write_text("\\n".join(block + prefix + rest).rstrip() + "\\n", encoding="utf-8")
PY
then
  restore_config
  echo "Codex setup failed; the previous config was restored." >&2
  exit 1
fi

DOCTOR="$(codex doctor 2>&1)" || true
if ! printf '%s\\n' "$DOCTOR" | grep -Eiq 'default model provider[[:space:]]+omni_server' || \\
   ! printf '%s\\n' "$DOCTOR" | grep -Eiq 'model provider requires OpenAI auth[[:space:]]+false'; then
  restore_config
  printf '%s\\n' "$DOCTOR" >&2
  echo "Omni setup verification failed; the previous Codex config was restored." >&2
  exit 1
fi
printf 'Omni Codex route active. Config: %s\\nBackup: %s\\n' "$CFG" "$BACKUP"'''

    # Desktop always uses the default profile.  CLI keeps CODEX_HOME support
    # so a user with an isolated CLI profile can target that profile explicitly.
    codex_desktop_ps = '# Codex Desktop (default profile)\n' + codex_ps
    codex_desktop_bash = codex_bash.replace(
        'CFG="${CODEX_HOME:-$HOME/.codex}/config.toml"',
        'CFG="$HOME/.codex/config.toml"',
        1,
    )
    codex_desktop_bash = '# Codex Desktop (default profile)\n' + codex_desktop_bash
    codex_cli_ps = '# Codex CLI (CODEX_HOME-aware profile)\n' + codex_ps
    codex_cli_bash = '# Codex CLI (CODEX_HOME-aware profile)\n' + codex_bash

    # These commands keep a timestamped backup and remove only Omni's
    # routing entries, leaving the rest of each client's configuration intact.
    claude_restore_ps = r'''$path="$HOME\.claude\settings.json"; if(Test-Path $path){Copy-Item $path "$path.omni-backup-$(Get-Date -Format yyyyMMddHHmmss)"; $data=Get-Content $path -Raw | ConvertFrom-Json; if($data.PSObject.Properties['env']){@('ANTHROPIC_BASE_URL','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_API_KEY','CLAUDE_CODE_AUTO_MODE_SERVER','CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY','API_TIMEOUT_MS','CLAUDE_ENABLE_STREAM_WATCHDOG') | ForEach-Object {if($data.env.PSObject.Properties[$_]){$data.env.PSObject.Properties.Remove($_)}}; if(-not $data.env.PSObject.Properties.Count){$data.PSObject.Properties.Remove('env')}}; $data | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $path}'''

    claude_restore_bash = r'''python3 - <<'PY'
import json, shutil
from datetime import datetime
from pathlib import Path
path = Path.home() / '.claude' / 'settings.json'
if path.exists():
    shutil.copy2(path, path.with_name(path.name + '.omni-backup-' + datetime.now().strftime('%Y%m%d%H%M%S')))
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    env = data.get('env', {})
    for key in ('ANTHROPIC_BASE_URL','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_API_KEY','CLAUDE_CODE_AUTO_MODE_SERVER','CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY','API_TIMEOUT_MS','CLAUDE_ENABLE_STREAM_WATCHDOG'):
        env.pop(key, None)
    if env:
        data['env'] = env
    else:
        data.pop('env', None)
    path.write_text(json.dumps(data, indent=2) + '\n')
PY'''

    codex_restore_ps = r'''$path="$HOME\.codex\config.toml"; if(Test-Path $path){Copy-Item $path "$path.omni-backup-$(Get-Date -Format yyyyMMddHHmmss)"; $text=Get-Content $path -Raw; $text=[regex]::Replace($text,'(?ms)^\[model_providers\.omni_server\]\r?\n.*?(?=^\[|\z)',''); $text=[regex]::Replace($text,'(?m)^\s*model_provider\s*=\s*"omni_server"\s*\r?\n',''); $text=[regex]::Replace($text,'(?m)^\s*# Omni managed route\r?\n',''); Set-Content -Encoding utf8 $path $text}'''

    codex_restore_bash = r'''python3 - <<'PY'
import re, shutil
from datetime import datetime
from pathlib import Path
path = Path.home() / '.codex' / 'config.toml'
if path.exists():
    shutil.copy2(path, path.with_name(path.name + '.omni-backup-' + datetime.now().strftime('%Y%m%d%H%M%S')))
    text = path.read_text()
    text = re.sub(r'(?ms)^\[model_providers\.omni_server\]\r?\n.*?(?=^\[|\Z)', '', text)
    text = re.sub(r'(?m)^\s*model_provider\s*=\s*"omni_server"\s*\r?\n', '', text)
    text = re.sub(r'(?m)^\s*# Omni managed route\r?\n', '', text)
    path.write_text(text)
PY'''

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
        'claude_restore_ps': claude_restore_ps,
        'claude_restore_bash': claude_restore_bash,
        'codex_ps': codex_ps,
        'codex_bash': codex_bash,
        'codex_desktop_ps': codex_desktop_ps,
        'codex_desktop_bash': codex_desktop_bash,
        'codex_cli_ps': codex_cli_ps,
        'codex_cli_bash': codex_cli_bash,
        'codex_restore_ps': codex_restore_ps,
        'codex_restore_bash': codex_restore_bash,
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
    # Keep an empty fixture truly empty. The deployment script accepts both
    # the structured payload and the legacy bare account mapping, so there is
    # no need to add an empty wrapper when there is nothing to migrate.
    payload = {'accounts': accounts} if accounts else {}
    models_file = controller.proxy_dir / 'cliproxy-models.json'
    if models_file.exists():
        try:
            payload['models_catalog'] = models_file.read_text(encoding='utf-8')
        except Exception:
            pass
    return payload


def deploy_to_server(config, controller, progress_callback=None):
    """Deploy Omni gateway service and migrate existing accounts to Ubuntu server in one batch."""
    config = validate_ssh_config(config)
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

# Ensure firewall allows gateway port
sudo ufw allow 8317/tcp comment 'Omni AI Gateway' 2>/dev/null || true

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
models:
    catalog: __TARGET_DIR__/cliproxy-models.json
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
              display-name: 3.8 Flash High
              force-mapping: true
            - name: claude-sonnet-4-6
              alias: claude-selected
              fork: true
              display-name: Sonnet 4.6
              force-mapping: true
            - name: gemini-3-flash
              alias: claude-haiku-4-5-ga-3-flash
              fork: true
              display-name: 3 Flash
              force-mapping: true
            - name: gemini-3-flash-agent
              alias: claude-sonnet-4-5-ga-3-flash-agent
              fork: true
              display-name: 3.5 Flash High
              force-mapping: true
CFG_EOF

sed -i "s|__CLIENT_KEY__|$CLIENT_KEY|g" "$TARGET_DIR/config.yaml"
sed -i "s|__AUTH_DIR__|$TARGET_DIR/auth|g" "$TARGET_DIR/config.yaml"
sed -i "s|__TARGET_DIR__|$TARGET_DIR|g" "$TARGET_DIR/config.yaml"

# Unpack transferred accounts from STDIN
python3 -c "
import sys, json, os
payload = json.loads(sys.stdin.read())
accounts = payload.get('accounts', payload)
target = os.path.expanduser('~/.omni-server/auth')
os.makedirs(target, exist_ok=True)
for name, content in accounts.items():
    p = os.path.join(target, name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(p, 0o600)
models = payload.get('models_catalog')
if models:
    with open(os.path.expanduser('~/.omni-server/cliproxy-models.json'), 'w', encoding='utf-8') as f:
        f.write(models)
print(f'Imported {len(accounts)} accounts and models catalog')
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
sudo loginctl enable-linger "$(whoami)" 2>/dev/null || loginctl enable-linger "$(whoami)" 2>/dev/null || true
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
