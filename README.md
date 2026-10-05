# 👁️ OcuSteer — AI-Powered Assistive Wheelchair & Rover System

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Hardware: Arduino & Raspberry Pi](https://img.shields.io/badge/Hardware-Arduino%20%7C%20Raspberry%20Pi-red.svg)](https://www.arduino.cc/)
[![Design System: Obsidian Vanguard](https://img.shields.io/badge/Design%20System-Obsidian%20Vanguard-white.svg)](#-cockpit-dashboard--obsidian-vanguard-design-system)
[![Flask](https://img.shields.io/badge/Flask-2.x-black.svg)](https://flask.palletsprojects.com/)
[![OpenCV](https://img.shields.io/badge/OpenCV-5.x-brightgreen.svg)](https://opencv.org/)

**A low-cost, hands-free navigation platform for quadriplegic and severely paralyzed individuals.**  
Combining **dual-modal biopotential signals (temple EOG & jaw-clench piezo)** with **deep learning vision AI (YuNet)** and **ultrasonic collision avoidance**.

[Architecture](#️-system-architecture) • [Features](#-key-features) • [Dashboard](#-cockpit-dashboard--obsidian-vanguard-design-system) • [Hardware](#-hardware-setup--bom) • [Quick Start](#-quick-start) • [Docker](#-docker--container-deployment) • [API](#-api-reference)

</div>

---

## 📖 Overview

Conventional motorized wheelchairs rely on joysticks or expensive commercial eye-tracking cameras ($3,000–$10,000) that fail in direct sunlight or total darkness.

**OcuSteer** solves this with a multi-layered, redundant control paradigm:

1. **Electrooculography (EOG)**: The human eyeball acts as an electric dipole (corneo-retinal potential). Electrodes placed at the temples detect rapid horizontal saccades (left/right glances) directly as microvolt swings through an AD8232 module. A moving-average filter (8-tap, 100 Hz) suppresses noise, and a duration-gating algorithm (160–600 ms) rejects blink artifacts.
2. **Piezoelectric Jaw Clench**: A MEAS piezo vibration sensor placed over the masseter muscle registers intentional jaw clenches to toggle propulsion (**Start / Stop**), creating an unambiguous binary channel immune to eye blinks.
3. **Deep Learning Vision AI (YuNet)**: Laptop or onboard cameras run real-time facial landmark and pupil tracking on CPU (100+ FPS via OpenCV 5 ONNX runtime) to complement or substitute biopotential inputs.
4. **Autonomous Ultrasonic Safety**: Front-mounted HC-SR04 ultrasonic sensors enforce an automatic emergency brake if an obstacle is closer than 30 cm, overriding all driver commands at the microcontroller level.

---

## 🏗️ System Architecture

```
                                  [ DRIVER ]
                       (Temples + Masseter Muscle)
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         │                                                       │
   [ Temple Electrodes ]                                   [ Laptop Webcam ]
         │ (Biopotential Swings)                                 │ (RGB Video)
         ▼                                                       ▼
   [ AD8232 EOG Module ]                                   [ YuNet Neural Net ]
   [ MEAS Piezo Clench ]                                   (Pupil Centroid / Saccades)
         │                                                       │
         ▼                                                       ▼
   [ Arduino Uno #1 ] ──USB Serial──► [ FEDORA LAPTOP HUB ] ◄────┘
   (Signal Pre-filtering)              ├── Multimodal Fusion Engine
                                       ├── Telemetry WebSocket Server
                                       └── Obsidian Vanguard Web Cockpit
                                                       │
                                                  Wi-Fi / LAN
                                                       │
                                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                       THE VEHICLE (ROVER)                   │
   │                                                             │
   │  [ Raspberry Pi + Camera ]                                  │
   │     ├── HTTP MJPEG Video Stream (Port 5001)                 │
   │     └── Serial Command Bridge (115200 baud)                 │
   │                   │                                         │
   │                   ▼                                         │
   │  [ Arduino Uno #2 (Vehicle Controller) ]                    │
   │     ├── L298N Dual H-Bridge Motor Driver ──► 4x DC Motors   │
   │     └── HC-SR04 Ultrasonic Distance Sensor (< 30cm Auto-Brake)│
   └─────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

| Feature | Description |
|:---|:---|
| **Dual-Modal Biosignal Fusion** | Temple EOG horizontal glances + piezo jaw clench binary toggle |
| **Deep Learning Vision AI** | OpenCV 5 YuNet ONNX neural network for CPU facial keypoint and pupil tracking |
| **Obsidian Vanguard Cockpit** | Monochromatic dark studio interface with bento pods, Libre Caslon typography, and glassmorphic pill controls |
| **Real-Time Oscilloscope** | 60 FPS HTML5 Canvas visualizer rendering live EOG and Piezo waveforms with baseline and threshold guidelines |
| **Theater / Fullscreen Mode** | One-click maximize the FPV camera stream to fullscreen theater mode with ESC exit |
| **Virtual D-Pad + Keyboard** | Manual override via on-screen D-Pad or keyboard (WASD / Arrow Keys / Space) |
| **Hardware Collision Override** | Hard-coded microcontroller safety loop that halts motors when obstacle < 30 cm |
| **Config Modal** | In-dashboard settings modal to configure Car IP, AI autopilot, clench/blink triggers live |
| **Containerized & Fedora Ready** | Complete Dockerfile, Podman compatibility, and launcher scripts (`./run.sh`, `./stop.sh`) |

---

## 🖥️ Cockpit Dashboard — Obsidian Vanguard Design System

The **Obsidian Vanguard** design system powers the web cockpit. It is a fully custom CSS framework designed for a premium, professional dark-studio aesthetic.

### Design Tokens

| Token | Value | Purpose |
|:---|:---|:---|
| `--bg-color` | `#131313` | Body background — near-black canvas |
| `--surface-container` | `#201f1f` | Primary bento pod fill |
| `--surface-container-lowest` | `#0e0e0e` | Oscilloscope / deepest layers |
| `--primary` | `#ffffff` | Hero text, active indicators |
| `--secondary` | `#c7c6c6` | Secondary text, Piezo wave |
| `--error` | `#ffb4ab` | Obstacle alerts, auto-brake |
| `--font-serif` | `Libre Caslon Text` | Brand title, pod headings |
| `--font-sans` | `Geist` | Data readouts, body text |
| `--font-mono` | `JetBrains Mono` | ADC values, timestamps, logs |
| `--radius-bento` | `32px` | Primary bento pod corner radius |
| `--radius-pill` | `9999px` | Status pills and chip badges |

### Dashboard Layout — Bento Grid

```
┌─────────────────── Studio Header (OcuSteer · Status Pills · HUD) ───────────────────┐
│                                                                                       │
│  ┌─────────────────────────────────┐  ┌─────────────────┐  ┌────────────────────┐   │
│  │  FPV Camera Stream (MJPEG/WebRTC│  │  Gaze Readout   │  │  Biosignal Panel   │   │
│  │  + Driver PIP + Overlay Canvas) │  │  (L / R / CTR)  │  │  EOG & Piezo Bars  │   │
│  │  + Theater Maximize Button      │  │  Quick Strip    │  │  + Oscilloscope    │   │
│  └─────────────────────────────────┘  └─────────────────┘  └────────────────────┘   │
│                                                                                       │
│  ┌──────────────────────┐  ┌────────────────────┐  ┌──────────────────────────────┐  │
│  │  Drive State Banner  │  │  Radar / Proximity │  │  Command Dispatch Log        │  │
│  │  (STOPPED/FWD/etc.)  │  │  + Auto-Brake Badge│  │  (Timestamped command feed)  │  │
│  └──────────────────────┘  └────────────────────┘  └──────────────────────────────┘  │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Virtual D-Pad (F / L / S / R / B) — Manual Override Control Panel             │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### Controls

| Input Method | Bindings | Action |
|:---|:---|:---|
| **Eye Glance (EOG)** | Left Glance | Turn Left |
| **Eye Glance (EOG)** | Right Glance | Turn Right |
| **Jaw Clench (Piezo)** | Clench | Toggle Start / Stop |
| **Keyboard** | `W` / `↑` | Forward |
| **Keyboard** | `A` / `←` | Turn Left |
| **Keyboard** | `D` / `→` | Turn Right |
| **Keyboard** | `S` / `↓` | Reverse |
| **Keyboard** | `Space` | Emergency Brake |
| **Keyboard** | `Esc` | Exit Theater Mode |
| **Virtual D-Pad** | F / L / S / R / B | Full manual override |

---

## 📁 Repository Structure

```
.
├── app.py                             # Root application entrypoint (auto-venv switcher)
├── run.sh                             # One-click start script (cleans ports & launches)
├── stop.sh                            # One-click stop script (kills process & frees ports)
├── run.py                             # Python launcher utility
├── requirements.txt                   # Pinned Python package dependencies
├── Dockerfile                         # Production container image definition
├── docker-compose.yml                 # Multi-container orchestration spec
├── DESIGN_SYSTEM.md                   # Obsidian Vanguard design specifications
│
├── laptop_hub/                        # Central Hub & Web Application (Fedora Laptop)
│   ├── app.py                         # Flask telemetry server, proxy & fusion coordinator
│   ├── eye_tracker.py                 # YuNet ONNX deep learning eye/gaze tracker
│   ├── models/
│   │   └── face_detection_yunet.onnx  # Pretrained lightweight YuNet neural network
│   ├── templates/
│   │   └── dashboard.html             # Obsidian Vanguard Bento cockpit HTML
│   └── static/
│       ├── css/dashboard.css          # Monochromatic styling, bento pods & animations
│       └── js/dashboard.js            # Telemetry poller, canvas scope & WebRTC camera
│
├── car/                               # Onboard Vehicle Firmware & Agent
│   ├── arduino_car_controller/
│   │   └── arduino_car_controller.ino # Arduino Uno motor & ultrasonic safety controller
│   └── pi_car_server.py               # Raspberry Pi camera streamer & serial bridge
│
├── firmware/                          # Biosignal Acquisition Firmware
│   ├── eog_processor/
│   │   └── eog_processor.ino          # Arduino Uno EOG filter, duration gate & piezo clench
│   └── motor_controller/
│       └── motor_controller.ino       # Standalone dual-Arduino motor firmware
│
├── docs/
│   └── wiring_and_pinout.md           # Pin-to-pin wiring diagram & power topology
└── tools/
    └── eog_visualizer.py              # CLI/Matplotlib serial biopotential wave plotter
```

---

## ⚡ Command Protocol

Communication between the Laptop Hub, Raspberry Pi, and Arduino Controller uses single-byte ASCII commands over serial (9600 baud) or HTTP:

| Command | Action | Description |
|:---:|:---:|:---|
| `'F'` | **Forward** | Cruising forward propulsion |
| `'S'` | **Stop** | Emergency brake / halt all motors |
| `'L'` | **Turn Left** | Nudge left (differential steering) |
| `'R'` | **Turn Right** | Nudge right (differential steering) |
| `'B'` | **Reverse** | Reverse motors |

### Internal Arduino Binary Protocol (Arduino #1 → Arduino #2 UART)

| Byte | Meaning |
|:---:|:---|
| `0x01` | TURN LEFT |
| `0x02` | TURN RIGHT |
| `0x03` | STOP / BRAKE |
| `0x04` | FORWARD / GO |
| `0x05` | CALIBRATE |

---

## 🔬 Signal Processing — EOG Firmware

The `eog_processor.ino` firmware running on **Arduino Uno #1** implements a real-time biosignal processing pipeline:

### Pipeline

```
Analog Read (A0 / A1)
        │
        ▼
8-tap Moving Average Filter (100 Hz, reduces noise by ~√8)
        │
        ▼
Lead-Off Detection (AD8232 pins 2 & 3)
        │
        ▼
Jaw-Clench Detection (Piezo A1 > 350 ADC → GO/STOP toggle)
        │
        ▼
Artifact Rejection Window (150 ms post-clench suppression)
        │
        ▼
Delta Threshold Comparison (±120 ADC from adaptive baseline)
        │
        ▼
Duration Gate (160 ms < saccade < 600 ms)
        │
        ▼
Biphasic Blink Rejection (polarity reversal check)
        │
        ▼
Cooldown (400 ms inter-command lockout)
        │
        ▼
UART Transmit (CMD byte → Arduino #2)
```

### Calibration

On boot, the firmware performs a **2-second auto-calibration** (200 samples at 10 ms intervals) while the user looks straight ahead to establish the resting EOG baseline. The baseline also tracks slowly over time using an **exponential moving average** (`weight = 1/1000`).

---

## 🔌 Hardware Setup & BOM

| Component | Function | Approx. Cost |
|:---|:---|:---|
| **AD8232 ECG/EOG Module** | Biopotential amplifier for temple eye glances | ₹300 / $4 |
| **MEAS Piezo Vibration Sensor** | Mechanical jaw-clench sensor taped to masseter | ₹150 / $2 |
| **3x Ag/AgCl Gel Electrodes** | Left temple (LA), Right temple (RA), Mastoid (RL) | ₹50 / $1 |
| **2x Arduino Uno** | (1) Signal pre-processor, (2) Vehicle motor controller | ₹900 / $11 |
| **1x Raspberry Pi + Camera** | Vehicle camera streamer and network bridge | Existing / $35 |
| **1x L298N H-Bridge Driver** | 4-channel DC motor power stage | ₹180 / $2 |
| **1x HC-SR04 Ultrasonic** | Front collision proximity detection | ₹80 / $1 |
| **4x DC Motors + Chassis** | Rover chassis and wheels | ₹500 / $6 |
| **1x LM2596 Buck Converter** | Steps battery voltage down to clean 5V logic rail | ₹70 / $1 |
| **Total** | | **~₹2,230 / ~$63** |

> Refer to [docs/wiring_and_pinout.md](docs/wiring_and_pinout.md) for detailed schematics and pin-to-pin wiring diagrams.

### Electrode Placement

```
           LEFT TEMPLE (LA) ●──────────────────● RIGHT TEMPLE (RA)
                             \                /
                              \   AD8232     /
                               └─────────────┘
                                      │
                               MASTOID (RL) ●   ← Reference / Ground
                               (behind ear)

           MASSETER ●   ← Piezo sensor, taped over jaw muscle
```

---

## 🚀 Quick Start

### 1. Prerequisites (Fedora / Linux / macOS)

Ensure Python 3.10+ is installed:
```bash
python3 --version
```

### 2. Clone the Repository

```bash
git clone https://github.com/Lakshjalan/AI-POWERED-WHEELCHAIR.git
cd AI-POWERED-WHEELCHAIR
```

### 3. Launch Local Server

Use the included launcher script, which automatically sets up a virtual environment, installs dependencies, and launches the application:
```bash
./run.sh
```

Open **[http://localhost:5000](http://localhost:5000)** in your browser (Firefox, Chrome, etc.).

> **Fedora / Wayland note**: Camera access via the web dashboard uses the native browser `getUserMedia` API, which works with PipeWire on Wayland without additional configuration.

### 4. Flash Firmware

Use the Arduino IDE to flash the firmware sketches:

- **Arduino #1 (Signal Processor)**: `firmware/eog_processor/eog_processor.ino`
- **Arduino #2 (Motor Controller)**: `car/arduino_car_controller/arduino_car_controller.ino`

### 5. Start the Vehicle Agent

On the Raspberry Pi:
```bash
python3 car/pi_car_server.py
```

### 6. Terminate Server

To safely stop the server and release port 5000:
```bash
./stop.sh
```

---

## 🐳 Docker / Container Deployment

### Native Podman (Fedora Recommended)

```bash
# Build image
podman build -t ocusteer-hub .

# Run container
podman run -d -p 5000:5000 --name ocusteer ocusteer-hub
```

### Docker Compose

```bash
docker compose up -d
```

---

## 🔗 API Reference

The Flask hub exposes the following REST endpoints:

| Method | Endpoint | Description |
|:---:|:---|:---|
| `GET` | `/` | Serves the Obsidian Vanguard cockpit dashboard |
| `GET` | `/api/telemetry` | Returns full telemetry JSON snapshot (gaze, biosignals, car state, radar) |
| `POST` | `/api/command` | Dispatches a drive command (`{ "command": "F", "source": "..." }`) |
| `POST` | `/api/config` | Updates runtime configuration (car IP, AI autopilot toggle, thresholds) |
| `GET` | `/video_feed` | Proxied MJPEG video stream from the Raspberry Pi |

### Telemetry JSON Schema

```json
{
  "car_connected": true,
  "car_state": "FORWARD",
  "current_gaze": "LEFT",
  "clench_active": false,
  "blink_active": false,
  "eog_value": 634,
  "piezo_value": 42,
  "eog_history": [512, 520, ...],
  "piezo_history": [40, 38, ...],
  "ultrasonic_distance": 87,
  "obstacle_alert": false,
  "command_log": [
    { "time": "23:15:04", "cmd": "F", "source": "EOG Gaze" }
  ]
}
```

---

## 🧪 Development & Debugging

### Visualize EOG Signals (CLI Plotter)

The `tools/eog_visualizer.py` script connects to the Arduino serial port and renders a live Matplotlib waveform for debugging electrode placement and threshold tuning:

```bash
python3 tools/eog_visualizer.py --port /dev/ttyUSB0 --baud 9600
```

### Adjusting EOG Thresholds

Edit the constants in `firmware/eog_processor/eog_processor.ino`:

```cpp
int leftThresholdDelta  = 120;  // Increase if false LEFT triggers
int rightThresholdDelta = 120;  // Increase if false RIGHT triggers
int piezoThreshold      = 350;  // Increase if accidental jaw clenches fire
const unsigned long MIN_GLANCE_DUR_MS = 160;  // Minimum deliberate saccade duration
const unsigned long COOLDOWN_MS       = 400;  // Inter-command lockout period
```

---

## 👥 Authors & Academic Context

- **Developer**: Laksh Jalan ([lakshjalan8@gmail.com](mailto:lakshjalan8@gmail.com))
- **Repository**: [https://github.com/Lakshjalan/AI-POWERED-WHEELCHAIR](https://github.com/Lakshjalan/AI-POWERED-WHEELCHAIR)
- **Target Themes**: Assistive Technology, MedTech, Embedded Systems, Smart India Hackathon (SIH).

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
