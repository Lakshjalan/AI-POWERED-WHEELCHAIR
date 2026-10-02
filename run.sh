#!/usr/bin/env bash
# OcuSteer Launcher for Fedora Linux
# Obsidian Vanguard System

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Free port 5000 if occupied by previous session
if command -v fuser >/dev/null 2>&1; then
    fuser -k 5000/tcp >/dev/null 2>&1 || true
fi

# Activate virtual environment and run
if [ -f ".venv/bin/python3" ]; then
    exec .venv/bin/python3 app.py "$@"
else
    exec python3 app.py "$@"
fi
