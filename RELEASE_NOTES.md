# Gemini Accounts 1.3.6 — Exclude provider-blocked quota

- The pooled 5h bar now excludes accounts with an active provider quota restriction, even when Google still reports a tiny nonzero weekly balance.
- Forecast markers follow the provider retry time and any later blocking reset, rather than showing unusable 5h quota as available.
- Claude Desktop setup now includes a dedicated Gemini 3 Flash fast slot, and Claude Code setup uses Flash for its Haiku slot. Existing users can reapply Claude setup through Connect applications with their consent, then restart Claude to refresh its menu.
- Restrictions stay within their model family: Claude limits do not reduce the Gemini total. Expired restrictions no longer block the total.

Windows: **Routing statistics → Check for updates → Update to v1.3.6**. Active requests delay installation until they finish. Saved accounts and client configurations are preserved. Versions older than 1.3.3 need the setup installer once.

Includes Windows setup and terminal builds for Windows x64, macOS Apple Silicon / Intel, and Linux x64.
