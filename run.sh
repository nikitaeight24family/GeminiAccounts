#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ]; then
    runtime=""
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
            runtime="$candidate"
            break
        fi
    done
    if [ -z "$runtime" ]; then
        echo 'Python 3.12 or newer is required for the source version. Use a standalone release or install Python from https://www.python.org/downloads/.' >&2
        exit 1
    fi
    "$runtime" -m venv .venv
fi
stamp=$(.venv/bin/python -c 'import hashlib; print(hashlib.sha256(open("requirements-cli.txt", "rb").read()).hexdigest())')
if [ ! -f .venv/requirements.stamp ] || [ "$(cat .venv/requirements.stamp)" != "$stamp" ]; then
    .venv/bin/python -m pip install -r requirements-cli.txt
    printf '%s' "$stamp" > .venv/requirements.stamp
fi
exec .venv/bin/python console.py "$@"
