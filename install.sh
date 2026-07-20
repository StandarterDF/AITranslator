#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[1/3] Virtual environment already exists, skipping..."
fi

echo "[2/3] Installing dependencies..."
"$VENV_DIR/bin/pip" install -r requirements.txt

if [ ! -f ".env" ]; then
    echo "[3/3] Creating .env from .env.example..."
    cp .env.example .env
    echo "  - Don't forget to edit .env with your API keys!"
else
    echo "[3/3] .env already exists, skipping..."
fi

echo ""
echo "Done! Run ./start.sh to start the server."
