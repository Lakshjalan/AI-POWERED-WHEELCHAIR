#!/usr/bin/env python3
import os
import sys

# Hand-off to app.py
current_dir = os.path.dirname(os.path.abspath(__file__))
app_file = os.path.join(current_dir, "app.py")
os.execv(sys.executable, [sys.executable, app_file] + sys.argv[1:])
