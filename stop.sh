#!/usr/bin/env bash
# OcuSteer Graceful Termination Script

echo "🛑 Stopping OcuSteer Hub Server..."

# Kill any process listening on port 5000
if command -v fuser >/dev/null 2>&1; then
    fuser -k 5000/tcp >/dev/null 2>&1 || true
fi

# Kill any background python process running the hub
pkill -f "laptop_hub/app.py" >/dev/null 2>&1 || true
pkill -f "app.py" >/dev/null 2>&1 || true

echo "✅ Server terminated and Port 5000 is freed."
