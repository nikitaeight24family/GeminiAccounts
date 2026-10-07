# Gemini Accounts 1.2.0 — Model selection and compact weekly countdowns

Choose any available text model using **⚙ next to Gemini Accounts**: Pro Low / High, Flash, Flash Lite, Sonnet, Opus or GPT-OSS. Default / Sonnet and Fast / Haiku slots are independent. Changes apply to new gateway requests without restarting clients. Updating Codex's explicit default is optional, asks consent and requires restarting Codex. Availability follows your account catalog.

Weekly **1w** countdowns now show days only, including markers inside the pooled quota bar. Less than one day is shown as `< 1d`. Five-hour countdowns retain hours and minutes.

The gateway refreshes model mappings while waiting for quota. Request history keeps the original model after a selection change. Terminal mode includes a **Models** menu and the `models --default MODEL_ID --fast MODEL_ID` command.

The desktop interface, installer, messages and documentation are fully in English. Existing accounts and backups are preserved.

**Windows desktop:** download `GeminiAccounts-Setup.exe` → **Install** → **Add Google account** → approve **Connect applications**.

**Terminal:** download the CLI archive for Windows x64, Mac Apple Silicon / Intel, or Linux x64 → extract → run `GeminiAccounts-CLI.exe` on Windows or `./gemini-accounts` on Mac / Linux. Python is included. First launch downloads a checksum-verified native service. Use the menu to sign in and approve setup; keep it open while working.

Includes account and pooled 5h / 1w quotas, forecasts, reset countdowns, independent Gemini / Claude subscriptions, last requested models, verification controls, native failover and streaming quota waits.

Setup always requires consent. Desktop **Restore previous settings / reset preferences** or terminal `restore` returns original client configs and preserves Google sign-ins. Later config edits are replaced by the backup after confirmation.

Windows supports Claude Desktop Code, Claude Code CLI and Codex Desktop / CLI. Mac terminal mode supports Claude Code CLI and Codex CLI. Mac executables are not notarized; macOS may require approval in Privacy & Security. Source mode is also available.

See the English [quick start](https://github.com/nikitaeight24family/GeminiAccounts#readme) and [terminal guide](https://github.com/nikitaeight24family/GeminiAccounts/blob/main/CLI.md). Google Antigravity determines eligibility, models and quotas. Clients are installed separately. `SHA256SUMS.txt` lists release checksums.

### Compact desktop panel

Demo accounts and example quota values; no personal account addresses.

<img src="https://raw.githubusercontent.com/nikitaeight24family/GeminiAccounts/v1.2.0/docs/compact-panel.png" alt="Compact Gemini Accounts panel" width="320">
