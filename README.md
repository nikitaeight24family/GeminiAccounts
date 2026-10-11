<p align="center"><img src="assets/omni-icon.png" width="72" alt="Omni logo"></p>
<h1 align="center">Omni</h1>
<p align="center">Your AI accounts, quotas and applications in one place.</p>
<p align="center">
  <a href="https://github.com/nikitaeight24family/Omni/releases/latest"><img src="https://img.shields.io/github/v/release/nikitaeight24family/Omni?label=release&color=739aff" alt="Latest release"></a>
  <a href="https://github.com/nikitaeight24family/Omni/actions/workflows/build.yml"><img src="https://github.com/nikitaeight24family/Omni/actions/workflows/build.yml/badge.svg" alt="Build and tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-66d7b0" alt="MIT license"></a>
</p>
<p align="center">
  <a href="https://github.com/nikitaeight24family/Omni/releases/latest/download/Omni-Setup.exe"><b>Download for Windows</b></a> ·
  <a href="https://github.com/nikitaeight24family/Omni/releases/latest">All downloads</a> ·
  <a href="CLI.md">Terminal guide</a> ·
  <a href="https://github.com/nikitaeight24family/Omni/issues">Report an issue</a>
</p>

Omni manages **Google Antigravity / Gemini, ChatGPT, Claude, Grok and TokenHarbor** accounts, monitors quotas and connects **Claude Code, Claude Desktop and Codex** through a local gateway. Select an account yourself or let Omni rotate available accounts using quota reset times and your priorities.

**Windows desktop** · **Windows / macOS / Linux terminal** · **English / Russian interface** · **Dark / light themes**

<p align="center"><img src="docs/omni-dashboard.png" width="1000" alt="Omni dashboard with demo accounts, subscription badges, priorities, quota limits and account details"></p>

*Screenshot uses demo accounts and sample quotas. No personal credentials are shown.*

Omni was previously named **Gemini Accounts**. The repository retains its history and releases, and legacy executable names and data folders remain compatible. For installations up to 1.4.4, download the current installer once to switch to the renamed release feed.

## Windows desktop: three steps

1. [Download Omni](https://github.com/nikitaeight24family/Omni/releases/latest/download/Omni-Setup.exe) and click **Install**. No Python or administrator access required.
2. Click the small **+ in a provider strip at the bottom** and choose account sign-in or API key. Google, ChatGPT, Claude, Grok and TokenHarbor connections have their own menus. ChatGPT sign-in opens an isolated Edge/Chrome profile for each account, so multiple accounts can be added without switching the browser's everyday account. Enter the password and 2FA code on the official sign-in page. Existing Codex `auth.json` files can still be imported from the same menu.
3. Open **Connect applications** and approve setup of installed clients. Original configs are backed up. Restarting running clients requires separate consent.

A desktop shortcut is created. Updates preserve accounts and configurations; active requests block an update. Install Claude / Codex clients separately.

## Terminal: Windows, macOS and Linux

Download the matching CLI archive from [Releases](https://github.com/nikitaeight24family/Omni/releases/latest), extract it and open a terminal in that folder. Python is included. The first run downloads a checksum-verified native service.

| Platform | Archive | Start |
| --- | --- | --- |
| Windows x64 | `GeminiAccounts-CLI-windows-x64.zip` | `.\GeminiAccounts-CLI.exe` |
| Mac with Apple Silicon | `GeminiAccounts-CLI-macos-arm64.tar.gz` | `./gemini-accounts` |
| Mac with Intel | `GeminiAccounts-CLI-macos-x64.tar.gz` | `./gemini-accounts` |
| Linux x64 | `GeminiAccounts-CLI-linux-x64.tar.gz` | `./gemini-accounts` |

Use the interactive menu for sign-in, quotas, verification, client setup and restoration. Keep it open while using clients. **Ctrl+C / Exit** stops services started by that terminal and preserves accounts. Services already running from another instance are reused and are not stopped on exit.

Mac executables are not notarized. macOS may require approval in **System Settings → Privacy & Security**. Source launch is also available. See the [terminal guide](CLI.md).

## Connections and restoration

| Client | Changes after approval |
| --- | --- |
| Claude Desktop on Windows | Local gateway preset for the **Code** tab. Choose available Gemini and Claude models in Claude's model menu. Ordinary web chats retain their own connection. |
| Claude Code CLI, all supported platforms | Gateway URL, local key, model defaults and gateway model discovery merged into `~/.claude/settings.json`. Choose an available model with `/model`. |
| Codex Desktop on Windows / Codex CLI | Responses API provider and a local model catalog in `~/.codex/config.toml`. Choose an available model in Codex. The existing Codex models stay in the catalog. |

Before any changes, the app lists affected files and asks for consent. Projects, sign-ins and session history are preserved. History is not transferred between applications. Organizational policies may prevent third-party providers. Automatic Claude Desktop setup and desktop client restarting are Windows-only; Mac terminal mode configures Claude Code CLI and Codex CLI.

**Restore:** desktop **☰ → Connect applications → Restore previous settings / reset preferences**, or terminal `./gemini-accounts restore`. After confirmation, exact original configs are restored and files that did not exist before setup are removed. Later edits to those files are replaced by their original backups. App preferences return to defaults. **Google sign-ins are kept.** Restart clients afterward.

## Features

| Area | What you can do |
| --- | --- |
| Accounts | Connect Google, ChatGPT, Claude, Grok and TokenHarbor accounts or API keys from each provider menu. Import Codex credentials, rename an account with a double-click, pause/resume with drawn icons and complete provider verification. |
| Quotas | See separate Gemini / Claude / OpenAI **5h and 1w** windows, remaining percentages and reset countdowns. Subscription badges show the reported Google AI Pro / Ultra or ChatGPT Free / Plus / Pro plan. |
| Priorities | Adjust account priorities with compact drawn arrows beside the pause control. Higher priority moves its card upward and ranks usable credentials first. Equal priorities retain automatic quota/reset ordering. |
| Quota reserves | Drag the thin marker on a per-account quota bar to set the **minimum remaining percentage**. It grows and shows a percentage while held. **70% means stop at 70% remaining**, not spend 70%. The default is **0%**. Each account, provider family and time window has its own saved boundary. |
| Compact mode | Collapse account lists or pooled quotas. Green, orange and red circles show remaining capacity with **5h / 1w inside the circle**. Counts use **8pcs**. The bottom panel stays anchored and TokenHarbor stays last. |
| Live activity | Identify active accounts with a full animated border, provider indicators and the recent model. Gemini and Claude can run on different Google accounts simultaneously. |
| Privacy | The open/closed eye beside Omni hides account names across cards, details and history using stable numbered aliases. Double-click a hidden name to set a private alias without exposing the real identity. |
| Settings | Click the **gear beside Omni** to open service visibility, **English / Russian** and **dark / light theme** settings, including from compact mode. Changes persist without restarting. |
| Window | Remember the last screen position. The drawn pin beside the settings gear keeps the window above other applications; both settings persist. |
| Reset forecasts | Expanded Google and OpenAI 5h / 1w strips show reset markers and countdowns on the pooled quota bar. |
| Refreshes | Existing cards, bars and controls update in place. Unchanged values skip redraws, and priority changes reuse cards. |
| Releases | The **GitHub icon in the expanded panel** opens the latest release. Windows can download and verify updates while waiting for active requests to finish. |
| Diagnostics | Request, error and account-switch history; local diagnostic export with lifecycle logs and a live state snapshot. |

### Account routing and recovery

Google and OpenAI have independent account pools. Manual priority is applied among available credentials; quota-exhausted or restricted accounts remain behind usable accounts. Automatic ordering favors the nearest **five-hour reset**. Weekly quota controls eligibility rather than the five-hour order. Models selected in Claude or Codex use their exact available model IDs.

Quota reserves are enforced through the local gateway's per-account model exclusions. A reached Gemini boundary excludes Gemini models; a reached Claude boundary excludes Claude / GPT-OSS; a reached OpenAI boundary excludes that ChatGPT credential. Other provider families and accounts remain available. Existing user exclusions are preserved, and Omni removes only its own exclusions when quota recovers or the boundary is lowered. Native quota resets and usage-reset credits restore eligibility after refreshed data confirms enough capacity.

The boundary uses the provider's reported quota. Configured ChatGPT reserves are refreshed before routing each generation request, independently of the desktop window. Display quotas refresh every minute and after relevant activity; an in-flight response can cross the boundary before the next measurement. A reserve is a stop condition for future requests, not an exact token budget. With a nonzero boundary and missing quota data, that family is held until quota data becomes available.

Both Google and ChatGPT can start a full unused five-hour window with a minimal request after three minutes: Gemini Flash / GPT-OSS for Google, Luna for ChatGPT. Real client usage suppresses the ping, weekly exhaustion and user reserves are respected, and retries are bounded.

Confirmed provider quota blocks queue affected requests with streaming keep-alives. Requests resume after a reset or when a new usable account joins. Cancelling the client cancels its wait; pending requests are not saved to disk. Reserve exclusions do not fabricate provider cooldowns. Forwarded HTTP 429 responses use a short client retry interval so an old Retry-After deadline does not hide recovered accounts for many minutes.

When OpenAI confirms an account is available but does not report a five-hour window, Omni uses it before accounts with timed windows. Actual provider failures, cooldowns, pauses and configured quota reserves still control eligibility. Missing windows are labelled explicitly rather than shown as invented percentages. Importing an account preserves existing cards, loaded quotas and subscription badges.

ChatGPT cards show one drawn reset button per available **usage-reset credit**, in the same header row as priority and pause. Zero credits leave no label or button. Hover reveals availability and expiry. Confirmation and a fresh availability check are required. The provider chooses the credit consumed; Omni does not automatically repeat a timed-out reset.

Quota exhaustion is shown as a quota status. Verification, invalid credentials, access restrictions and provider errors remain distinct, and unfamiliar status messages stay visible. Active borders clear on idle or quota wait; recent models remain visible for one minute. Desktop countdowns update every 15 seconds.

### Appearance and service visibility

The gear opens **Display settings**, also available as a tab in the expanded panel. Choose whether to show **Gemini, Claude, OpenAI, Grok and TokenHarbor**. Hiding a service changes its display only; it does not pause accounts or remove them from routing. Pooled Google Gemini and OpenAI sections show their own 5h / 1w totals, exclude paused accounts and identify incomplete quota data.

Omni uses its own orbit logo. Google accounts carry the Antigravity icon; ChatGPT accounts carry the OpenAI mark. Subscription badges sit beneath account names. Account selection applies only while details are open; compact mode keeps verification actions available.

### Optional TokenHarbor

Expand **TokenHarbor → + Add TokenHarbor account**, enter a Universal Key and review the connection changes. Omni tests the exact **`claude-haiku-5.5:free`** route before adding it to approved clients. No paid fallback is configured. Each key shows its latest success or error and the last-used key is marked after the gateway reports usage.

The free route is a limited-time offer and requires access on the TokenHarbor account. Published rate limits appear in its connection window. Use **Balance and reset** for live campaign allowance and expiry: TokenHarbor has no documented read API for those remaining values, so Omni does not invent them. TokenHarbor says free-route prompts and responses may be retained. **Remove TokenHarbor connection** removes the provider and client menu entry.

## Availability and storage

Google Antigravity determines account eligibility, models and quotas. A Gemini web subscription alone does not guarantee access to Claude or every model. This is an independent project, not an official Google, Anthropic or OpenAI application.

Gateway: `127.0.0.1:8317`; native service: `127.0.0.1:8318`. Both are local-only. Each installation receives random keys. Releases contain no personal sign-ins, private keys or history.

Windows uses LocalAppData, or an existing Codex LocalCache installation. macOS uses `~/Library/Application Support/GeminiAccounts`; Linux uses `$XDG_DATA_HOME/GeminiAccounts` or `~/.local/share/GeminiAccounts`. `GEMINI_ACCOUNTS_HOME` selects an explicit runtime root. Google sign-ins are in `ClaudeGemini/auth/`.

Windows protects management keys, verification state and backups with **DPAPI**. Mac / Linux encrypt these files with **Fernet** and a user-only local storage key; this is file-permission protection, not Keychain integration. Keep the storage key with the protected data. Never publish installed auth folders, keys or client configs.

## Development

Python 3.12+. Desktop: `requirements.txt`; terminal-only: `requirements-cli.txt` (no Tk or GUI dependencies).

```sh
python -m pip install -r requirements-cli.txt
python console.py --help
python -m unittest tests.test_console tests.test_accounts tests.test_activity tests.test_quota_queue tests.test_quota_starts tests.test_routing
```

Windows build: `build-release.ps1`. Terminal binary: `python -m PyInstaller --onefile --name gemini-accounts --add-data assets/cliproxy-models.json:assets --collect-all tzdata console.py` on macOS / Linux (use `;assets` on Windows). GitHub Actions builds and tests Windows, Mac Apple Silicon / Intel and Linux editions. Native CLIProxyAPI is pinned to **8.0.16**, with committed SHA-256 checksums and its license included. Client configuration interfaces may change with client updates.

Documentation: [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-advanced), [Claude Code environment variables](https://code.claude.com/docs/en/env-vars), [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI).

### Diagnostic logs

Request lifecycle logging is automatic, including active requests, quota waits, upstream attempts, streaming progress, cancellations and failures. **Routing statistics → Save diagnostic log…** exports a ZIP with rotated JSONL logs, request history and a live state snapshot. No prompts, generated text, authentication tokens or client configuration files are included. Logs contain account names. Terminal: `./gemini-accounts diagnostics --output diagnostics.zip` (Windows: `GeminiAccounts-CLI.exe diagnostics --output diagnostics.zip`). The export also works when services are offline.

Windows desktop checks GitHub for newer releases. **Routing statistics → Update to …** downloads the verified installer, waits for active requests, replaces application files and restarts services. Client configurations are not automatically rewritten. **Send diagnostic log…** requires owner confirmation for every upload, uses the configured HTTPS recipient and replaces email addresses with account labels. The default recipient is https://logs.conch-labs.com/ingest. An upload access token is required and stored encrypted locally; no token is embedded in public builds.

### Native Claude accounts

Use **+ Claude** to sign in on the official Claude website in a separate browser profile. Native Claude credentials stay in the local gateway, separately from Google accounts that also provide Claude models. The Claude panel shows the provider-reported subscription (Pro, Max 5x/20x, Team or Enterprise), remaining 5h/1w quota, reset timers, statuses and active model. Missing quota or plan data remains unknown.

Each account has inline priority arrows and quota reserve markers. Available Claude accounts rotate independently; the request queue can continue through Claude when Google is exhausted. Full untouched windows can be started after the same three-minute grace period using an available Haiku model; real usage, reserves and weekly exhaustion suppress that probe. Collapsed account and pooled headers retain quota circles. Claude visibility, privacy names, theme and language use the shared settings.

### Native desktop migration

The shipped Windows manager remains the current Python desktop application. Experimental WPF, SwiftUI and GTK clients in [`native/`](native/README.md) are development work and are not included in this release.
