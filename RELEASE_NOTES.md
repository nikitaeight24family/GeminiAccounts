# Gemini Accounts 1.3.2 — Provider restriction diagnostics

- Request history distinguishes temporary request rate limits, unavailable model capacity and exhausted model quota when Google's structured error identifies the cause. Unknown 429 errors stay explicitly unknown. Raw error bodies and credentials are not saved in the activity journal.
- Routing statistics show the provider restriction reason and the next reported retry countdown separately from remaining quota. A full quota bar does not mean the model is currently accepting requests.
- Removes the extra role clarification previously injected into Gemini system prompts. Original client instructions are preserved.
- Requests separately marked Gemini thought summaries when thinking is already enabled, preserving explicit visibility settings. This does not establish that the previously reported reasoning leak is fixed; provider behavior remains unverified.
- Retains empty-response recovery, cancellable quota waits, model selection, configuration backups and restoration.

**This update does not remove Google's 429 restrictions or guarantee a successful response.** If Pro is restricted, choose an available Flash model in **⚙ → Gemini** and retry. The gateway does not silently substitute a different model.

**Windows:** download `GeminiAccounts-Setup.exe`, close ongoing requests, and run the installer. Existing Google sign-ins and original client configuration backups are preserved. New users: **Install → Add Google account → approve Connect applications**, then restart the selected client.

**Terminal:** download and extract the CLI archive for your platform, run `GeminiAccounts-CLI.exe` on Windows or `./gemini-accounts` on Mac / Linux, then use the menu to sign in and approve application setup. Keep it running while using connected clients.

Includes Windows desktop installer and CLI archives for Windows x64, macOS Apple Silicon / Intel and Linux x64. Mac executables are not notarized. See the [quick start](https://github.com/nikitaeight24family/GeminiAccounts#readme) and [terminal guide](https://github.com/nikitaeight24family/GeminiAccounts/blob/main/CLI.md). Release checksums are in `SHA256SUMS.txt`.
