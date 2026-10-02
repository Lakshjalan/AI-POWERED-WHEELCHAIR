#!/usr/bin/env python3
"""
OcuSteer - Raspberry Pi Onboard Car Agent & Video Server
--------------------------------------------------------
Runs on the Raspberry Pi mounted to the car chassis.
Key Responsibilities:
  1. Streams live camera feed (Pi Camera or USB Cam) over HTTP MJPEG at port 5001.
  2. Bridges Wi-Fi driving commands from the Fedora laptop to the onboard Arduino Uno over Serial.
  3. Relays ultrasonic obstacle telemetry back to the laptop telemetry dashboard.

Usage on Raspberry Pi:
    python3 pi_car_server.py [--port 5001] [--serial /dev/ttyACM0]
"""

import argparse
import sys
import time
import threading
import json
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

# State variables
current_telemetry = {
    "distance_cm": 999,
    "car_state": "STOP",
    "obstacle_active": False,
    "last_updated": time.time()
}

arduino_serial = None
serial_lock = threading.Lock()
camera_device = None


def open_serial(port_name, baud=115200):
    global arduino_serial
    try:
        import serial
        arduino_serial = serial.Serial(port_name, baud, timeout=0.1)
        time.sleep(2)  # Wait for Arduino DTR reset
        print(f"✅ Connected to Car Arduino on {port_name} at {baud} baud.")
        
        # Start background reader thread
        threading.Thread(target=serial_reader_thread, daemon=True).start()
    except Exception as e:
        print(f"⚠️ Could not open serial port {port_name}: {e}")
        print("Running in simulated car serial mode.")


def serial_reader_thread():
    global current_telemetry
    while True:
        try:
            if arduino_serial and arduino_serial.is_open:
                line = arduino_serial.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("TELEMETRY,"):
                    parts = line.split(",")
                    if len(parts) >= 4:
                        with serial_lock:
                            current_telemetry["distance_cm"] = int(parts[1])
                            state_code = int(parts[2])
                            state_map = {0: "STOP", 1: "FORWARD", 2: "REVERSE", 3: "LEFT", 4: "RIGHT"}
                            current_telemetry["car_state"] = state_map.get(state_code, "UNKNOWN")
                            current_telemetry["obstacle_active"] = (parts[3] == "1")
                            current_telemetry["last_updated"] = time.time()
            time.sleep(0.02)
        except Exception:
            time.sleep(0.5)


def send_car_command(cmd_char):
    with serial_lock:
        if arduino_serial and arduino_serial.is_open:
            try:
                arduino_serial.write(cmd_char.encode('utf-8'))
                return True
            except Exception as e:
                print(f"Serial write error: {e}")
                return False
        else:
            # Simulated response
            state_map = {'F': "FORWARD", 'S': "STOP", 'L': "LEFT", 'R': "RIGHT", 'B': "REVERSE"}
            current_telemetry["car_state"] = state_map.get(cmd_char.upper(), "UNKNOWN")
            return True


def generate_frames():
    """Generates MJPEG video frames from camera, with synthetic fallback."""
    # Attempt OpenCV camera
    cap = None
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            cap = None
    except Exception:
        cap = None

    frame_counter = 0
    while True:
        frame_counter += 1
        jpeg_bytes = None

        if cap is not None and cap.isOpened():
            success, frame = cap.read()
            if success:
                import cv2
                # Overlay timestamp and telemetry banner
                h, w, _ = frame.shape
                cv2.putText(frame, f"OCUSTEER ROVER FPV | {current_telemetry['car_state']}",
                            (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(frame, f"DIST: {current_telemetry['distance_cm']} cm",
                            (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 255) if current_telemetry['obstacle_active'] else (0, 255, 0), 2)
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                jpeg_bytes = buffer.tobytes()

        if jpeg_bytes is None:
            # Generate synthetic test pattern if camera is absent
            try:
                import cv2
                import numpy as np
                synthetic = np.zeros((360, 640, 3), dtype=np.uint8)
                synthetic[:, :] = (20, 24, 30)  # Dark cyber background

                # Grid lines
                for y in range(0, 360, 40):
                    cv2.line(synthetic, (0, y), (640, y), (40, 48, 60), 1)
                for x in range(0, 640, 40):
                    cv2.line(synthetic, (x, 0), (x, 360), (40, 48, 60), 1)

                # Crosshair
                cv2.circle(synthetic, (320, 180), 45, (0, 230, 255), 1)
                cv2.line(synthetic, (320, 120), (320, 240), (0, 230, 255), 1)
                cv2.line(synthetic, (260, 180), (380, 180), (0, 230, 255), 1)

                cv2.putText(synthetic, "OCUSTEER ROVER FPV FEED [ONLINE]", (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
                cv2.putText(synthetic, f"STATE: {current_telemetry['car_state']} | DIST: {current_telemetry['distance_cm']} cm",
                            (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.putText(synthetic, f"FRAME: {frame_counter}", (20, 330),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 120, 140), 1)

                _, buffer = cv2.imencode('.jpg', synthetic)
                jpeg_bytes = buffer.tobytes()
            except Exception:
                time.sleep(0.1)
                continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
        time.sleep(0.04)  # ~25 FPS


@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/control', methods=['GET', 'POST'])
def control():
    cmd = request.args.get('cmd') or (request.json.get('cmd') if request.is_json else None)
    if not cmd:
        return jsonify({"status": "error", "message": "Missing 'cmd' parameter"}), 400

    cmd = cmd.strip()
    success = send_car_command(cmd)
    return jsonify({
        "status": "ok" if success else "error",
        "command": cmd,
        "car_state": current_telemetry["car_state"]
    })


@app.route('/telemetry')
def telemetry():
    return jsonify(current_telemetry)


@app.route('/')
def index():
    return jsonify({
        "service": "OcuSteer Pi Car Server",
        "status": "online",
        "video_feed": "/video_feed",
        "telemetry": "/telemetry",
        "control": "/control?cmd=[F|S|L|R|B]"
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="OcuSteer Car Server")
    parser.add_argument("--port", type=int, default=5001, help="HTTP Server Port")
    parser.add_argument("--serial", type=str, default="/dev/ttyACM0", help="Car Arduino Serial Port")
    args = parser.parse_args()

    open_serial(args.serial)
    print(f"🚀 OcuSteer Car Server running at http://0.0.0.0:{args.port}")
    app.run(host="0.0.0.0", port=args.port, threaded=True)
