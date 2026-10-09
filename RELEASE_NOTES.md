# Gemini Accounts 1.3.5 — Accurate quota recovery forecasts

- The 5h forecast now waits for the weekly reset when an account has no weekly quota. This also covers full or partly remaining 5h buckets and 5h resets that have already passed.
- Unusable 5h quota on weekly-exhausted accounts is excluded from the available pooled total. If both windows block use, recovery is shown at the later reset.
- Retains Desktop SDK compatibility, account removal and one-click updates from 1.3.4.

Windows users on 1.3.3 or newer: open **Routing statistics → Check for updates → Update to v1.3.5**. The updater waits for active requests before installing and restarting. Older installations need the setup file once to gain the updater. Saved accounts and client settings are preserved.

Terminal archives are available for Windows x64, macOS Apple Silicon / Intel and Linux x64.
