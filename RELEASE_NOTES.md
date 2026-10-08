# Gemini Accounts 1.3.3 — Request diagnostics and log export

- Windows desktop checks the latest GitHub release. Click **Update to …** to download a SHA-256-verified installer, wait for current requests, replace application files and restart. New requests are temporarily blocked during replacement; connected client configurations are not automatically rewritten.
- **Send diagnostic log…** requires separate owner consent for each upload to a configured HTTPS endpoint, replaces email addresses with account labels and does not follow redirects. No endpoint is preconfigured.
- Automatic rotating file logs record requests immediately: selected and upstream models, attempts, provider cooldowns, waiting phases, time to headers / first bytes, streamed byte counts, cancellations, empty responses and completion.
- Logs include completed provider attempts, account names and failover attempts even when the next account also fails. The switch counter now includes these correlated failed attempts instead of only successful switches.
- **Routing statistics → Save diagnostic log…** exports a ZIP containing current / rotated logs, request history and a live snapshot of active requests and account restrictions. Logging continues in the gateway even when the desktop window is closed.
- Terminal export: `./gemini-accounts diagnostics --output diagnostics.zip` or `GeminiAccounts-CLI.exe diagnostics --output diagnostics.zip`. Export remains available when the services are offline.
- Structured Google error reason codes and retry delays are recorded. Generic “quota exceeded” messages no longer claim that the complete model quota has been exhausted.

Logs contain account names and technical request metadata. They exclude prompts, generated text, authentication tokens, verification links and configuration files. Logs rotate to keep disk usage bounded; export captures retained history and live state, not events from before this version was installed.

Windows: install `GeminiAccounts-Setup.exe` after current requests finish. Existing sign-ins and configuration backups are preserved. New users: **Install → Add Google account → approve Connect applications**, then restart the selected client.

Terminal: extract the CLI archive for your platform and run the included executable. Windows x64, macOS Apple Silicon / Intel and Linux x64 are supported. Mac builds are not notarized. See the [quick start](https://github.com/nikitaeight24family/GeminiAccounts#readme) and [terminal guide](https://github.com/nikitaeight24family/GeminiAccounts/blob/main/CLI.md).

This is a diagnostics update. It does not remove provider restrictions or establish that the reported Opus waiting issue is fixed. The new logs allow its actual request path and failover behavior to be checked.
