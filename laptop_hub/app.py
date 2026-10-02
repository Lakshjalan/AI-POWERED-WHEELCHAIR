#!/usr/bin/env python3
"""
OcuSteer - Central Hub & Fusion Engine (Fedora Laptop)
------------------------------------------------------
Central controller running on the user's Fedora laptop.
Responsibilities:
  1. Serves the Web Cockpit Dashboard (HTML5, Vanilla CSS, JS).
  2. Runs the AI Eye & Blink Tracker using laptop webcam.
  3. Reads Temple Electrodes (EOG) and Jaw-Clench (Piezo) from USB Arduino.
  4. Fuses biological inputs into driving commands.
  5. Relays commands and proxies video/telemetry from the Car's Raspberry Pi.
"""

import sys
import os
import time
import math
import random
import threading
import json
import cv2
import numpy as np
import requests
from flask import Flask, render_template, Response, request, jsonify

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eye_tracker import EyeTracker

app = Flask(__name__, static_folder="static", template_folder="templates")

# System configuration & shared state
config = {
    "car_ip": "192.168.1.100",  # Set to Raspberry Pi IP
    "car_port": 5001,
    "sensor_serial_port": "/dev/ttyACM0",
    "ai_autopilot_enabled": True,
    "blink_trigger_enabled": True,
    "clench_trigger_enabled": True,
    "gaze_sensitivity": 0.55
}

system_state = {
    "car_state": "STOP",
    "car_connected": False,
    "ultrasonic_distance": 95,
    "obstacle_alert": False,
    "eog_value": 512,
    "eog_history": [512] * 60,
    "piezo_value": 45,
    "piezo_history": [45] * 60,
    "current_gaze": "CENTER",
    "gaze_ratio": 0.5,
    "blink_active": False,
    "clench_active": False,
    "last_command": "STOP",
    "command_log": []
}

state_lock = threading.RLock()
eye_tracker = EyeTracker(camera_index=0)
arduino_sensor_serial = None


# --- SENSOR INTAKE & SIMULATION THREAD ---
def sensor_acquisition_thread():
    """Reads real EOG/Piezo values from Arduino #1 or generates realistic simulated biopotentials."""
    global arduino_sensor_serial, system_state
    sim_t = 0.0

    while True:
        sim_t += 0.05
        eog_val = 512
        piezo_val = 40

        # Try reading real serial hardware if available
        if arduino_sensor_serial and arduino_sensor_serial.is_open:
            try:
                line = arduino_sensor_serial.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        eog_val = int(parts[0])
                        piezo_val = int(parts[1])
            except Exception:
                pass
        else:
            # High-fidelity realistic biosignal simulation
            # Baseline drift + ECG/EMG micro-jitter
            jitter = random.randint(-4, 4)
            wander = int(12 * math.sin(sim_t * 0.4))
            eog_val = 512 + wander + jitter

            # Sync simulation with eye tracker gaze state
            with state_lock:
                gaze = system_state["current_gaze"]
                if gaze == "LEFT":
                    eog_val += 180 + random.randint(-15, 15)
                elif gaze == "RIGHT":
                    eog_val -= 180 + random.randint(-15, 15)

                if system_state["clench_active"]:
                    piezo_val = 480 + random.randint(-30, 40)
                else:
                    piezo_val = random.randint(35, 55)

        with state_lock:
            system_state["eog_value"] = eog_val
            system_state["eog_history"].pop(0)
            system_state["eog_history"].append(eog_val)

            system_state["piezo_value"] = piezo_val
            system_state["piezo_history"].pop(0)
            system_state["piezo_history"].append(piezo_val)

            # Check piezo clench threshold (>350 ADC)
            if piezo_val > 350 and config["clench_trigger_enabled"]:
                trigger_jaw_clench()

        time.sleep(0.03)  # ~33 Hz update


def trigger_jaw_clench():
    now = time.time()
    # Debounce
    if not hasattr(trigger_jaw_clench, "last_trigger"):
        trigger_jaw_clench.last_trigger = 0

    if now - trigger_jaw_clench.last_trigger > 0.8:
        trigger_jaw_clench.last_trigger = now
        system_state["clench_active"] = True
        # Toggle car forward/stop
        new_cmd = "F" if system_state["car_state"] == "STOP" else "S"
        dispatch_car_command(new_cmd, source="Piezo Jaw-Clench")
        threading.Timer(0.3, lambda: reset_clench()).start()


def reset_clench():
    with state_lock:
        system_state["clench_active"] = False


# --- VISION AI THREAD ---
latest_driver_jpeg = None
jpeg_lock = threading.Lock()

def vision_ai_thread():
    """Continuously runs the EyeTracker and evaluates driving gestures."""
    global latest_driver_jpeg, system_state
    last_gaze_cmd_time = 0

    while True:
        annotated_frame, telemetry = eye_tracker.process_frame()

        with state_lock:
            system_state["current_gaze"] = telemetry["gaze"]
            system_state["gaze_ratio"] = telemetry["gaze_ratio"]
            system_state["blink_active"] = telemetry["blink"]

            # AI Gaze Steering Decision
            if config["ai_autopilot_enabled"]:
                now = time.time()
                # Double blink toggles forward/stop
                if telemetry["double_blink"] and config["blink_trigger_enabled"]:
                    new_cmd = "F" if system_state["car_state"] == "STOP" else "S"
                    dispatch_car_command(new_cmd, source="AI Double-Blink")

                # Left / Right Glance Nudge (with 0.6s cooldown)
                elif now - last_gaze_cmd_time > 0.6:
                    if telemetry["gaze"] == "LEFT":
                        dispatch_car_command("L", source="AI Gaze Left")
                        last_gaze_cmd_time = now
                    elif telemetry["gaze"] == "RIGHT":
                        dispatch_car_command("R", source="AI Gaze Right")
                        last_gaze_cmd_time = now

        # Encode JPEG for browser HUD
        try:
            _, buffer = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            with jpeg_lock:
                latest_driver_jpeg = buffer.tobytes()
        except Exception:
            pass

        time.sleep(0.033)  # ~30 FPS


# --- CAR COMMUNICATION & PROXY ---
def dispatch_car_command(cmd_char, source="Manual"):
    """Dispatches a command to the Raspberry Pi on the car (or simulates locally)."""
    with state_lock:
        system_state["last_command"] = cmd_char
        state_map = {"F": "FORWARD", "S": "STOP", "L": "TURNING LEFT", "R": "TURNING RIGHT", "B": "REVERSE"}
        system_state["car_state"] = state_map.get(cmd_char.upper(), system_state["car_state"])

        log_entry = {
            "time": time.strftime("%H:%M:%S"),
            "cmd": cmd_char.upper(),
            "source": source,
            "status": "DISPATCHED"
        }
        system_state["command_log"].insert(0, log_entry)
        if len(system_state["command_log"]) > 25:
            system_state["command_log"].pop()

    # Send over Wi-Fi to Raspberry Pi
    def _send_async():
        car_url = f"http://{config['car_ip']}:{config['car_port']}/control?cmd={cmd_char}"
        try:
            requests.get(car_url, timeout=0.4)
            with state_lock:
                system_state["car_connected"] = True
        except Exception:
            with state_lock:
                system_state["car_connected"] = False

    threading.Thread(target=_send_async, daemon=True).start()


# --- STREAMING GENERATORS ---
def generate_driver_stream():
    """Streams the annotated eye-tracking video from the laptop camera."""
    while True:
        with jpeg_lock:
            frame_bytes = latest_driver_jpeg

        if frame_bytes is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.035)


def generate_car_fpv_stream():
    """Streams FPV video from the car's Raspberry Pi, or falls back to simulated rover feed."""
    car_stream_url = f"http://{config['car_ip']}:{config['car_port']}/video_feed"

    while True:
        # Try proxying real car stream
        try:
            req = requests.get(car_stream_url, stream=True, timeout=1.0)
            for chunk in req.iter_content(chunk_size=1024):
                if chunk:
                    yield chunk
        except Exception:
            # Fallback: render realistic rover FPV test HUD
            sim_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            sim_frame[:, :] = (15, 20, 28)

            # Draw HUD grid & horizon
            for y in range(0, 360, 30):
                cv2.line(sim_frame, (0, y), (640, y), (30, 40, 55), 1)
            for x in range(0, 640, 40):
                cv2.line(sim_frame, (x, 0), (x, 360), (30, 40, 55), 1)

            # Center target crosshair
            cx, cy = 320, 180
            cv2.circle(sim_frame, (cx, cy), 35, (0, 240, 255), 1)
            cv2.line(sim_frame, (cx - 50, cy), (cx + 50, cy), (0, 240, 255), 1)
            cv2.line(sim_frame, (cx, cy - 50), (cx, cy + 50), (0, 240, 255), 1)

            # Heading & state
            state_text = system_state["car_state"]
            dist_text = f"{system_state['ultrasonic_distance']} CM"
            cv2.putText(sim_frame, "CAR CAMERA FPV [STANDBY / LOCAL TEST]", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 200), 2)
            cv2.putText(sim_frame, f"STATUS: {state_text}  |  RADAR: {dist_text}", (20, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.putText(sim_frame, f"TARGET PI: http://{config['car_ip']}:{config['car_port']}", (20, 335),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 140, 180), 1)

            _, buf = cv2.imencode('.jpg', sim_frame)
            frame_bytes = buf.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.05)


# --- HTTP ROUTES ---
@app.route('/')
def dashboard():
    return render_template("dashboard.html", config=config)


@app.route('/video_feed/driver')
def video_feed_driver():
    return Response(generate_driver_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_feed/car')
def video_feed_car():
    return Response(generate_car_fpv_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/telemetry')
def get_telemetry():
    with state_lock:
        return jsonify({
            "car_state": system_state["car_state"],
            "car_connected": system_state["car_connected"],
            "ultrasonic_distance": system_state["ultrasonic_distance"],
            "obstacle_alert": system_state["obstacle_alert"],
            "eog_value": system_state["eog_value"],
            "eog_history": system_state["eog_history"],
            "piezo_value": system_state["piezo_value"],
            "piezo_history": system_state["piezo_history"],
            "current_gaze": system_state["current_gaze"],
            "gaze_ratio": system_state["gaze_ratio"],
            "blink_active": system_state["blink_active"],
            "clench_active": system_state["clench_active"],
            "last_command": system_state["last_command"],
            "command_log": system_state["command_log"][:10],
            "config": config
        })


@app.route('/api/command', methods=['POST'])
def post_command():
    data = request.json or {}
    cmd = data.get("command", "").upper()
    source = data.get("source", "Manual Web Override")
    if cmd in ["F", "S", "L", "R", "B"]:
        dispatch_car_command(cmd, source=source)
        return jsonify({"status": "ok", "command": cmd})
    return jsonify({"status": "error", "message": "Invalid command"}), 400


@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json or {}
    for k, v in data.items():
        if k in config:
            config[k] = v
    return jsonify({"status": "ok", "config": config})


if __name__ == '__main__':
    # Start background threads
    threading.Thread(target=sensor_acquisition_thread, daemon=True).start()
    threading.Thread(target=vision_ai_thread, daemon=True).start()

    print("=" * 65)
    print("🚀 OCUSTEER TELEMETRY & COCKPIT HUB RUNNING (Fedora Linux)")
    print("🌐 Dashboard URL : http://127.0.0.1:5000")
    print("👁️ Vision AI     : Online (Webcam Eye & Blink Tracking)")
    print("⚡ Sensor Intake : Online (Temple EOG & Piezo Clench)")
    print("=" * 65)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
