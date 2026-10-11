# Verification before publishing

The user requires local verification before every GitHub push. Run the complete test suite (`python -m unittest discover -s tests`) and build the affected executable locally. Resolve failures before committing and pushing. After any new changes, repeat the affected checks and complete suite against the final changes before pushing. CI is an additional check, not a substitute for local testing. Publish releases only after all platform jobs succeed.

The product display name is Omni. Existing GeminiAccounts / ClaudeGemini data locations, executable names and managed configuration markers remain compatibility identifiers. Releases keep the legacy installer asset alongside Omni-Setup.exe so installed older versions can update.
