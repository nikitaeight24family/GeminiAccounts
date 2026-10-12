# Omni 1.5.0 — Account highlights and safer ChatGPT imports

- Fixed missing Gemini highlights when fast responses finish between queue polls. Successful responses remain highlighted for 60 seconds after completion, including long responses.
- Preserve provider badges and recent model captions after a response completes. Quota waits, failures and background checks do not activate highlights.
- Reject ChatGPT imports that share a session with local Codex or duplicate a session already connected to Omni, including old copies of renewed tokens. Separate ChatGPT sign-ins remain supported.

Existing revoked CLI sessions require a new sign-in through Omni. This protection does not restore revoked tokens or establish why OpenAI revoked an earlier session.

Includes Windows installers and terminal builds for Windows x64, macOS Apple Silicon / Intel, and Linux x64.

## Previous release: Omni 1.4.9 — TokenHarbor model menu and quota recovery

- Fixed TokenHarbor Claude Haiku 5.5 Free missing from Claude Desktop's Code menu when the key is connected after application setup, including ChatGPT-only profiles.
- Existing approved Omni profiles automatically restore a missing TokenHarbor menu entry while preserving their selected model. Restart Claude Desktop after updating to reload its model menu.
- Fixed stale local ChatGPT quota blocks after a confirmed limit reset and resumed waiting requests when a full reset is detected.
- Show each account's quota as soon as it responds, without waiting for slower account checks, and retain known subscription names while quota loads.

Includes Windows installers and terminal builds for Windows x64, macOS Apple Silicon / Intel, and Linux x64.

## Previous release notes: Gemini Accounts 1.3.7 — Flash reasoning levels

- Added Antigravity Flash High, Medium and Low as distinct upstream models, including Google's Gemini 3.5 Flash IDs.
- Claude Code discovers gateway models, Claude Desktop lists the available variants, and Codex receives an extended catalog while preserving its existing model choices.
- Connected client settings are updated only with owner consent and can be restored. Restart the clients after updating their settings.

Windows: **Routing statistics → Check for updates → Update to v1.3.7**. Active requests delay installation until they finish. Terminal users can download the matching archive.

## Previous release: 1.3.6

- The pooled 5h bar now excludes accounts with an active provider quota restriction, even when Google still reports a tiny nonzero weekly balance.
- Forecast markers follow the provider retry time and any later blocking reset, rather than showing unusable 5h quota as available.
- Claude Desktop setup now includes a dedicated Gemini 3 Flash fast slot, and Claude Code setup uses Flash for its Haiku slot. Existing users can reapply Claude setup through Connect applications with their consent, then restart Claude to refresh its menu.
- Restrictions stay within their model family: Claude limits do not reduce the Gemini total. Expired restrictions no longer block the total.

Windows: **Routing statistics → Check for updates → Update to v1.3.6**. Active requests delay installation until they finish. Saved accounts and client configurations are preserved. Versions older than 1.3.3 need the setup installer once.

Includes Windows setup and terminal builds for Windows x64, macOS Apple Silicon / Intel, and Linux x64.
