# Gemini Accounts 1.3.4 — Gateway retry handling and authenticated log uploads

- Removes the standalone Claude Agent SDK identity line from Anthropic system instructions before forwarding generation and token-count requests. User messages, tools and all other instructions are preserved. Both streaming and nonstreaming paths are covered by protocol tests; the affected remote installation has not yet been retested.
- Adds **Remove account** in account details, with confirmation. Deletes the saved credential and its local labels / verification state without deleting the Google account or enabling other paused accounts.
- Removes the exact experimental thought-summary override introduced in 1.3.2�1.3.3; custom payload settings remain intact.
- The gateway now keeps HTTP 429 retries local even when account cooldown metadata is missing or no longer matches the rejection. It sends keepalives, respects numeric Retry-After and otherwise uses increasing retry delays instead of exposing 429 to Claude's own retry loop. Authentication / verification failures still surface as errors.
- Claude token-count requests normalize the extended-context suffix before forwarding. Diagnostics record their route, original model, forwarded model and HTTP status as well as generation requests. This closes a diagnostics gap; it does not prove that the reported “model not found” error has been resolved.
- Nonstream response body byte counts are recorded correctly.
- **Send diagnostic log…** uses `https://logs.conch-labs.com/ingest`, POST `application/zip`, bearer authorization and `X-Filename: logs.zip`. A server connectivity test accepted a synthetic archive with HTTP 201. Upload credentials are stored encrypted per installation and are never included in published sources or diagnostic ZIPs. Enter an upload credential once when prompted; every upload still requires owner confirmation.
- Retains file log export and verified one-click Windows updates from 1.3.3. Install this version manually when upgrading from a version older than 1.3.3; later Windows updates can use **Routing statistics → Update to …**.

Google model availability and account restrictions remain outside the gateway's control. Waiting is cancellable; no assistant answers or tool calls are fabricated. This release does not claim to fix the underlying Google restriction or the unconfirmed model routing issue.

Windows: run `GeminiAccounts-Setup.exe` after current requests finish. Existing Google sign-ins and configuration backups are preserved. Terminal archives cover Windows x64, macOS Apple Silicon / Intel and Linux x64. See the [quick start](https://github.com/nikitaeight24family/GeminiAccounts#readme) and [terminal guide](https://github.com/nikitaeight24family/GeminiAccounts/blob/main/CLI.md).
