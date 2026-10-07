# Gemini Accounts 1.1.0 — English + terminal editions

The desktop interface, installer, messages and documentation are fully in English. Existing accounts and backups are preserved.

**Windows desktop:** download `GeminiAccounts-Setup.exe` → **Install** → **Add Google account** → approve **Connect applications**.

**Terminal:** download the CLI archive for Windows x64, Mac Apple Silicon / Intel, or Linux x64 → extract → run `GeminiAccounts-CLI.exe` on Windows or `./gemini-accounts` on Mac / Linux. Python is included. First launch downloads a checksum-verified native service. Use the menu to sign in and approve setup; keep it open while working.

Includes account and pooled 5h / 1w quotas, forecasts, reset countdowns, independent Gemini / Claude subscriptions, last requested models, verification controls, native failover and streaming quota waits.

Setup always requires consent. Desktop **Restore previous settings / reset preferences** or terminal `restore` returns original client configs and preserves Google sign-ins. Later config edits are replaced by the backup after confirmation.

Windows supports Claude Desktop Code, Claude Code CLI and Codex Desktop / CLI. Mac terminal mode supports Claude Code CLI and Codex CLI. Mac executables are not notarized; macOS may require approval in Privacy & Security. Source mode is also available.

See the English [quick start](https://github.com/nikitaeight24family/GeminiAccounts#readme) and [terminal guide](https://github.com/nikitaeight24family/GeminiAccounts/blob/main/CLI.md). Google Antigravity determines eligibility, models and quotas. Clients are installed separately. `SHA256SUMS.txt` lists release checksums.
