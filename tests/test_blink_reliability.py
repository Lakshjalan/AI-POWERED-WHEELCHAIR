#!/usr/bin/env python3
"""
Comprehensive Unit Tests for OcuSteer Blink Detection & Morse Integration.
Tests:
  1. Short blinks (Dots) at 30 FPS and 20 FPS
  2. Long blinks (Dashes) at 30 FPS
  3. Partial closures & squints (should NOT trigger blinks)
  4. Single-frame noise spikes (must be rejected)
  5. Adaptive calibration for small resting eye baselines (e.g. 0.24)
  6. Adaptive calibration for large resting eye baselines (e.g. 0.36)
  7. Temporary landmark loss during in-progress blinks (must preserve Morse timing)
  8. Permanent landmark loss (must NOT invent blinks)
  9. Full Morse decoding sequence (DOT + DASH = 'A')
"""

import sys
import os
import time

# Ensure laptop_hub is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'laptop_hub'))

from eye_tracker import EyeTracker
from morse_decoder import MorseDecoder


def test_short_blink_30fps():
    print("[TEST 1] Short Blink (Dot) at 30 FPS...")
    tracker = EyeTracker()
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    t = 100.0
    dt = 1.0 / 30.0  # 33.3ms per frame

    # 10 open frames
    for _ in range(10):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 4 closed frames (~133ms)
    start_event_seen = False
    for i in range(4):
        tracker._update_blink_state(avg_ear=0.09, raw_contrast=None, now=t)
        if tracker.blink_event_start:
            start_event_seen = True
            morse.on_blink_start()
        t += dt

    assert start_event_seen, "Blink start event was not fired for 133ms blink"
    assert tracker.is_eye_closed is True, "Tracker should be in CLOSED state"

    # 4 open frames
    end_event_seen = False
    measured_dur = 0.0
    for _ in range(4):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        if tracker.blink_event_end:
            end_event_seen = True
            measured_dur = tracker.last_completed_blink_duration
            morse.on_blink_end(explicit_duration=measured_dur)
        t += dt

    assert end_event_seen, "Blink end event was not fired upon reopening"
    assert tracker.is_eye_closed is False, "Tracker should return to OPEN state"
    assert 0.10 <= measured_dur <= 0.20, f"Expected duration ~0.13s, got {measured_dur:.3f}s"
    assert morse.current_symbol == ".", f"Expected dot (.), got '{morse.current_symbol}'"
    print(f"  PASS: Measured {measured_dur:.3f}s -> Classified as DOT '.'")


def test_short_blink_20fps():
    print("[TEST 2] Short Blink (Dot) at 20 FPS (Low-spec webcam / CPU load)...")
    tracker = EyeTracker()
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    t = 200.0
    dt = 1.0 / 20.0  # 50.0ms per frame

    # 10 open frames
    for _ in range(10):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 2 closed frames (100ms total)
    start_event_seen = False
    for _ in range(2):
        tracker._update_blink_state(avg_ear=0.08, raw_contrast=None, now=t)
        if tracker.blink_event_start:
            start_event_seen = True
            morse.on_blink_start()
        t += dt

    assert start_event_seen, "Blink start event was not fired for 100ms blink at 20 FPS"

    # Reopen
    end_event_seen = False
    measured_dur = 0.0
    for _ in range(3):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        if tracker.blink_event_end:
            end_event_seen = True
            measured_dur = tracker.last_completed_blink_duration
            morse.on_blink_end(explicit_duration=measured_dur)
        t += dt

    assert end_event_seen, "Blink end event was not fired at 20 FPS"
    assert 0.08 <= measured_dur <= 0.18, f"Expected duration ~0.10s, got {measured_dur:.3f}s"
    assert morse.current_symbol == ".", f"Expected dot (.), got '{morse.current_symbol}'"
    print(f"  PASS: Measured {measured_dur:.3f}s at 20 FPS -> Classified as DOT '.'")


def test_normal_blink_dash():
    print("[TEST 3] Normal Blink (Dash) at 30 FPS...")
    tracker = EyeTracker()
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    t = 300.0
    dt = 1.0 / 30.0

    # 10 open frames
    for _ in range(10):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 14 closed frames (~466ms)
    for _ in range(14):
        tracker._update_blink_state(avg_ear=0.08, raw_contrast=None, now=t)
        if tracker.blink_event_start:
            morse.on_blink_start()
        t += dt

    # Reopen
    measured_dur = 0.0
    for _ in range(4):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        if tracker.blink_event_end:
            measured_dur = tracker.last_completed_blink_duration
            morse.on_blink_end(explicit_duration=measured_dur)
        t += dt

    assert 0.40 <= measured_dur <= 0.55, f"Expected duration ~0.46s, got {measured_dur:.3f}s"
    assert morse.current_symbol == "-", f"Expected dash (-), got '{morse.current_symbol}'"
    print(f"  PASS: Measured {measured_dur:.3f}s -> Classified as DASH '-'")


def test_partial_closure_squint():
    print("[TEST 4] Partial Eye Closure & Squint Noise Rejection...")
    tracker = EyeTracker()

    t = 400.0
    dt = 1.0 / 30.0

    # User squints: EAR drops from 0.30 to 0.24 (above close threshold 0.21)
    for _ in range(20):
        tracker._update_blink_state(avg_ear=0.24, raw_contrast=None, now=t)
        assert tracker.is_eye_closed is False, "Squint should NOT cause is_eye_closed to become True"
        assert tracker.blink_event_start is False, "Squint should NOT trigger blink_event_start"
        t += dt

    print("  PASS: Squint did not trigger false blink events.")


def test_single_frame_noise_spike():
    print("[TEST 5] Single-Frame Jitter / Landmark Glitch Rejection...")
    tracker = EyeTracker()

    t = 500.0
    dt = 1.0 / 30.0

    # 5 normal open frames
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 1 rogue noise frame plunging to 0.05
    tracker._update_blink_state(avg_ear=0.05, raw_contrast=None, now=t)
    assert tracker.is_eye_closed is False, "Single noise frame must NOT trigger eye closure"
    assert tracker.blink_event_start is False, "Single noise frame must NOT fire blink_event_start"
    t += dt

    # Immediately back to open (0.30)
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        assert tracker.is_eye_closed is False
        assert tracker.blink_event_end is False
        t += dt

    print("  PASS: Single-frame noise spike correctly rejected without false blink.")


def test_small_baseline_calibration():
    print("[TEST 6] Small Resting Eye Baseline Calibration (0.24)...")
    tracker = EyeTracker()

    t = 600.0
    dt = 1.0 / 30.0

    # Feed 35 frames of 0.24
    for _ in range(35):
        tracker._update_blink_state(avg_ear=0.24, raw_contrast=None, now=t)
        t += dt

    assert tracker.ear_calibration_complete is True, "EAR calibration should be complete"
    assert abs(tracker.open_baseline_ear - 0.24) < 0.01, f"Expected baseline ~0.24, got {tracker.open_baseline_ear}"
    assert tracker.ear_close_thresh < 0.20, f"Expected close thresh < 0.20, got {tracker.ear_close_thresh}"
    print(f"  Calibrated Baseline: {tracker.open_baseline_ear:.3f}, Close Thresh: {tracker.ear_close_thresh:.3f}")

    # Now simulate a blink dropping to 0.12
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.10, raw_contrast=None, now=t)
        t += dt
    assert tracker.is_eye_closed is True, "Blink should be detected with small-eye threshold"

    # Reopen
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.24, raw_contrast=None, now=t)
        t += dt
    assert tracker.is_eye_closed is False, "Eye should reopen successfully"
    print("  PASS: Small-eye baseline calibrated and blinks detected accurately.")


def test_large_baseline_calibration():
    print("[TEST 7] Large Resting Eye Baseline Calibration (0.36)...")
    tracker = EyeTracker()

    t = 700.0
    dt = 1.0 / 30.0

    # Feed 35 frames of 0.36
    for _ in range(35):
        tracker._update_blink_state(avg_ear=0.36, raw_contrast=None, now=t)
        t += dt

    assert tracker.ear_calibration_complete is True, "EAR calibration should be complete"
    assert abs(tracker.open_baseline_ear - 0.36) < 0.01, f"Expected baseline ~0.36, got {tracker.open_baseline_ear}"
    assert tracker.ear_close_thresh > 0.24, f"Expected close thresh > 0.24, got {tracker.ear_close_thresh}"
    print(f"  Calibrated Baseline: {tracker.open_baseline_ear:.3f}, Close Thresh: {tracker.ear_close_thresh:.3f}")

    # A blink dropping to 0.20 (which would have been MISSED under old static 0.21 threshold!)
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.20, raw_contrast=None, now=t)
        t += dt
    assert tracker.is_eye_closed is True, "Blink to 0.20 should be detected with large-eye threshold"

    # Reopen
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.36, raw_contrast=None, now=t)
        t += dt
    assert tracker.is_eye_closed is False, "Eye should reopen successfully"
    print("  PASS: Large-eye baseline calibrated and blinks detected accurately.")


def test_temporary_landmark_loss_during_blink():
    print("[TEST 8] Temporary Landmark Dropout During Blink...")
    tracker = EyeTracker()
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    t = 800.0
    dt = 1.0 / 30.0

    # Open frames
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 2 closed frames -> Closure confirmed
    for _ in range(2):
        tracker._update_blink_state(avg_ear=0.08, raw_contrast=None, now=t)
        if tracker.blink_event_start:
            morse.on_blink_start()
        t += dt

    assert tracker.is_eye_closed is True, "Blink should be in progress"

    # 2 frames of temporary landmark loss (avg_ear=None, raw_contrast=None) ~66ms
    for _ in range(2):
        tracker._update_blink_state(avg_ear=None, raw_contrast=None, now=t)
        t += dt

    assert tracker.is_eye_closed is True, "Blink should NOT be cancelled during brief dropout grace period"

    # Landmarks return with open eye (0.30)
    end_event_seen = False
    measured_dur = 0.0
    for _ in range(3):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        if tracker.blink_event_end:
            end_event_seen = True
            measured_dur = tracker.last_completed_blink_duration
            morse.on_blink_end(explicit_duration=measured_dur)
        t += dt

    assert end_event_seen is True, "Blink end should fire cleanly when landmarks return"
    assert tracker.is_eye_closed is False
    assert 0.10 <= measured_dur <= 0.25, f"Measured duration should span total closure, got {measured_dur:.3f}s"
    assert morse.current_symbol == ".", f"Expected dot (.), got '{morse.current_symbol}'"
    print(f"  PASS: Dropout survived, duration {measured_dur:.3f}s measured cleanly, dot decoded.")


def test_permanent_landmark_loss_no_blink():
    print("[TEST 9] Permanent Landmark Loss (Driver Looks Away / Leaves Seat)...")
    tracker = EyeTracker()

    t = 900.0
    dt = 1.0 / 30.0

    # Open frames
    for _ in range(5):
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # Driver turns away: 20 frames of None
    for _ in range(20):
        tracker._update_blink_state(avg_ear=None, raw_contrast=None, now=t)
        assert tracker.is_eye_closed is False, "Landmark loss must NOT start a blink"
        assert tracker.blink_event_start is False, "No blink start event should fire"
        t += dt

    print("  PASS: Permanent landmark loss did not invent phantom blinks.")


def test_morse_decoding_letter_A():
    print("[TEST 10] Full Morse Decoding Sequence (DOT + DASH = 'A')...")
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08, char_gap=0.30)

    # 1. Dot (120ms)
    morse.on_blink_start()
    morse.on_blink_end(explicit_duration=0.12)
    assert morse.current_symbol == ".", f"Expected '.', got '{morse.current_symbol}'"

    # Brief inter-element gap (150ms < char_gap 300ms)
    time.sleep(0.15)

    # 2. Dash (450ms)
    morse.on_blink_start()
    morse.on_blink_end(explicit_duration=0.45)
    assert morse.current_symbol == ".-", f"Expected '.-', got '{morse.current_symbol}'"

    # Wait for character gap (> 300ms)
    time.sleep(0.40)
    assert morse.decoded_message.strip() == "A", f"Expected 'A', got '{morse.decoded_message}'"
    print(f"  PASS: Successfully decoded '{morse.decoded_message.strip()}' from Morse '.-'")


def test_short_blink_low_fps_15fps():
    print("[TEST 11] Single-Frame Short Blink (Dot) at 15 FPS (Laptop Webcam Pacing)...")
    tracker = EyeTracker()
    morse = MorseDecoder()
    morse.update_timings(dot_thresh=0.35, min_blink=0.08)

    t = 1000.0
    dt = 1.0 / 15.0  # 66.7ms per frame

    # 10 open frames
    for _ in range(10):
        tracker.current_ear_left = 0.30
        tracker.current_ear_right = 0.30
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 1 deeply closed frame (~70ms captured, representing 110ms physiological blink)
    tracker.current_ear_left = 0.09
    tracker.current_ear_right = 0.09
    tracker._update_blink_state(avg_ear=0.09, raw_contrast=None, now=t)
    assert tracker.blink_event_start is True, "Blink start should trigger for deep closure at 15 FPS"
    assert tracker.is_eye_closed is True, "Tracker should be in CLOSED state"
    morse.on_blink_start()
    t += dt

    # Reopening on subsequent frame
    tracker.current_ear_left = 0.30
    tracker.current_ear_right = 0.30
    tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
    assert tracker.blink_event_end is True, "Blink end should trigger upon reopening"
    assert tracker.is_eye_closed is False, "Tracker should return to OPEN state"

    measured_dur = tracker.last_completed_blink_duration
    morse.on_blink_end(explicit_duration=measured_dur)
    assert 0.10 <= measured_dur <= 0.20, f"Expected quantized duration ~0.12s, got {measured_dur:.3f}s"
    assert morse.current_symbol == ".", f"Expected dot (.), got '{morse.current_symbol}'"
    print(f"  PASS: Single-frame 15 FPS closure measured {measured_dur:.3f}s -> Decoded as DOT '.'")


def test_low_fps_single_frame_asymmetric_noise_rejection():
    print("[TEST 12] Low FPS (15 FPS) Asymmetric Single-Eye Noise Rejection...")
    tracker = EyeTracker()

    t = 1100.0
    dt = 1.0 / 15.0

    # 5 open frames
    for _ in range(5):
        tracker.current_ear_left = 0.30
        tracker.current_ear_right = 0.30
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    # 1 noise frame where only left eye drops (e.g. hair/hand occlusion)
    tracker.current_ear_left = 0.10
    tracker.current_ear_right = 0.28
    tracker._update_blink_state(avg_ear=0.19, raw_contrast=None, now=t)
    assert tracker.is_eye_closed is False, "Asymmetric single-eye dip must NOT trigger closed state"
    assert tracker.blink_event_start is False, "No blink start event should fire for asymmetric noise"
    t += dt

    # Return to normal open
    for _ in range(5):
        tracker.current_ear_left = 0.30
        tracker.current_ear_right = 0.30
        tracker._update_blink_state(avg_ear=0.30, raw_contrast=None, now=t)
        t += dt

    print("  PASS: Single-eye tracking noise correctly rejected at 15 FPS.")


def test_diagnostic_frame_logging():
    print("[TEST 13] Rolling Frame-by-Frame Diagnostic Logging...")
    tracker = EyeTracker()

    t = 1200.0
    dt = 1.0 / 30.0

    for _ in range(10):
        tracker.current_ear_left = 0.31
        tracker.current_ear_right = 0.30
        tracker._update_blink_state(avg_ear=0.305, raw_contrast=None, now=t)
        t += dt

    logs = tracker.get_diagnostic_log()
    assert len(logs) == 10, f"Expected 10 log entries, got {len(logs)}"
    last_entry = logs[-1]
    assert "t" in last_entry and "fps" in last_entry
    assert "ear_l" in last_entry and "ear_r" in last_entry and "ear_avg" in last_entry
    assert "baseline" in last_entry and "th_close" in last_entry and "th_open" in last_entry
    assert "is_closed" in last_entry and "evt_start" in last_entry and "evt_end" in last_entry

    dump = tracker.dump_diagnostic_log()
    assert "Time" in dump and "EAR_L" in dump and "EAR_R" in dump
    print(f"  PASS: Diagnostic log verified ({len(logs)} frames recorded, formatted table validated).")


if __name__ == '__main__':
    print("=" * 65)
    print("RUNNING EXTENSIVE BLINK RELIABILITY & MORSE INTEGRATION TESTS")
    print("=" * 65)
    test_short_blink_30fps()
    test_short_blink_20fps()
    test_normal_blink_dash()
    test_partial_closure_squint()
    test_single_frame_noise_spike()
    test_small_baseline_calibration()
    test_large_baseline_calibration()
    test_temporary_landmark_loss_during_blink()
    test_permanent_landmark_loss_no_blink()
    test_morse_decoding_letter_A()
    test_short_blink_low_fps_15fps()
    test_low_fps_single_frame_asymmetric_noise_rejection()
    test_diagnostic_frame_logging()
    print("=" * 65)
    print(">>> ALL 13 TESTS PASSED SUCCESSFULLY! <<<")
    print("=" * 65)
