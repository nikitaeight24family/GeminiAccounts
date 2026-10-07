# Terminal guide

## Standalone release

Download and extract the CLI archive matching your OS and CPU from [Releases](https://github.com/nikitaeight24family/GeminiAccounts/releases/latest).

Mac / Linux: `./gemini-accounts`. Windows PowerShell: `.\GeminiAccounts-CLI.exe`.

Use the numbered menu to add a Google account, inspect quotas and approve client setup. Keep the menu running while working. The first run downloads the matching native gateway and verifies its pinned checksum. A browser is required for sign-in and Google verification.

## Commands

On Windows, replace `./gemini-accounts` with `.\GeminiAccounts-CLI.exe`. From source, replace it with `python console.py`.

```sh
# Browser sign-in
./gemini-accounts login

# Accounts, four quota values, reset times and last models
./gemini-accounts status

# List the actual available model IDs; menu item 6 selects interactively
./gemini-accounts models

# Set Pro High for the default slot and Flash for the fast slot
./gemini-accounts models --default gemini-pro-agent --fast gemini-3-flash

# Configure clients with an approval prompt
./gemini-accounts configure --clients claude_cli codex

# Gateway and quota monitoring; leave running in one terminal
./gemini-accounts serve
```

Run clients in a second terminal: `claude`, `claude --resume`, `codex` or `codex resume`. **Ctrl+C** stops only service processes started by this invocation. It preserves sign-ins and session history; active requests through those services end when they stop.

```sh
# Check verification after completing Google's browser page
./gemini-accounts verify "you@example.com"

# Request and open a fresh verification link
./gemini-accounts verify "you@example.com" --refresh-link

# Use one account, or return to automatic selection
./gemini-accounts use "you@example.com"
./gemini-accounts use all

# Restore exact original client configs and default app preferences
./gemini-accounts restore
```

`configure --yes` and `restore --yes` explicitly approve changes for scripts. Without `--yes`, typing anything except `yes` cancels. Restore works with the service offline, preserves Google sign-ins and warns that later config edits will be replaced by the original backups.

One-shot commands start missing services in the background so clients can connect afterward. For monitoring, automatic priority updates and delayed quota-start pings, keep the menu or `serve` running. Native failover remains available without the monitor. Terminal mode on Windows shares an existing desktop installation's account store and reuses running services.

## Source launch

Install Python **3.12 or newer**, download and extract the source archive. Launchers create a local virtual environment and install only terminal dependencies.

Mac / Linux:

```sh
sh run.sh
# Or:
sh run.sh serve
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Manual alternative:

```sh
python -m pip install -r requirements-cli.txt
python console.py
```

No administrator access needed. The first run needs internet access to download CLIProxyAPI. Runtime data is separate from the extracted source.

## Storage and troubleshooting

- Mac: `~/Library/Application Support/GeminiAccounts/`.
- Linux: `$XDG_DATA_HOME/GeminiAccounts/` or `~/.local/share/GeminiAccounts/`.
- Windows: LocalAppData or an existing Codex LocalCache installation.
- `GEMINI_ACCOUNTS_HOME` overrides the root. Set it consistently for all commands.
- `ClaudeGemini/auth/` stores Google sign-ins. `GeminiAccounts/` stores preferences, protected backups and logs.
- Terminal-started service logs: `GeminiAccounts/native.log` and `GeminiAccounts/queue.log`.
- Ports **8317** and **8318** must be free or used by the same authenticated installation. The app refuses to replace an unrelated service.
- Authentication errors are not quota waits. Complete verification or sign in again as instructed.
- Windows uses DPAPI. Mac / Linux use encrypted files and a user-only `storage-key`; keep that key with your protected data. This version does not integrate with macOS Keychain.
- Mac executables are not notarized. Approve the download in **System Settings → Privacy & Security** if blocked, or use source mode.

Automatic Claude Desktop setup and desktop client restarting are Windows-only. Mac terminal mode supports Claude Code CLI and Codex CLI. Install clients separately. Google determines model availability; this application cannot create extra quota or bypass verification.
