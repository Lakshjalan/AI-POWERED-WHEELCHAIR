#!/usr/bin/env python3
"""
======================================================================================
OcuSteer - Raspberry Pi Live Video Streamer & Car Hub
--------------------------------------------------------------------------------------
Runs on Raspberry Pi mounted on the car chassis.
Key Responsibilities:
  1. Captures live camera feed (USB Webcam or Raspberry Pi Camera Module)
  2. Serves low-latency MJPEG video stream on port 5001 (/video_feed)
  3. Relayed directly into the Laptop Web Dashboard for the driver FPV view.
  4. Includes fallback cyber-HUD test stream if camera is disconnected.
======================================================================================
"""

import argparse
import sys
import time
import threading
import json
from flask import Flask, Response, request, jsonify

app = Flask(__name__)

# Global frame buffer & lock for thread-safe multi-client streaming
latest_jpeg = None
frame_lock = threading.Lock()
camera_running = True
camera_status = {"online": False, "source": "None", "fps": 0}

def camera_capture_thread(camera_index=0, width=640, height=360, fps=25):
    """Background thread that continuously grabs frames from the camera."""
    global latest_jpeg, camera_status, camera_running
    import cv2
    import numpy as np

    print(f"[Camera] Initializing capture on device index {camera_index} ({width}x{height} @ {fps}fps)...")
    
    cap = None
    try:
        # Try V4L2 backend first on Linux / Raspberry Pi OS
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(camera_index)
    except Exception as e:
        print(f"[Camera] Error opening camera: {e}")
        cap = None

    if cap and cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        camera_status["online"] = True
        camera_status["source"] = f"/dev/video{camera_index}"
        print(f"✅ [Camera] Camera initialized successfully on /dev/video{camera_index}!")
    else:
        print("⚠️ [Camera] No physical camera found. Generating synthetic Cyber-HUD stream.")
        camera_status["online"] = False
        camera_status["source"] = "Synthetic HUD"

    frame_counter = 0
    t0 = time.time()

    while camera_running:
        success = False
        frame = None

        if cap and cap.isOpened():
            success, frame = cap.read()

        if success and frame is not None:
            frame_counter += 1
            if time.time() - t0 >= 1.0:
                camera_status["fps"] = frame_counter
                frame_counter = 0
                t0 = time.time()

            # Optional telemetry / timestamp watermark
            cv2.putText(frame, "OCUSTEER ROVER FPV", (16, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 180), 2)
            cv2.putText(frame, time.strftime("%H:%M:%S"), (width - 120, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            with frame_lock:
                latest_jpeg = buffer.tobytes()
        else:
            # Fallback Synthetic Cyber HUD Frame
            synthetic = np.zeros((height, width, 3), dtype=np.uint8)
            synthetic[:, :] = (18, 22, 28)

            # Draw HUD grid lines
            for y in range(0, height, 40):
                cv2.line(synthetic, (0, y), (width, y), (35, 42, 55), 1)
            for x in range(0, width, 40):
                cv2.line(synthetic, (x, 0), (x, height), (35, 42, 55), 1)

            # Reticle / Crosshair
            cx, cy = width // 2, height // 2
            cv2.circle(synthetic, (cx, cy), 40, (0, 230, 255), 1)
            cv2.line(synthetic, (cx, cy - 50), (cx, cy + 50), (0, 230, 255), 1)
            cv2.line(synthetic, (cx - 50, cy), (cx + 50, cy), (0, 230, 255), 1)

            cv2.putText(synthetic, "OCUSTEER ROVER FPV FEED [STANDBY]", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
            cv2.putText(synthetic, "NO CAMERA ATTACHED - SYNTHETIC FEED", (20, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 180, 200), 1)
            cv2.putText(synthetic, time.strftime("%H:%M:%S"), (width - 120, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 1)

            _, buffer = cv2.imencode('.jpg', synthetic, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            with frame_lock:
                latest_jpeg = buffer.tobytes()

            time.sleep(1.0 / fps)

    if cap:
        cap.release()


def generate_mjpeg_stream():
    """Generator that yields MJPEG multipart boundary stream to HTTP clients."""
    while True:
        with frame_lock:
            frame_data = latest_jpeg

        if frame_data is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
        time.sleep(0.04)  # ~25 FPS max client transmission


@app.route('/video_feed')
def video_feed():
    """Main live video stream endpoint consumed by the Laptop Web Dashboard."""
    return Response(
        generate_mjpeg_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/telemetry')
def telemetry():
    """Camera status and heartbeat telemetry."""
    return jsonify({
        "service": "OcuSteer Raspberry Pi Camera Server",
        "camera_online": camera_status["online"],
        "camera_source": camera_status["source"],
        "fps": camera_status["fps"],
        "timestamp": time.time()
    })


@app.route('/')
def index():
    return jsonify({
        "service": "OcuSteer Raspberry Pi Camera Streamer",
        "status": "online",
        "video_feed": "/video_feed",
        "telemetry": "/telemetry"
    })


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="OcuSteer Raspberry Pi Camera Streamer")
    parser.add_argument("--port", type=int, default=5001, help="HTTP Server Port (default: 5001)")
    parser.add_argument("--camera", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument("--width", type=int, default=640, help="Stream width (default: 640)")
    parser.add_argument("--height", type=int, default=360, help="Stream height (default: 360)")
    parser.add_argument("--fps", type=int, default=25, help="Target FPS (default: 25)")
    args = parser.parse_args()

    # Start camera capture thread in background
    capture_thread = threading.Thread(
        target=camera_capture_thread,
        args=(args.camera, args.width, args.height, args.fps),
        daemon=True
    )
    capture_thread.start()

    print(f"🚀 [OcuSteer] Raspberry Pi Video Streamer running at http://0.0.0.0:{args.port}/video_feed")
    app.run(host="0.0.0.0", port=args.port, threaded=True)
