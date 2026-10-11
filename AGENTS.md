# Verification before publishing

The user requires local verification before every GitHub push. Run the complete test suite (`python -m unittest discover -s tests`) and build the affected executable locally. Resolve failures before committing and pushing. After any new changes, repeat the affected checks and complete suite against the final changes before pushing. CI is an additional check, not a substitute for local testing. Publish releases only after all platform jobs succeed.
