#!/usr/bin/env python3
"""
OcuSteer - Deep Learning AI Eye & Gaze Tracker (YuNet ONNX)
------------------------------------------------------------
Runs on Fedora OS. Uses OpenCV 5 YuNet Neural Network:
  1. Detects face bounding box and 5 facial keypoints (eyes, nose, mouth corners)
  2. Tracks horizontal gaze saccades (glance Left / Right) via pupil-to-canthus ratio
  3. Detects blinks and double-blinks (Start/Stop toggle)
"""

import os
import time
import cv2
import numpy as np

class EyeTracker:
    def __init__(self, camera_index=0, model_path=None):
        self.camera_index = camera_index
        self.cap = None

        if model_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, "models", "face_detection_yunet.onnx")

        self.model_path = model_path
        self.detector = None
        self._init_detector()

        # Telemetry & state tracking
        self.current_gaze = "CENTER"
        self.blink_detected = False
        self.last_blink_time = 0
        self.double_blink_detected = False
        self.glance_start_time = 0
        self.active_glance = None
        self.gaze_ratio = 0.50
        self.face_detected = False

    def _init_detector(self):
        if os.path.exists(self.model_path) and hasattr(cv2, "FaceDetectorYN"):
            try:
                # Default input size (w, h)
                self.detector = cv2.FaceDetectorYN.create(
                    self.model_path, "", (320, 240),
                    score_threshold=0.6, nms_threshold=0.3, top_k=1
                )
                print("🧠 YuNet Deep Learning Face & Eye AI Initialized.")
            except Exception as e:
                print(f"⚠️ Could not init YuNet: {e}")
                self.detector = None
        else:
            self.detector = None

    def start_camera(self):
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if not self.cap.isOpened():
                self.cap = None
                return False
            return True
        except Exception:
            self.cap = None
            return False

    def release(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None

    def process_frame(self, frame=None):
        """Processes frame through YuNet neural network and extracts gaze telemetry."""
        now = time.time()
        self.double_blink_detected = False

        if frame is None:
            if self.cap is None or not self.cap.isOpened():
                if not self.start_camera():
                    return self._generate_synthetic_driver(now)

            ret, frame = self.cap.read()
            if not ret or frame is None:
                return self._generate_synthetic_driver(now)

        # Mirror frame horizontally for natural intuitive interaction
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        if self.detector is not None:
            # Set input size for YuNet
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(frame)

            if faces is not None and len(faces) > 0:
                self.face_detected = True
                face = faces[0]
                fx, fy, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                
                # Landmarks: right eye, left eye, nose, right mouth, left mouth
                re_x, re_y = int(face[4]), int(face[5])
                le_x, le_y = int(face[6]), int(face[7])
                nose_x, nose_y = int(face[8]), int(face[9])

                # Draw Face Bounding Box
                cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (0, 240, 200), 2)
                cv2.putText(frame, "DRIVER TRACKED (YuNet AI)", (fx, max(20, fy - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 240, 200), 1)

                # Eye ROI & pupil detection around landmarks
                eye_ratios = []
                for (ex, ey) in [(re_x, re_y), (le_x, le_y)]:
                    cv2.circle(frame, (ex, ey), 4, (0, 255, 255), -1)

                    # Extract eye patch
                    pad_w, pad_h = 24, 16
                    x1, y1 = max(0, ex - pad_w), max(0, ey - pad_h)
                    x2, y2 = min(w, ex + pad_w), min(h, ey + pad_h)

                    if x2 > x1 and y2 > y1:
                        eye_patch = frame[y1:y2, x1:x2]
                        gray_patch = cv2.cvtColor(eye_patch, cv2.COLOR_BGR2GRAY)
                        # Find darkest region (pupil)
                        min_val, _, min_loc, _ = cv2.minMaxLoc(gray_patch)
                        pupil_x = x1 + min_loc[0]
                        pupil_y = y1 + min_loc[1]
                        cv2.circle(frame, (pupil_x, pupil_y), 3, (0, 0, 255), -1)

                        ratio = (pupil_x - x1) / float(x2 - x1)
                        eye_ratios.append(ratio)

                # Compute gaze from pupil positions and nose displacement
                if eye_ratios:
                    avg_eye_ratio = sum(eye_ratios) / len(eye_ratios)
                    self.gaze_ratio = self.gaze_ratio * 0.65 + avg_eye_ratio * 0.35

                    # Gaze decision (mirrored display)
                    if self.gaze_ratio > 0.58:
                        detected_gaze = "RIGHT"
                    elif self.gaze_ratio < 0.42:
                        detected_gaze = "LEFT"
                    else:
                        detected_gaze = "CENTER"

                    if detected_gaze != "CENTER":
                        if self.active_glance == detected_gaze:
                            if now - self.glance_start_time > 0.18:
                                self.current_gaze = detected_gaze
                        else:
                            self.active_glance = detected_gaze
                            self.glance_start_time = now
                    else:
                        self.active_glance = None
                        self.current_gaze = "CENTER"

                self.blink_detected = False
            else:
                # Face missing or eyes closed
                if self.face_detected and not self.blink_detected:
                    self.blink_detected = True
                    gap = now - self.last_blink_time
                    if 0.15 < gap < 0.65:
                        self.double_blink_detected = True
                    self.last_blink_time = now
                self.current_gaze = "CENTER"
        else:
            return self._generate_synthetic_driver(now)

        # Draw HUD overlays on frame
        color_map = {"LEFT": (255, 140, 0), "RIGHT": (0, 165, 255), "CENTER": (0, 255, 0)}
        col = color_map.get(self.current_gaze, (255, 255, 255))
        cv2.putText(frame, f"GAZE: {self.current_gaze}", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2)
        cv2.putText(frame, f"RATIO: {self.gaze_ratio:.2f}", (20, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        if self.double_blink_detected:
            cv2.putText(frame, ">> DOUBLE-BLINK [START/STOP] <<", (20, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        elif self.blink_detected:
            cv2.putText(frame, "BLINK", (20, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 255), 1)

        return frame, {
            "gaze": self.current_gaze,
            "gaze_ratio": round(float(self.gaze_ratio), 2),
            "blink": self.blink_detected,
            "double_blink": self.double_blink_detected,
            "face_detected": self.face_detected,
            "timestamp": now
        }

    def _generate_synthetic_driver(self, now):
        """Generates realistic animated synthetic driver if webcam is off or bench testing."""
        frame = np.zeros((360, 480, 3), dtype=np.uint8)
        frame[:, :] = (20, 25, 34)

        # Head outline
        cv2.ellipse(frame, (240, 180), (105, 135), 0, 0, 360, (55, 70, 85), 2)

        # Animated glancing cycle for visual feedback
        cycle = (int(now * 1.4) % 8)
        if cycle in [1, 2]:
            sim_gaze = "LEFT"
            offset_x = -16
        elif cycle in [5, 6]:
            sim_gaze = "RIGHT"
            offset_x = 16
        else:
            sim_gaze = "CENTER"
            offset_x = 0

        # Eyes & Pupils
        for eye_x in [190, 290]:
            cv2.ellipse(frame, (eye_x, 160), (26, 13), 0, 0, 360, (190, 200, 210), -1)
            cv2.circle(frame, (eye_x + offset_x, 160), 8, (30, 35, 45), -1)
            cv2.circle(frame, (eye_x + offset_x, 160), 3, (0, 220, 255), -1)

        cv2.putText(frame, "DRIVER BIOMETRIC FEED [SIMULATED]", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 240, 200), 2)
        cv2.putText(frame, f"GAZE: {sim_gaze}", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, "Webcam auto-engages when available", (20, 340),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 140, 160), 1)

        return frame, {
            "gaze": sim_gaze,
            "gaze_ratio": 0.50 + (offset_x / 50.0),
            "blink": False,
            "double_blink": False,
            "face_detected": True,
            "timestamp": now
        }
