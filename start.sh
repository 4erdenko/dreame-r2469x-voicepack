#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Install Python 3.11+ from https://www.python.org/downloads/'
    exit 1
fi
exec python3 voicepack.py "$@"
