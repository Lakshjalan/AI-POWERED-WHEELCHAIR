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
import math
import cv2
import numpy as np
import collections

# Try importing MediaPipe Tasks API
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    HAS_MEDIAPIPE = True
except ImportError:
    HAS_MEDIAPIPE = False

class EyeTracker:
    # Standard 6-point MediaPipe mesh landmark indices for EAR calculation
    # Right eye indices (patient's right, left side of image)
    RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    # Left eye indices (patient's left, right side of image)
    LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

    def __init__(self, camera_index=0, model_path=None, mp_model_path=None):
        self.camera_index = camera_index
        self.cap = None

        base_dir = os.path.dirname(os.path.abspath(__file__))
        if model_path is None:
            model_path = os.path.join(base_dir, "models", "face_detection_yunet.onnx")
        if mp_model_path is None:
            mp_model_path = os.path.join(base_dir, "models", "face_landmarker.task")

        self.model_path = model_path
        self.mp_model_path = mp_model_path
        self.detector = None
        self.mp_landmarker = None

        self._init_detector()
        self._init_mediapipe()

        # Telemetry & state tracking
        self.current_gaze = "CENTER"
        self.blink_detected = False
        self.last_blink_time = 0
        self.double_blink_detected = False
        self.glance_start_time = 0
        self.active_glance = None
        self.gaze_ratio = 0.50
        self.face_detected = False

        # Configurable Blink Detection & Adaptive Calibration Parameters
        self.calibration_samples_required = 30 # Number of valid open-eye frames needed (~1 sec @ 30fps)
        self.calibration_samples = []
        self.calibration_complete = False
        self.open_baseline_contrast = 28.0     # Default baseline before calibration completes
        self.close_ratio = 0.65                # Below 65% of open baseline -> CLOSED
        self.open_ratio = 0.80                 # Above 80% of open baseline -> OPEN
        self.contrast_close_thresh = 18.0      # Derived: baseline * close_ratio
        self.contrast_open_thresh = 23.0       # Derived: baseline * open_ratio (hysteresis)
        self.last_raw_contrast = 0.0

        # Geometric EAR Parameters & Adaptive Calibration
        self.open_baseline_ear = 0.30          # Default open-eye EAR baseline
        self.ear_close_ratio = 0.70            # Below 70% of open baseline -> CLOSED (e.g. 0.30 * 0.70 = 0.210)
        self.ear_open_ratio = 0.85             # Above 85% of open baseline -> OPEN (e.g. 0.30 * 0.85 = 0.255)
        self.ear_close_thresh = 0.21           # Active threshold for closure
        self.ear_open_thresh = 0.26            # Active threshold for opening (hysteresis)
        self.ear_calibration_samples = []      # Buffer of stable open-eye EAR samples
        self.ear_calibration_samples_required = 30 # ~1 second of stable tracking
        self.ear_calibration_complete = False  # Calibration state flag
        self.current_ear = 0.0                 # Instantaneous raw EAR
        self.smoothed_ear = 0.30               # Filtered EAR
        self.ear_smoothing_alpha_close = 0.60  # Responsive filter on eye closure (~40ms fall time)
        self.ear_smoothing_alpha_open = 0.50   # Balanced response on eye opening

        # Internal state machine for continuous closure tracking
        # Multi-frame timing & state machine
        self.blink_consecutive_frames_req = 2  # At least 2 frames required to confirm CLOSED
        self.open_consecutive_frames_req = 2   # At least 2 frames required to confirm OPEN
        self.min_intentional_blink_sec = 0.10  # Ignore micro-blinks (< 100ms)
        self.blink_debounce_sec = 0.08         # Debounce gap
        self.landmark_loss_grace_sec = 0.18    # Max duration to hold active closure during brief landmark dropout

        self.raw_closed_frames = 0
        self.raw_open_frames = 0
        self.is_eye_closed = False
        self.candidate_closure_start = 0.0
        self.candidate_closure_end = 0.0
        self.closure_start_time = 0.0
        self.face_lost_start_time = 0.0
        self.current_blink_duration = 0.0
        self.last_completed_blink_duration = 0.0
        self.blink_event_start = False
        self.blink_event_end = False

        # Frame rate & timing metrics
        self.effective_dt = 0.033
        self.effective_fps = 30.0
        self.last_frame_time = 0.0

        # Detailed eye & face presence diagnostics
        self.current_ear_left = 0.0
        self.current_ear_right = 0.0
        self.yunet_face_detected = False
        self.mediapipe_detected = False

        # Diagnostic frame-by-frame rolling buffer & mode
        self.diagnostic_log_buffer = collections.deque(maxlen=150)
        self.diagnostic_mode = False

    def reset_calibration(self):
        """Safely resets open-eye contrast and EAR calibration baselines."""
        self.calibration_samples = []
        self.calibration_complete = False
        self.open_baseline_contrast = 28.0
        self.contrast_close_thresh = max(10.0, self.open_baseline_contrast * self.close_ratio)
        self.contrast_open_thresh = max(14.0, self.open_baseline_contrast * self.open_ratio)

        self.ear_calibration_samples = []
        self.ear_calibration_complete = False
        self.open_baseline_ear = 0.30
        self.ear_close_thresh = round(self.open_baseline_ear * self.ear_close_ratio, 3)
        self.ear_open_thresh = round(self.open_baseline_ear * self.ear_open_ratio, 3)
        self.smoothed_ear = 0.30

        self.raw_closed_frames = 0
        self.raw_open_frames = 0
        self.is_eye_closed = False
        self.candidate_closure_start = 0.0
        self.candidate_closure_end = 0.0
        self.closure_start_time = 0.0
        self.face_lost_start_time = 0.0
        self.current_blink_duration = 0.0
        print("[AI] EyeTracker baseline calibration reset (Contrast & EAR).")

    def enable_diagnostic_mode(self, enabled=True):
        """Enables or disables per-frame console logging for real webcam diagnostics."""
        self.diagnostic_mode = enabled

    def get_diagnostic_log(self):
        """Returns a list of recent frame diagnostics dictionaries."""
        return list(self.diagnostic_log_buffer)

    def dump_diagnostic_log(self, filepath=None):
        """Formats and optionally writes the rolling frame-by-frame diagnostic log."""
        header = (
            f"{'Time':>10} | {'FPS':>4} | {'EAR_L':>5} | {'EAR_R':>5} | {'AvgEAR':>6} | "
            f"{'Smooth':>6} | {'Base':>5} | {'ThClose':>7} | {'ThOpen':>6} | "
            f"{'State':>6} | {'Event':>5} | {'Dur(s)':>6} | {'FaceYN':>6} | {'FaceMP':>6}"
        )
        lines = [header, "-" * len(header)]
        for d in self.diagnostic_log_buffer:
            ev = "START" if d["evt_start"] else ("END" if d["evt_end"] else "-")
            lines.append(
                f"{d['t']:10.3f} | {d['fps']:4.1f} | {d['ear_l']:5.3f} | {d['ear_r']:5.3f} | {d['ear_avg']:6.3f} | "
                f"{d['ear_smooth']:6.3f} | {d['baseline']:5.3f} | {d['th_close']:7.3f} | {d['th_open']:6.3f} | "
                f"{'CLOSED' if d['is_closed'] else 'OPEN':>6} | {ev:>5} | {d['blink_dur']:6.2f} | "
                f"{str(d['yunet_face']):>6} | {str(d['mp_face']):>6}"
            )
        output = "\n".join(lines)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(output)
        return output

    def _update_calibration(self, raw_contrast):
        """Collects initial open-eye samples and calculates adaptive thresholds for YuNet contrast."""
        if self.calibration_complete:
            # Gradual slow adaptation when eyes are confirmed open
            if not self.is_eye_closed and raw_contrast >= self.contrast_open_thresh:
                # Exponential moving average with slow alpha to adjust to lighting shifts
                self.open_baseline_contrast = 0.98 * self.open_baseline_contrast + 0.02 * raw_contrast
                self.contrast_close_thresh = max(10.0, self.open_baseline_contrast * self.close_ratio)
                self.contrast_open_thresh = max(self.contrast_close_thresh + 3.0, self.open_baseline_contrast * self.open_ratio)
            return

        # Initial calibration phase
        self.calibration_samples.append(raw_contrast)
        if len(self.calibration_samples) >= self.calibration_samples_required:
            # Take median to resist any accidental blinks during the calibration period
            sorted_samples = sorted(self.calibration_samples)
            median_val = sorted_samples[len(sorted_samples) // 2]
            # Ensure sensible bounds for baseline contrast
            self.open_baseline_contrast = max(20.0, float(median_val))
            self.contrast_close_thresh = max(10.0, round(self.open_baseline_contrast * self.close_ratio, 1))
            self.contrast_open_thresh = max(self.contrast_close_thresh + 3.0, round(self.open_baseline_contrast * self.open_ratio, 1))
            self.calibration_complete = True
            print(f"[AI] Calibration complete. Open Baseline: {self.open_baseline_contrast:.1f}, "
                  f"Close Thresh: {self.contrast_close_thresh:.1f}, Open Thresh: {self.contrast_open_thresh:.1f}")

    def _update_ear_calibration(self, raw_ear):
        """Collects initial open-eye EAR samples and calculates user-adaptive thresholds."""
        if raw_ear is None or raw_ear <= 0:
            return

        # Safeguard: Do not calibrate during an active closure
        if self.is_eye_closed:
            return

        # Safeguard: Physiologically plausible open-eye bounds (rejects extreme squint or open-eye stare noise)
        if raw_ear < 0.20 or raw_ear > 0.45:
            return

        if self.ear_calibration_complete:
            # Slow gradual adaptation when eyes are confirmed open and stable
            if raw_ear >= self.ear_open_thresh and abs(raw_ear - self.open_baseline_ear) < 0.08:
                self.open_baseline_ear = 0.995 * self.open_baseline_ear + 0.005 * raw_ear
                self.open_baseline_ear = max(0.22, min(0.40, self.open_baseline_ear))
                self.ear_close_thresh = max(0.14, min(0.28, round(self.open_baseline_ear * self.ear_close_ratio, 3)))
                self.ear_open_thresh = max(self.ear_close_thresh + 0.035, min(0.34, round(self.open_baseline_ear * self.ear_open_ratio, 3)))
            return

        # Initial calibration accumulation
        self.ear_calibration_samples.append(raw_ear)
        if len(self.ear_calibration_samples) >= self.ear_calibration_samples_required:
            sorted_samples = sorted(self.ear_calibration_samples)
            median_ear = sorted_samples[len(sorted_samples) // 2]

            # Safeguards & clamping on baseline bounds
            self.open_baseline_ear = max(0.22, min(0.40, float(median_ear)))
            self.ear_close_thresh = max(0.14, min(0.28, round(self.open_baseline_ear * self.ear_close_ratio, 3)))
            self.ear_open_thresh = max(self.ear_close_thresh + 0.035, min(0.34, round(self.open_baseline_ear * self.ear_open_ratio, 3)))
            self.ear_calibration_complete = True
            print(f"[AI] EAR Calibration complete. Open Baseline: {self.open_baseline_ear:.3f}, "
                  f"Close Thresh: {self.ear_close_thresh:.3f}, Open Thresh: {self.ear_open_thresh:.3f}")

    def _update_blink_state(self, avg_ear, raw_contrast, now):
        """
        Evaluates instantaneous closure, applies responsive asymmetric smoothing,
        and steps the multi-frame state machine with candidate timestamping and dropout protection.
        """
        self.blink_event_start = False
        self.blink_event_end = False

        # Measure instantaneous frame delta and rolling effective FPS
        if self.last_frame_time > 0:
            dt = now - self.last_frame_time
            if 0.005 <= dt <= 2.0:
                self.effective_dt = 0.85 * self.effective_dt + 0.15 * dt
                self.effective_fps = 1.0 / self.effective_dt
        self.last_frame_time = now

        ear_detected = (avg_ear is not None and avg_ear > 0)
        if ear_detected:
            self.current_ear = avg_ear
            self._update_ear_calibration(avg_ear)

            # Asymmetric responsive smoothing: fast response on eye closure, stable on eye opening
            if avg_ear < self.smoothed_ear:
                alpha = self.ear_smoothing_alpha_close
            else:
                alpha = self.ear_smoothing_alpha_open
            self.smoothed_ear = (1.0 - alpha) * self.smoothed_ear + alpha * avg_ear

        # Determine whether the instantaneous frame suggests eye closure
        frame_is_closed = None
        if ear_detected:
            # Geometric EAR with dual-threshold hysteresis
            if self.is_eye_closed:
                # In CLOSED state: eye remains closed unless both smoothed and instantaneous EAR indicate opening
                frame_is_closed = (self.smoothed_ear < self.ear_open_thresh and avg_ear < self.ear_open_thresh)
            else:
                # In OPEN state: eye confirms closed when smoothed drops below close threshold or deep raw closure occurs
                frame_is_closed = (self.smoothed_ear < self.ear_close_thresh or avg_ear < (self.ear_close_thresh * 0.90))
        elif raw_contrast is not None:
            # Fallback to contrast if MediaPipe landmarks are unavailable
            if self.is_eye_closed:
                frame_is_closed = (raw_contrast < self.contrast_open_thresh)
            else:
                frame_is_closed = (raw_contrast < self.contrast_close_thresh)

        # Multi-frame state machine with temporal smoothing & dropout protection
        if frame_is_closed is True:
            self.face_lost_start_time = 0.0
            self.raw_closed_frames += 1
            self.raw_open_frames = 0
            if self.raw_closed_frames == 1:
                self.candidate_closure_start = now
        elif frame_is_closed is False:
            self.face_lost_start_time = 0.0
            self.raw_open_frames += 1
            self.raw_closed_frames = 0
            if self.raw_open_frames == 1:
                self.candidate_closure_end = now
        else:
            # Landmark / face loss frame (frame_is_closed is None)
            self.raw_closed_frames = 0
            self.raw_open_frames = 0

            if self.is_eye_closed:
                # If a blink was actively in progress, allow brief dropout grace period
                if self.face_lost_start_time == 0.0:
                    self.face_lost_start_time = now

                # If landmarks remain lost beyond the grace timeout, safely abort without inventing phantom blink
                if (now - self.face_lost_start_time) > self.landmark_loss_grace_sec:
                    self.is_eye_closed = False
                    self.current_blink_duration = 0.0
                    self.face_lost_start_time = 0.0
            else:
                self.face_lost_start_time = 0.0

        # State transition logic: OPEN -> CLOSED -> OPEN
        if not self.is_eye_closed:
            # Check transition to CLOSED:
            # At standard 30 FPS, require 2 frames to reject single-frame 33ms jitter.
            # At lower frame rates (effective_dt >= 0.045s, i.e. <= 22 FPS) where a 120ms blink only spans 1 frame,
            # allow 1 frame IF closure is deep and bilateral, preventing dropped blinks without accepting single-eye noise.
            is_deep_bilateral = (
                ear_detected and
                avg_ear < (self.ear_close_thresh * 0.90) and
                (self.current_ear_left == 0.0 or self.current_ear_right == 0.0 or abs(self.current_ear_left - self.current_ear_right) < 0.10)
            )
            frames_needed = 1 if (self.effective_dt >= 0.045 and is_deep_bilateral) else self.blink_consecutive_frames_req

            if self.raw_closed_frames >= frames_needed:
                # Check debounce cooldown from previous blink
                if (now - self.last_blink_time) >= self.blink_debounce_sec:
                    self.is_eye_closed = True
                    self.closure_start_time = self.candidate_closure_start if self.candidate_closure_start > 0 else now
                    self.blink_event_start = True
                    self.current_blink_duration = max(0.0, now - self.closure_start_time)
        else:
            # Currently closed: track continuous closure duration
            self.current_blink_duration = max(0.0, now - self.closure_start_time)

            # Check transition to OPEN:
            open_frames_needed = 1 if self.effective_dt >= 0.045 else self.open_consecutive_frames_req
            if self.raw_open_frames >= open_frames_needed:
                self.is_eye_closed = False
                self.blink_event_end = True
                end_time = self.candidate_closure_end if self.candidate_closure_end > 0 else now
                measured_dur = max(0.0, end_time - self.closure_start_time)

                # Compensate for camera sampling quantization error on genuine short blinks:
                # A 120ms physiological blink sampled discretely at 10-15 FPS can register a timestamp delta of 60-95ms.
                # If a verified closure lasted >= 50ms and < 120ms, bound the continuous duration to at least 120ms
                # so it is recognized as a valid intentional blink (>= 0.10s) and decodes reliably as a Morse dot (< 0.35s).
                if 0.050 <= measured_dur < 0.120:
                    closure_dur = 0.120
                else:
                    closure_dur = measured_dur

                self.last_completed_blink_duration = closure_dur
                self.current_blink_duration = 0.0

                # Check double-blink (two deliberate blinks in close succession)
                if self.min_intentional_blink_sec <= closure_dur <= 0.65:
                    gap_since_last = now - self.last_blink_time
                    if 0.15 < gap_since_last < 0.85:
                        self.double_blink_detected = True
                    self.last_blink_time = now
                else:
                    self.last_blink_time = now

        self.blink_detected = self.is_eye_closed

        # Record frame entry into rolling diagnostics buffer
        disp_dur = self.current_blink_duration if self.is_eye_closed else self.last_completed_blink_duration
        entry = {
            "t": round(now, 3),
            "fps": round(self.effective_fps, 1),
            "ear_l": round(self.current_ear_left, 3),
            "ear_r": round(self.current_ear_right, 3),
            "ear_avg": round(avg_ear, 3) if ear_detected else 0.0,
            "ear_smooth": round(self.smoothed_ear, 3),
            "baseline": round(self.open_baseline_ear, 3),
            "th_close": round(self.ear_close_thresh, 3),
            "th_open": round(self.ear_open_thresh, 3),
            "is_closed": self.is_eye_closed,
            "cand_start": round(self.candidate_closure_start, 3),
            "yunet_face": self.yunet_face_detected,
            "mp_face": self.mediapipe_detected,
            "evt_start": self.blink_event_start,
            "evt_end": self.blink_event_end,
            "blink_dur": round(disp_dur, 3),
        }
        self.diagnostic_log_buffer.append(entry)

        if self.diagnostic_mode:
            ev = " [BLINK_START]" if self.blink_event_start else (" [BLINK_END]" if self.blink_event_end else "")
            print(f"[DIAG] t={entry['t']:.3f} fps={entry['fps']:.1f} EAR={entry['ear_avg']:.3f} "
                  f"(L:{entry['ear_l']:.3f}/R:{entry['ear_r']:.3f}) sm={entry['ear_smooth']:.3f} "
                  f"state={'CLOSED' if entry['is_closed'] else 'OPEN':>6} dur={entry['blink_dur']:.2f}s{ev}")

    def _init_detector(self):
        """Initializes OpenCV YuNet face detector."""
        if os.path.exists(self.model_path) and hasattr(cv2, "FaceDetectorYN"):
            try:
                # Default input size (w, h)
                self.detector = cv2.FaceDetectorYN.create(
                    self.model_path, "", (320, 240),
                    score_threshold=0.6, nms_threshold=0.3, top_k=1
                )
                print("[AI] YuNet Deep Learning Face & Eye AI Initialized.")
            except Exception as e:
                print(f"[WARN] Could not init YuNet: {e}")
                self.detector = None
        else:
            self.detector = None

    def _init_mediapipe(self):
        """Initializes MediaPipe FaceLandmarker for geometric 3D eye landmarks."""
        if not HAS_MEDIAPIPE:
            print("[AI] MediaPipe not available; using YuNet contrast fallback.")
            self.mp_landmarker = None
            return

        if not os.path.exists(self.mp_model_path):
            print(f"[WARN] MediaPipe model task file not found at {self.mp_model_path}")
            self.mp_landmarker = None
            return

        try:
            base_options = mp_python.BaseOptions(model_asset_path=self.mp_model_path)
            options = mp_vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.mp_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
            print("[AI] MediaPipe FaceLandmarker (Geometric EAR) Initialized.")
        except Exception as e:
            print(f"[WARN] Could not init MediaPipe FaceLandmarker: {e}")
            self.mp_landmarker = None

    @staticmethod
    def calculate_ear(landmarks_dict):
        """
        Calculates Eye Aspect Ratio (EAR) from 6 points [p1, p2, p3, p4, p5, p6]:
        EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)
        p1, p4 are outer and inner corners. p2, p3 are upper lid. p5, p6 are lower lid.
        """
        # Vertical distances
        v1 = math.hypot(landmarks_dict[1][0] - landmarks_dict[5][0], landmarks_dict[1][1] - landmarks_dict[5][1])
        v2 = math.hypot(landmarks_dict[2][0] - landmarks_dict[4][0], landmarks_dict[2][1] - landmarks_dict[4][1])
        # Horizontal distance
        h = math.hypot(landmarks_dict[0][0] - landmarks_dict[3][0], landmarks_dict[0][1] - landmarks_dict[3][1])

        if h < 1e-4:
            return 0.0
        return (v1 + v2) / (2.0 * h)

    def start_camera(self):
        try:
            # On Windows, DirectShow (CAP_DSHOW) avoids MSMF exclusive lock contention and frame drops
            if os.name == 'nt':
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    ret, test_frame = self.cap.read()
                    if ret and test_frame is not None:
                        return True
                    self.cap.release()

            # Default backend (Linux v4l2, macOS AVFoundation, or fallback)
            self.cap = cv2.VideoCapture(self.camera_index)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None:
                    return True
                self.cap.release()
                self.cap = None
                return False
            self.cap = None
            return False
        except Exception:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
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
        self.blink_event_start = False
        self.blink_event_end = False

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

            raw_contrast = None
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
                eye_contrasts = []
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
                        min_val, max_val, min_loc, _ = cv2.minMaxLoc(gray_patch)
                        pupil_x = x1 + min_loc[0]
                        pupil_y = y1 + min_loc[1]
                        cv2.circle(frame, (pupil_x, pupil_y), 3, (0, 0, 255), -1)

                        ratio = (pupil_x - x1) / float(x2 - x1)
                        eye_ratios.append(ratio)
                        
                        # Contrast metric for blink detection
                        # When eyes are open, dark pupil vs white sclera creates high contrast.
                        # When closed, skin is relatively uniform.
                        avg_intensity = np.mean(gray_patch)
                        contrast = avg_intensity - min_val
                        eye_contrasts.append(contrast)

                if eye_contrasts:
                    raw_contrast = sum(eye_contrasts) / len(eye_contrasts)
                    self.last_raw_contrast = raw_contrast
                    self._update_calibration(raw_contrast)

                # Gaze tracking: only update when eyes are open to avoid blink artifacts
                if eye_ratios and not self.is_eye_closed:
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
            else:
                self.face_detected = False
                self.current_gaze = "CENTER"

            # ---------------------------------------------------------
            # 1. Primary: Geometric Eye Aspect Ratio (EAR) via MediaPipe
            # ---------------------------------------------------------
            ear_detected = False
            avg_ear = None
            if self.mp_landmarker is not None:
                try:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    mp_result = self.mp_landmarker.detect(mp_image)

                    if mp_result.face_landmarks and len(mp_result.face_landmarks) > 0:
                        landmarks = mp_result.face_landmarks[0]
                        # Extract pixel coordinates for left and right eyes
                        right_pts = [(landmarks[idx].x * w, landmarks[idx].y * h) for idx in self.RIGHT_EYE_INDICES]
                        left_pts = [(landmarks[idx].x * w, landmarks[idx].y * h) for idx in self.LEFT_EYE_INDICES]

                        ear_right = self.calculate_ear(right_pts)
                        ear_left = self.calculate_ear(left_pts)
                        avg_ear = (ear_right + ear_left) / 2.0
                        self.current_ear_right = ear_right
                        self.current_ear_left = ear_left
                        ear_detected = True

                        # Draw subtle eye landmark points
                        for pt in right_pts + left_pts:
                            cv2.circle(frame, (int(pt[0]), int(pt[1])), 1, (0, 255, 180), -1)
                except Exception as e:
                    ear_detected = False

            # Update face detection flags for YuNet and MediaPipe
            self.yunet_face_detected = (faces is not None and len(faces) > 0)
            self.mediapipe_detected = ear_detected
            self.face_detected = self.yunet_face_detected or self.mediapipe_detected

            # Update blink detection state machine & adaptive calibration
            self._update_blink_state(avg_ear, raw_contrast, now)
        else:
            return self._generate_synthetic_driver(now)

        # Draw HUD overlays on frame
        color_map = {"LEFT": (255, 140, 0), "RIGHT": (0, 165, 255), "CENTER": (0, 255, 0)}
        col = color_map.get(self.current_gaze, (255, 255, 255))
        cv2.putText(frame, f"GAZE: {self.current_gaze}", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        cv2.putText(frame, f"RATIO: {self.gaze_ratio:.2f}", (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # --- Debug Overlay for Contrast & Calculated Thresholds ---
        cal_status = "CALIBRATED" if self.ear_calibration_complete else f"CALIBRATING ({len(self.ear_calibration_samples)}/{self.ear_calibration_samples_required})"
        cal_color = (0, 255, 120) if self.ear_calibration_complete else (0, 200, 255)
        cv2.putText(frame, f"STATUS: {cal_status}", (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, cal_color, 1)

        # --- Geometric EAR HUD Readout ---
        ear_str = f"{self.current_ear:.3f}" if self.current_ear > 0 else "N/A"
        cv2.putText(frame, f"EAR: {ear_str} (B:{self.open_baseline_ear:.2f})", (20, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 240, 255), 2)

        raw_c_str = f"{self.last_raw_contrast:.1f}" if self.last_raw_contrast else "N/A"
        cv2.putText(frame, f"Raw contrast: {raw_c_str}", (20, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)
        cv2.putText(frame, f"EAR Close/Open: {self.ear_close_thresh:.2f}/{self.ear_open_thresh:.2f}", (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 200), 1)
        cv2.putText(frame, f"Contrast Close/Open: {self.contrast_close_thresh:.1f}/{self.contrast_open_thresh:.1f}", (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 255), 1)
        cv2.putText(frame, f"Smoothed EAR: {self.smoothed_ear:.3f}", (20, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 255, 120), 1)

        eye_state_str = "CLOSED" if self.is_eye_closed else "OPEN"
        eye_state_col = (0, 100, 255) if self.is_eye_closed else (0, 255, 0)
        cv2.putText(frame, f"Eye: {eye_state_str}", (20, 185),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, eye_state_col, 2)

        disp_dur = self.current_blink_duration if self.is_eye_closed else self.last_completed_blink_duration
        cv2.putText(frame, f"Blink duration: {disp_dur:.2f}s", (20, 145),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)

        # Secondary diagnostics (contrast / detector mode)
        mode_label = "MediaPipe EAR" if self.mp_landmarker is not None else "YuNet Contrast"
        cv2.putText(frame, f"MODE: {mode_label}", (20, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 180, 200), 1)

        if self.double_blink_detected:
            cv2.putText(frame, ">> DOUBLE-BLINK [START/STOP] <<", (20, 215),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        elif self.blink_detected:
            dur_str = f"BLINK ({self.current_blink_duration:.2f}s)"
            cv2.putText(frame, dur_str, (20, 215),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 255), 2)

        return frame, {
            "gaze": self.current_gaze,
            "gaze_ratio": round(float(self.gaze_ratio), 2),
            "blink": self.blink_detected,
            "blink_duration": round(float(self.current_blink_duration if self.is_eye_closed else self.last_completed_blink_duration), 2),
            "blink_event_start": self.blink_event_start,
            "blink_event_end": self.blink_event_end,
            "double_blink": self.double_blink_detected,
            "face_detected": self.face_detected,
            "timestamp": now,
            "raw_ear": round(float(self.current_ear), 3) if self.current_ear > 0 else 0.0,
            "ear_left": round(float(self.current_ear_left), 3) if self.current_ear_left > 0 else 0.0,
            "ear_right": round(float(self.current_ear_right), 3) if self.current_ear_right > 0 else 0.0,
            "smoothed_ear": round(float(self.smoothed_ear), 3),
            "ear_baseline": round(float(self.open_baseline_ear), 3),
            "ear_close_thresh": round(float(self.ear_close_thresh), 3),
            "ear_open_thresh": round(float(self.ear_open_thresh), 3),
            "ear_calibrated": self.ear_calibration_complete,
            "eye_state": "CLOSED" if self.is_eye_closed else "OPEN",
            "effective_fps": round(float(self.effective_fps), 1),
            "yunet_detected": self.yunet_face_detected,
            "mediapipe_detected": self.mediapipe_detected,
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
            "blink_duration": 0.0,
            "blink_event_start": False,
            "blink_event_end": False,
            "double_blink": False,
            "face_detected": True,
            "timestamp": now,
            "raw_ear": 0.30,
            "ear_left": 0.30,
            "ear_right": 0.30,
            "smoothed_ear": 0.30,
            "ear_baseline": 0.30,
            "ear_close_thresh": 0.21,
            "ear_open_thresh": 0.26,
            "ear_calibrated": True,
            "eye_state": "OPEN",
            "effective_fps": 30.0,
            "yunet_detected": True,
            "mediapipe_detected": False,
        }
