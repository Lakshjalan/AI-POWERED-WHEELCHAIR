#!/usr/bin/env python3
"""
OcuSteer - Live Webcam Blink Diagnostic & Timing Analyzer
---------------------------------------------------------
Captures a short live webcam session, analyzes EAR metrics frame-by-frame,
and outputs a compact diagnostic report showing:
  - Effective processing FPS and inter-frame intervals
  - Raw EAR (Left, Right, Average) and Asymmetric Smoothed EAR
  - Baseline calibration and adaptive thresholds
  - Event triggers (BLINK_START, BLINK_END) and measured durations
  - Face detection status (YuNet vs MediaPipe)

No video files are saved or uploaded externally.
"""

import sys
import os
import time

# Ensure laptop_hub is on sys.path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(base_dir, 'laptop_hub'))

from eye_tracker import EyeTracker
from morse_decoder import MorseDecoder


def run_diagnostic_session(duration_sec=8.0, output_log="tools/blink_diagnostic_report.txt"):
    print("=" * 70)
    print("OCUSTEER LIVE WEBCAM BLINK DIAGNOSTIC SESSION")
    print(f"Recording frame-by-frame metrics for {duration_sec:.1f}s...")
    print("=" * 70)

    tracker = EyeTracker(camera_index=0)
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    started = tracker.start_camera()
    if not started:
        print("[WARN] Real camera could not be opened; running in synthetic benchmark mode.")

    tracker.enable_diagnostic_mode(enabled=False)

    frame_count = 0
    start_time = time.time()
    blinks_detected = 0
    fps_records = []

    try:
        while (time.time() - start_time) < duration_sec:
            t_frame_start = time.time()
            frame, tele = tracker.process_frame()
            dt = time.time() - t_frame_start
            frame_count += 1
            if tele.get("effective_fps"):
                fps_records.append(tele["effective_fps"])

            if tele.get("blink_event_start"):
                morse.on_blink_start()
            elif tele.get("blink_event_end"):
                blinks_detected += 1
                dur = tele.get("blink_duration", 0.0)
                morse.on_blink_end(explicit_duration=dur)

            # Cap loop pacing to ~30 FPS
            sleep_time = max(0.001, 0.033 - dt)
            time.sleep(sleep_time)

    finally:
        tracker.release()

    total_time = time.time() - start_time
    avg_fps = sum(fps_records) / len(fps_records) if fps_records else (frame_count / total_time)

    log_text = tracker.dump_diagnostic_log(filepath=output_log)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC SESSION SUMMARY")
    print("=" * 70)
    print(f"Total Session Duration : {total_time:.2f}s")
    print(f"Frames Processed       : {frame_count}")
    print(f"Average Effective FPS  : {avg_fps:.1f} FPS")
    print(f"Blinks Detected        : {blinks_detected}")
    print(f"Morse Decoded Symbols  : '{morse.current_symbol}' (Message: '{morse.decoded_message.strip()}')")
    print(f"Diagnostic Log File    : {output_log}")
    print("=" * 70)

    # Print sample of the log
    lines = log_text.splitlines()
    print("\nRecent 15 Diagnostic Frames:")
    for line in lines[:1] + lines[-15:]:
        print(line)

    return {
        "frames": frame_count,
        "avg_fps": avg_fps,
        "blinks": blinks_detected,
        "morse_symbol": morse.current_symbol
    }


if __name__ == '__main__':
    run_diagnostic_session(duration_sec=5.0)
