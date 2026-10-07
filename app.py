#!/usr/bin/env python3
"""
OcuSteer - Root Launcher
-------------------------
Automatically ensures the virtual environment is used and starts the Laptop Hub server.
"""

import os
import sys

# Ensure execution within .venv if available
current_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(current_dir, ".venv", "bin", "python3")

if os.path.exists(venv_python) and os.path.realpath(sys.executable) != os.path.realpath(venv_python):
    os.execv(venv_python, [venv_python] + sys.argv)

# Change directory to laptop_hub and launch
sys.path.insert(0, os.path.join(current_dir, "laptop_hub"))
import app

if __name__ == "__main__":
    import threading
    threading.Thread(target=app.sensor_acquisition_thread, daemon=True).start()
    threading.Thread(target=app.vision_ai_thread, daemon=True).start()

    print("=" * 65)
    print("🚀 OCUSTEER TELEMETRY & COCKPIT HUB RUNNING (Fedora Linux)")
    print("🌐 Dashboard URL : http://127.0.0.1:5000")
    print("📡 Morse Comms   : http://127.0.0.1:5000/morse")
    print("👁️ Vision AI     : Online (Webcam Eye & Blink Tracking)")
    print("⚡ Sensor Intake : Online (Temple EOG & Piezo Clench)")
    print("=" * 65)

    app.app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
