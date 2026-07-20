#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Run ./install.sh first." >&2
    exit 1
fi

exec "$VENV_DIR/bin/python" main.py "$@"
