#!/usr/bin/env python3
"""
OcuSteer - Real-Time EOG & Jaw-Clench Visualizer & Calibrator
------------------------------------------------------------
Plots live biosignals received from Arduino Uno #1 over USB Serial.
Allows dynamic threshold calibration and visual inspection of eye glances and blinks.

Usage:
    python tools/eog_visualizer.py [PORT] [BAUD]

Example:
    python tools/eog_visualizer.py /dev/ttyACM0 9600
"""

import sys
import time
import serial
import serial.tools.list_ports

try:
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def scan_ports():
    ports = serial.tools.list_ports.comports()
    print("\n🔍 Available Serial Ports:")
    for p in ports:
        print(f"  - {p.device}: {p.description}")
    return [p.device for p in ports]


def run_text_monitor(ser):
    print("\n📊 Running in Console Monitor Mode (Press Ctrl+C to stop)...")
    print(f"{'Time (s)':<10} | {'EOG ADC':<10} | {'Piezo ADC':<10} | {'Status'}")
    print("-" * 50)
    start_time = time.time()
    try:
        while True:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                elapsed = f"{time.time() - start_time:.2f}"
                print(f"{elapsed:<10} | {line}")
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


def run_live_plotter(ser):
    print("\n📈 Initializing Live Matplotlib Waveform Monitor...")
    window_size = 200
    eog_data = [512] * window_size
    piezo_data = [0] * window_size
    x_axis = list(range(window_size))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    fig.canvas.manager.set_window_title("OcuSteer - Live Biosignal Telemetry")

    # EOG Plot
    ax1.set_ylim(0, 1023)
    ax1.set_ylabel("EOG Signal (0-1023 ADC)")
    ax1.axhline(512, color='gray', linestyle='--', alpha=0.6, label="Baseline")
    ax1.axhline(512 + 120, color='blue', linestyle=':', label="Left Glance Thresh")
    ax1.axhline(512 - 120, color='orange', linestyle=':', label="Right Glance Thresh")
    line_eog, = ax1.plot(x_axis, eog_data, color='green', lw=1.5, label="Filtered EOG")
    ax1.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)

    # Piezo Plot
    ax2.set_ylim(0, 1023)
    ax2.set_ylabel("Piezo (Jaw Clench)")
    ax2.set_xlabel("Recent Samples (100 Hz)")
    ax2.axhline(350, color='red', linestyle='--', label="Clench Trigger")
    line_piezo, = ax2.plot(x_axis, piezo_data, color='purple', lw=1.5, label="Piezo Vibration")
    ax2.legend(loc="upper right")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    def update(_):
        while ser.in_waiting:
            raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
            parts = raw_line.split(',')
            try:
                if len(parts) >= 2:
                    eog_val = int(parts[0])
                    piezo_val = int(parts[1])
                    eog_data.pop(0)
                    eog_data.append(eog_val)
                    piezo_data.pop(0)
                    piezo_data.append(piezo_val)
            except ValueError:
                pass

        line_eog.set_ydata(eog_data)
        line_piezo.set_ydata(piezo_data)
        return line_eog, line_piezo

    ani = animation.FuncAnimation(fig, update, interval=20, blit=True)
    plt.show()


def main():
    available = scan_ports()
    port = sys.argv[1] if len(sys.argv) > 1 else (available[0] if available else "/dev/ttyACM0")
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600

    print(f"\n🔌 Connecting to {port} at {baud} baud...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)  # Wait for Arduino DTR reset
        print(" Connected successfully.")
    except Exception as e:
        print(f"❌ Failed to connect to serial port: {e}")
        print("Check connections or specify port manually: python tools/eog_visualizer.py <PORT>")
        sys.exit(1)

    if HAS_MATPLOTLIB:
        run_live_plotter(ser)
    else:
        print("Note: matplotlib not found. Running in CLI text mode.")
        run_text_monitor(ser)


if __name__ == "__main__":
    main()
