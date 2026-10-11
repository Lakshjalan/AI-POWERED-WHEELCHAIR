#!/usr/bin/env python3
"""
camera_stream.py - Raspberry Pi 5 Camera Server with Objective Detection & Vehicle Control
------------------------------------------------------------------------------------------
Runs directly on the Raspberry Pi 5.
Features:
  1. Captures from Pi Camera using Picamera2 (RGB888 / 640x480).
  2. Runs lightweight MobileNet SSD objective/obstacle detection overlaid on the video stream.
  3. Serves the stream on /video (and /video_feed for compatibility) at port 5000.
  4. Provides /control endpoint so laptop eye gaze / blink commands steer the rover.
  5. Provides /health and /telemetry endpoints for the dashboard.
"""

from flask import Flask, Response, request, jsonify
from picamera2 import Picamera2
import cv2
import numpy as np
import time
import atexit
import os
import threading
import urllib.request

app = Flask(__name__)

# ==============================
# CAMERA CONFIGURATION
# ==============================
camera = Picamera2()

config = camera.create_video_configuration(
    main={
        "size": (640, 480),
        "format": "RGB888"
    },
    controls={
        "AwbEnable": True,       # Automatic white balance
        "AeEnable": True,        # Automatic exposure
        "Brightness": 0.0,
        "Contrast": 1.0,
        "Saturation": 1.0
    },
    buffer_count=4
)

camera.configure(config)
camera.start()

# Allow automatic exposure and white balance to settle
time.sleep(2)


def cleanup():
    try:
        camera.stop()
    except Exception:
        pass


atexit.register(cleanup)

# ==============================
# OBJECTIVE DETECTION (MobileNet SSD)
# ==============================
DETECTION_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair",
    "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

_CLASS_COLORS = [
    (0,   0,   0),   (128, 0,   0),   (0,   128, 0),   (128, 128, 0),
    (0,   0,   128), (128, 0,   128), (0,   128, 128), (128, 128, 128),
    (64,  0,   0),   (0,   220, 255), (64,  128, 0),   (192, 128, 0),
    (64,  0,   128), (192, 0,   128), (64,  128, 128), (0,   255, 80),
    (192, 128, 128), (0,   64,  0),   (128, 64,  0),   (0,   192, 0),
    (128, 192, 0)
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
CAFFEMODEL_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

PROTOTXT_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/MobileNetSSD_deploy.prototxt"
CAFFEMODEL_URL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/MobileNetSSD_deploy.caffemodel"

detection_net = None

def load_detector():
    global detection_net
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        if not os.path.exists(PROTOTXT_PATH):
            urllib.request.urlretrieve(PROTOTXT_URL, PROTOTXT_PATH)
        if not os.path.exists(CAFFEMODEL_PATH):
            urllib.request.urlretrieve(CAFFEMODEL_URL, CAFFEMODEL_PATH)
        detection_net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)
        print("✅ MobileNet SSD objective detector loaded.")
    except Exception as e:
        print(f"⚠️ Objective detection offline (falling back to raw camera): {e}")

load_detector()

# ==============================
# VEHICLE STATE & SERIAL BRIDGE
# ==============================
vehicle_state = {
    "car_state": "STOP",
    "distance_cm": 95,
    "detected_objects": [],
    "last_cmd": "S"
}
state_lock = threading.Lock()
arduino_serial = None

def init_serial(port="/dev/ttyACM0", baud=115200):
    global arduino_serial
    try:
        import serial
        arduino_serial = serial.Serial(port, baud, timeout=0.1)
        print(f"✅ Connected to Arduino on {port}")
    except Exception as e:
        print(f"ℹ️ Serial Arduino not attached ({e}); running in simulated vehicle mode.")

init_serial()

def execute_drive_command(cmd_char):
    state_map = {"F": "FORWARD", "S": "STOP", "L": "TURNING LEFT", "R": "TURNING RIGHT", "B": "REVERSE"}
    with state_lock:
        vehicle_state["car_state"] = state_map.get(cmd_char.upper(), vehicle_state["car_state"])
        vehicle_state["last_cmd"] = cmd_char.upper()
    if arduino_serial and arduino_serial.is_open:
        try:
            arduino_serial.write(cmd_char.encode("utf-8"))
        except Exception:
            pass


# ==============================
# VIDEO FRAME GENERATOR
# ==============================
def generate_frames():
    while True:
        try:
            # Capture a frame from Picamera2
            frame = camera.capture_array()
            h, w = frame.shape[:2]

            labels_found = []
            # Run objective detection
            if detection_net is not None:
                try:
                    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
                    detection_net.setInput(blob)
                    detections = detection_net.forward()

                    for i in range(detections.shape[2]):
                        confidence = float(detections[0, 0, i, 2])
                        if confidence > 0.45:
                            class_idx = int(detections[0, 0, i, 1])
                            if class_idx < len(DETECTION_CLASSES):
                                label = DETECTION_CLASSES[class_idx]
                                color = _CLASS_COLORS[class_idx]

                                box = detections[0, 0, i, 3:7] * [w, h, w, h]
                                x1, y1, x2, y2 = box.astype(int)
                                x1, y1 = max(0, x1), max(0, y1)
                                x2, y2 = min(w - 1, x2), min(h - 1, y2)

                                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                                tag = f"{label} {int(confidence * 100)}%"
                                tag_y = y1 - 8 if y1 > 20 else y1 + 18
                                cv2.putText(frame, tag, (x1, tag_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
                                labels_found.append(label)
                except Exception:
                    pass

            with state_lock:
                vehicle_state["detected_objects"] = labels_found
                current_state = vehicle_state["car_state"]

            # HUD Telemetry Overlay on the Rover Camera
            cv2.putText(frame, f"ROVER FRONT CAM | {current_state}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            if labels_found:
                unique_labels = list(dict.fromkeys(labels_found))
                cv2.putText(frame, f"OBJECTIVES: {', '.join(unique_labels[:3])}", (15, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2)

            # Encode the frame as JPEG
            success, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 80]
            )

            if not success:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )

        except Exception as error:
            print(f"Camera frame error: {error}")
            time.sleep(0.1)


# ==============================
# WEBPAGE & ENDPOINTS
# ==============================
@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Raspberry Pi 5 Camera - OcuSteer Rover</title>
        <style>
            body { background: #111827; color: white; font-family: Arial, sans-serif; text-align: center; margin: 0; padding: 25px; }
            h1 { margin-bottom: 8px; }
            p { color: #9ca3af; }
            img { width: 100%; max-width: 960px; height: auto; border-radius: 10px; border: 2px solid #374151; }
            .status { margin-top: 15px; color: #34d399; }
        </style>
    </head>
    <body>
        <h1>Raspberry Pi 5 Rover Camera</h1>
        <p>Front Objective Detection & Steering Feed</p>
        <img src="/video" alt="Live camera feed">
        <div class="status">Camera stream active &bull; Objective detection ready</div>
    </body>
    </html>
    """

# Support both /video (your original) and /video_feed
@app.route("/video")
@app.route("/video_feed")
def video():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
    )

# Vehicle movement control from laptop eye tracker / dashboard
@app.route("/control", methods=["GET", "POST"])
def control():
    cmd = request.args.get("cmd") or (request.json.get("cmd") if request.is_json else None)
    if not cmd:
        return jsonify({"status": "error", "message": "Missing 'cmd' parameter"}), 400
    cmd = cmd.strip().upper()
    execute_drive_command(cmd)
    with state_lock:
        state = vehicle_state["car_state"]
    return jsonify({"status": "ok", "command": cmd, "car_state": state})

@app.route("/telemetry")
def telemetry():
    with state_lock:
        return jsonify(vehicle_state)

@app.route("/health")
def health():
    return {
        "status": "ok",
        "camera": "running",
        "detection": "enabled" if detection_net is not None else "disabled"
    }


# ==============================
# START SERVER
# ==============================
if __name__ == "__main__":
    try:
        print("🚀 Starting Raspberry Pi 5 camera & objective server...")
        print("Video endpoints: http://<PI_IP>:5000/video & http://<PI_IP>:5000/video_feed")
        print("Control endpoint: http://<PI_IP>:5000/control?cmd=[F|S|L|R|B]")
        print("Webpage:        http://<PI_IP>:5000")
        print("Health check:   http://<PI_IP>:5000/health")

        app.run(
            host="0.0.0.0",
            port=5000,
            threaded=True,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\nStopping camera server...")
    finally:
        cleanup()
