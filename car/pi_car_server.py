#!/usr/bin/env python3
"""
OcuSteer - Raspberry Pi Onboard Car Agent & Video Server
--------------------------------------------------------
Runs on the Raspberry Pi mounted to the car chassis.
Key Responsibilities:
  1. Streams live camera feed (Pi Camera Module or USB Cam) over HTTP MJPEG at port 5001.
     - Tries picamera2 (Pi Camera Module via ribbon connector) first.
     - Falls back to OpenCV VideoCapture(0) for USB webcams.
  2. Overlays lightweight MobileNet SSD object detection on the FPV stream
     so the cockpit dashboard shows detected objectives in front of the rover.
  3. Bridges Wi-Fi driving commands from the Fedora laptop to the onboard Arduino Uno over Serial.
  4. Relays ultrasonic obstacle telemetry back to the laptop telemetry dashboard.

Usage on Raspberry Pi:
    python3 pi_car_server.py [--port 5001] [--serial /dev/ttyACM0] [--no-detection]

Model files (auto-downloaded on first run if absent):
    car/models/MobileNetSSD_deploy.prototxt
    car/models/MobileNetSSD_deploy.caffemodel
"""

import argparse
import sys
import os
import time
import threading
import json
import urllib.request
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

# ──────────────────────────────────────────────────────────
#  State variables
# ──────────────────────────────────────────────────────────
current_telemetry = {
    "distance_cm": 999,
    "car_state": "STOP",
    "obstacle_active": False,
    "last_updated": time.time(),
    "detected_objects": []   # NEW: list of object labels visible in camera
}

arduino_serial = None
serial_lock = threading.Lock()
enable_detection = True   # Can be disabled via --no-detection flag

# ──────────────────────────────────────────────────────────
#  MobileNet SSD — 20 PASCAL-VOC classes
# ──────────────────────────────────────────────────────────
DETECTION_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair",
    "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

# Colour map per class (BGR)
_CLASS_COLORS = [
    (0,   0,   0),   # background
    (128, 0,   0),   # aeroplane
    (0,   128, 0),   # bicycle
    (128, 128, 0),   # bird
    (0,   0,   128), # boat
    (128, 0,   128), # bottle
    (0,   128, 128), # bus
    (128, 128, 128), # car
    (64,  0,   0),   # cat
    (0,   220, 255), # chair   — cyan (most common indoor obstacle)
    (64,  128, 0),   # cow
    (192, 128, 0),   # diningtable
    (64,  0,   128), # dog
    (192, 0,   128), # horse
    (64,  128, 128), # motorbike
    (0,   255, 80),  # person  — bright green
    (192, 128, 128), # pottedplant
    (0,   64,  0),   # sheep
    (128, 64,  0),   # sofa
    (0,   192, 0),   # train
    (128, 192, 0),   # tvmonitor
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
CAFFEMODEL_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

PROTOTXT_URL = (
    "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/"
    "MobileNetSSD_deploy.prototxt"
)
CAFFEMODEL_URL = (
    "https://github.com/chuanqi305/MobileNet-SSD/raw/master/"
    "MobileNetSSD_deploy.caffemodel"
)

_detection_net = None   # Loaded once; shared across frames


def _ensure_model_dir():
    os.makedirs(MODEL_DIR, exist_ok=True)


def _download_if_missing(url, dest):
    if not os.path.exists(dest):
        print(f"📥 Downloading {os.path.basename(dest)} …")
        try:
            urllib.request.urlretrieve(url, dest)
            print(f"   ✅ Saved to {dest}")
        except Exception as exc:
            print(f"   ⚠️  Download failed: {exc}")
            return False
    return True


def load_detection_model():
    """Loads MobileNet SSD model. Downloads weights if missing. Returns net or None."""
    global _detection_net
    if _detection_net is not None:
        return _detection_net

    try:
        import cv2
        _ensure_model_dir()
        ok_proto = _download_if_missing(PROTOTXT_URL, PROTOTXT_PATH)
        ok_model = _download_if_missing(CAFFEMODEL_URL, CAFFEMODEL_PATH)

        if ok_proto and ok_model:
            net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)
            _detection_net = net
            print("✅ MobileNet SSD object detection model loaded.")
            return net
        else:
            print("⚠️  Object detection model unavailable — running without detection.")
            return None
    except Exception as exc:
        print(f"⚠️  Could not load detection model: {exc}")
        return None


def run_detection(frame, net, confidence_threshold=0.45):
    """
    Runs MobileNet SSD inference on a frame.
    Returns (annotated_frame, list_of_label_strings).
    """
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)),
        0.007843, (300, 300), 127.5
    )
    net.setInput(blob)
    detections = net.forward()

    labels_found = []
    output = frame.copy()

    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < confidence_threshold:
            continue

        class_idx = int(detections[0, 0, i, 1])
        if class_idx >= len(DETECTION_CLASSES):
            continue

        label = DETECTION_CLASSES[class_idx]
        color = _CLASS_COLORS[class_idx] if class_idx < len(_CLASS_COLORS) else (0, 255, 0)

        # Bounding box (normalised → pixel)
        box = detections[0, 0, i, 3:7] * [w, h, w, h]
        x1, y1, x2, y2 = box.astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)

        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)

        tag = f"{label} {confidence * 100:.0f}%"
        tag_y = y1 - 8 if y1 > 20 else y1 + 18
        cv2.putText(output, tag, (x1, tag_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        labels_found.append(label)

    return output, labels_found


# ──────────────────────────────────────────────────────────
#  Serial (Arduino) helpers — unchanged from original
# ──────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────
#  Camera initialisation — picamera2 first, then OpenCV
# ──────────────────────────────────────────────────────────
def _open_picamera2():
    """
    Attempts to open the Pi Camera Module via picamera2.
    Returns a Picamera2 instance configured for video, or None.
    picamera2 is available on Raspberry Pi OS Bullseye+ with the Pi Camera Module.
    """
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        video_config = picam2.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameDurationLimits": (33333, 33333)}  # ~30 fps
        )
        picam2.configure(video_config)
        picam2.start()
        time.sleep(0.5)  # Warm-up
        print("✅ Pi Camera Module (picamera2) opened successfully.")
        return picam2
    except Exception as exc:
        print(f"ℹ️  picamera2 not available ({exc}). Trying OpenCV VideoCapture …")
        return None


def _open_opencv_cap():
    """
    Opens a USB webcam (or V4L2 device) via OpenCV.
    Tries index 0, then 1 as fallback.
    Returns a cv2.VideoCapture or None.
    """
    try:
        import cv2
        for idx in (0, 1):
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                print(f"✅ USB / V4L2 camera opened at index {idx}.")
                return cap
        return None
    except Exception as exc:
        print(f"⚠️  OpenCV camera open failed: {exc}")
        return None


def _read_picamera2_frame(picam2):
    """Captures one BGR frame from a Picamera2 instance."""
    import cv2
    import numpy as np
    rgb_array = picam2.capture_array()          # RGB888
    bgr_frame = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    return True, bgr_frame


# ──────────────────────────────────────────────────────────
#  MJPEG frame generator — NEW multi-camera-backend version
# ──────────────────────────────────────────────────────────
def generate_frames():
    """
    Generates MJPEG video frames from the Pi Camera or USB webcam.
    Overlays MobileNet SSD object detections and telemetry HUD.
    Falls back to a synthetic test pattern if no camera is found.
    """
    import cv2
    import numpy as np

    # Load detection model once (downloads if needed)
    net = load_detection_model() if enable_detection else None

    # Try Pi Camera Module first, then USB webcam
    picam2 = _open_picamera2()
    cap = None
    if picam2 is None:
        cap = _open_opencv_cap()

    if picam2 is None and cap is None:
        print("⚠️  No physical camera found — streaming synthetic FPV pattern.")

    frame_counter = 0

    while True:
        frame_counter += 1
        raw_frame = None

        # ── Capture frame ──
        if picam2 is not None:
            try:
                ok, raw_frame = _read_picamera2_frame(picam2)
                if not ok:
                    raw_frame = None
            except Exception:
                raw_frame = None

        elif cap is not None and cap.isOpened():
            ok, raw_frame = cap.read()
            if not ok:
                raw_frame = None

        # ── Object detection ──
        detected_labels = []
        if raw_frame is not None and net is not None:
            try:
                raw_frame, detected_labels = run_detection(raw_frame, net)
            except Exception:
                pass  # Detection failure should never crash the stream

        # Update shared telemetry with detected objects
        with serial_lock:
            current_telemetry["detected_objects"] = detected_labels

        # ── HUD overlay ──
        if raw_frame is not None:
            frame = raw_frame
            h, w = frame.shape[:2]

            car_state = current_telemetry['car_state']
            dist_cm = current_telemetry['distance_cm']
            obstacle = current_telemetry['obstacle_active']
            obj_count = len(detected_labels)

            # Top banner
            cv2.putText(frame,
                        f"OCUSTEER ROVER FPV  |  {car_state}",
                        (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

            # Distance — red if obstacle, green otherwise
            dist_color = (0, 0, 255) if obstacle else (0, 255, 0)
            cv2.putText(frame,
                        f"DIST: {dist_cm} cm {'⚠ OBSTACLE' if obstacle else ''}",
                        (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.60, dist_color, 2)

            # Detection count
            if obj_count > 0:
                unique = list(dict.fromkeys(detected_labels))   # preserve order, remove dups
                obj_str = ", ".join(unique[:4])  # max 4 labels on screen
                cv2.putText(frame,
                            f"DETECTED: {obj_str}",
                            (15, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 1)

            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            jpeg_bytes = buffer.tobytes()

        else:
            # ── Synthetic fallback pattern ──
            synthetic = np.zeros((480, 640, 3), dtype=np.uint8)
            synthetic[:, :] = (20, 24, 30)

            # Grid lines
            for y in range(0, 480, 40):
                cv2.line(synthetic, (0, y), (640, y), (40, 48, 60), 1)
            for x in range(0, 640, 40):
                cv2.line(synthetic, (x, 0), (x, 480), (40, 48, 60), 1)

            # Crosshair reticle
            cv2.circle(synthetic, (320, 240), 50, (0, 230, 255), 1)
            cv2.line(synthetic, (320, 170), (320, 310), (0, 230, 255), 1)
            cv2.line(synthetic, (250, 240), (390, 240), (0, 230, 255), 1)

            cv2.putText(synthetic, "OCUSTEER ROVER FPV  [NO CAMERA — STANDBY]",
                        (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 200), 2)
            cv2.putText(synthetic,
                        f"STATE: {current_telemetry['car_state']}  |  "
                        f"DIST: {current_telemetry['distance_cm']} cm",
                        (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (200, 200, 200), 1)
            cv2.putText(synthetic, f"FRAME: {frame_counter}",
                        (20, 455), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (100, 120, 140), 1)

            _, buffer = cv2.imencode('.jpg', synthetic)
            jpeg_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
        time.sleep(0.04)  # ~25 FPS


# ──────────────────────────────────────────────────────────
#  HTTP Routes — all existing routes preserved unchanged
# ──────────────────────────────────────────────────────────
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
        "control": "/control?cmd=[F|S|L|R|B]",
        "detection": "MobileNet SSD (PASCAL-VOC 20 classes)" if enable_detection else "disabled"
    })


# ──────────────────────────────────────────────────────────
#  Entry Point
# ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="OcuSteer Car Server")
    parser.add_argument("--port", type=int, default=5001, help="HTTP Server Port")
    parser.add_argument("--serial", type=str, default="/dev/ttyACM0", help="Car Arduino Serial Port")
    parser.add_argument("--no-detection", action="store_true",
                        help="Disable MobileNet SSD object detection (saves CPU on Pi 3)")
    args = parser.parse_args()

    enable_detection = not args.no_detection

    open_serial(args.serial)

    print("=" * 65)
    print("🚀 OcuSteer Car Server running")
    print(f"🌐 Stream URL  : http://0.0.0.0:{args.port}/video_feed")
    print(f"📡 Serial      : {args.serial}")
    print(f"🔍 Detection   : {'MobileNet SSD (auto-download if needed)' if enable_detection else 'DISABLED'}")
    print("=" * 65)

    app.run(host="0.0.0.0", port=args.port, threaded=True)
