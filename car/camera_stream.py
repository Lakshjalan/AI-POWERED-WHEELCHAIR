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

# Orientation: 0 (normal), 90 (clockwise), 180, 270 (counter-clockwise)
# Default to 90 to transform portrait camera mounting into landscape
ROTATION_DEG = 90

# ==============================
# CAMERA CONFIGURATION (LOW LATENCY)
# ==============================
camera = Picamera2()

config = camera.create_video_configuration(
    main={
        "size": (640, 480),
        "format": "RGB888"
    },
    controls={
        "AwbEnable": True,
        "AeEnable": True,
        "FrameDurationLimits": (33333, 33333)  # Target steady ~30 FPS
    },
    buffer_count=2  # Minimized buffer to eliminate frame queue backlog
)

camera.configure(config)
camera.start()
time.sleep(1.5)

def cleanup():
    try:
        camera.stop()
    except Exception:
        pass

atexit.register(cleanup)

# ==============================
# OBJECTIVE DETECTION (ASYNC CACHED)
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
        print(f"⚠️ Objective detection offline: {e}")

load_detector()

# Vehicle shared state
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
        print(f"ℹ️ Serial Arduino not attached ({e}); running simulated.")

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
# HIGH-SPEED BACKGROUND FRAME GRABBER
# ==============================
latest_encoded_jpeg = None
jpeg_lock = threading.Lock()
cached_boxes = []
cached_labels = []

def camera_capture_loop():
    """Background worker thread: continually grabs frames and updates the latest JPEG."""
    global latest_encoded_jpeg, cached_boxes, cached_labels
    frame_idx = 0

    while True:
        try:
            frame = camera.capture_array()
            if ROTATION_DEG == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif ROTATION_DEG in (270, -90):
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif ROTATION_DEG == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)

            h, w = frame.shape[:2]
            frame_idx += 1

            # Run detection every 4th frame so AI doesn't bottleneck the 30fps video stream
            if detection_net is not None and (frame_idx % 4 == 0):
                try:
                    blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
                    detection_net.setInput(blob)
                    detections = detection_net.forward()

                    new_boxes = []
                    new_labels = []
                    for i in range(detections.shape[2]):
                        conf = float(detections[0, 0, i, 2])
                        if conf > 0.45:
                            class_idx = int(detections[0, 0, i, 1])
                            if class_idx < len(DETECTION_CLASSES):
                                label = DETECTION_CLASSES[class_idx]
                                color = _CLASS_COLORS[class_idx]
                                box = detections[0, 0, i, 3:7] * [w, h, w, h]
                                x1, y1, x2, y2 = box.astype(int)
                                new_boxes.append((max(0, x1), max(0, y1), min(w - 1, x2), min(h - 1, y2), label, conf, color))
                                new_labels.append(label)

                    cached_boxes = new_boxes
                    cached_labels = new_labels
                    with state_lock:
                        vehicle_state["detected_objects"] = new_labels
                except Exception:
                    pass

            # Draw current cached bounding boxes (keeps video smooth without blinking)
            for (x1, y1, x2, y2, label, conf, color) in cached_boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                tag = f"{label} {int(conf * 100)}%"
                tag_y = y1 - 8 if y1 > 20 else y1 + 18
                cv2.putText(frame, tag, (x1, tag_y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)

            with state_lock:
                current_state = vehicle_state["car_state"]

            # HUD Telemetry Overlay
            cv2.putText(frame, f"ROVER FPV | {current_state}", (15, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            if cached_labels:
                unique_labels = list(dict.fromkeys(cached_labels))
                cv2.putText(frame, f"OBJECTS: {', '.join(unique_labels[:3])}", (15, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 230, 255), 2)

            # High-speed encode (Quality 65 for ultra-low latency & high frame rate)
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if success:
                with jpeg_lock:
                    latest_encoded_jpeg = buffer.tobytes()

        except Exception as e:
            time.sleep(0.01)

# Start capture worker thread
capture_thread = threading.Thread(target=camera_capture_loop, daemon=True)
capture_thread.start()

# ==============================
# STREAM GENERATOR (ZERO-QUEUE)
# ==============================
def generate_frames():
    """Pours the freshest available frame with zero backlog queueing."""
    while True:
        with jpeg_lock:
            frame_bytes = latest_encoded_jpeg

        if frame_bytes is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n"
                + frame_bytes
                + b"\r\n"
            )
        time.sleep(0.03)  # ~33 FPS cadence

# ==============================
# HTTP ROUTES
# ==============================
@app.route("/")
def index():
    return f"""
    <!DOCTYPE html><html><head><title>Raspberry Pi 5 Rover</title>
    <style>body {{ background:#111827; color:#fff; font-family:sans-serif; text-align:center; padding:20px; }}
    img {{ max-width:960px; width:100%; border-radius:8px; border:2px solid #374151; }}
    .btn {{ margin-top:14px; padding:10px 20px; background:#2563eb; color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:15px; font-weight:bold; }}
    .btn:hover {{ background:#1d4ed8; }}
    </style></head>
    <body>
        <h1>Raspberry Pi 5 Rover Stream</h1>
        <img src="/video" alt="Rover Live Stream">
        <p>Current Rotation: <b>{ROTATION_DEG}&deg;</b> &bull; Ultra Low-Latency Stream Active</p>
        <div>
            <button class="btn" onclick="fetch('/rotate').then(()=>location.reload())">🔄 Rotate 90&deg;</button>
        </div>
    </body></html>
    """

@app.route("/rotate", methods=["GET", "POST"])
def rotate():
    global ROTATION_DEG
    deg = request.args.get("deg") or (request.json.get("deg") if request.is_json else None)
    if deg is not None:
        try:
            ROTATION_DEG = int(deg) % 360
        except ValueError:
            pass
    else:
        rotation_cycle = {0: 90, 90: 270, 270: 180, 180: 0}
        ROTATION_DEG = rotation_cycle.get(ROTATION_DEG, 90)
    return jsonify({"status": "ok", "rotation_deg": ROTATION_DEG})

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

@app.route("/control", methods=["GET", "POST"])
def control():
    cmd = request.args.get("cmd") or (request.json.get("cmd") if request.is_json else None)
    if not cmd:
        return jsonify({"status": "error", "message": "Missing 'cmd'"}), 400
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
    return {"status": "ok", "camera": "running", "mode": "low-latency", "rotation_deg": ROTATION_DEG}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OcuSteer Raspberry Pi 5 Camera Streamer")
    parser.add_argument("--rotate", type=int, default=90, choices=[0, 90, 180, 270], help="Rotation angle in degrees (default: 90 for landscape)")
    parser.add_argument("--port", type=int, default=5000, help="Port to run server on (default: 5000)")
    cli_args, _ = parser.parse_known_args()
    ROTATION_DEG = cli_args.rotate

    try:
        print(f"🚀 Starting ultra-low latency Pi 5 camera server (Rotation: {ROTATION_DEG}°)...")
        print(f"Port: {cli_args.port} | Endpoints: /video, /video_feed, /rotate")
        app.run(host="0.0.0.0", port=cli_args.port, threaded=True, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print('\nStopping...')
    finally:
        cleanup()


