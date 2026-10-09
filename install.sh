#!/bin/sh
# PYTHON=/path/to/python3.10 ./install.sh selects a specific interpreter.
set -eu
cd "$(dirname "$0")"
if [ -n "${PYTHON:-}" ]; then
    interpreter="$PYTHON"
else
    interpreter=""
    for candidate in python3 python3.12 python3.11 python3.10; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
            interpreter="$candidate"
            break
        fi
    done
fi
if [ -z "$interpreter" ]; then
    echo 'Нужен Python 3.10 или новее. Установите python3 и повторите установку.' >&2
    exit 1
fi
exec "$interpreter" install.py "$@"
