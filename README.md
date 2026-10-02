# 👁️ OcuSteer — AI-Powered Assistive Wheelchair & Rover System

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Hardware: Arduino & Raspberry Pi](https://img.shields.io/badge/Hardware-Arduino%20%7C%20Raspberry%20Pi-red.svg)](https://www.arduino.cc/)
[![Design System: Obsidian Vanguard](https://img.shields.io/badge/Design%20System-Obsidian%20Vanguard-white.svg)](#-cockpit-dashboard-obsidian-vanguard)

**A low-cost, hands-free navigation platform for quadriplegic and severely paralyzed individuals.**  
Combining **dual-modal biopotential signals (temple EOG & jaw-clench piezo)** with **deep learning vision AI (YuNet)** and **ultrasonic collision avoidance**.

[Architecture](#-system-architecture) • [Features](#-key-features) • [Hardware Wiring](#-hardware-setup--bom) • [Quick Start](#-quick-start) • [Docker / Podman](#-docker--container-deployment)

</div>

---

## 📖 Overview

Conventional motorized wheelchairs rely on joysticks or expensive commercial eye-tracking cameras ($3,000–$10,000) that fail in direct sunlight or total darkness. 

**OcuSteer** solves this with a multi-layered, redundant control paradigm:
1. **Electrooculography (EOG)**: The human eyeball acts as an electric dipole (corneo-retinal potential). Electrodes placed at the temples detect rapid horizontal saccades (left/right glances) directly as microvolt swings through an AD8232 module.
2. **Piezoelectric Jaw Clench**: A MEAS piezo vibration sensor placed over the masseter muscle registers intentional jaw clenches to toggle propulsion (**Start / Stop**), creating an unambiguous binary channel immune to eye blinks.
3. **Deep Learning Vision AI (YuNet)**: Laptop or onboard cameras run real-time facial landmark and pupil tracking on CPU (100+ FPS) to complement or substitute biopotential inputs.
4. **Autonomous Ultrasonic Safety**: Front-mounted HC-SR04 ultrasonic sensors enforce an automatic emergency brake if an obstacle is closer than $30\text{ cm}$, overriding all driver commands.

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
   │     └── HC-SR04 Ultrasonic Distance Sensor (&lt; 30cm Auto-Brake)
   └─────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

- **Dual-Modal Biosignal Fusion**: Temple EOG horizontal glances + piezo jaw clench binary toggle.
- **Deep Learning Vision AI**: OpenCV 5 YuNet ONNX neural network for CPU facial keypoint and pupil tracking.
- **Obsidian Vanguard Web Cockpit**: Monochromatic dark studio interface (`#131313`, `#201f1f`) with sweeping 32px rounded bento pods, `Libre Caslon Text` typography, and glassmorphic pill controls.
- **Real-Time Oscilloscope**: 60 FPS HTML5 Canvas visualizer rendering live green EOG and purple Piezo waveforms with baseline and threshold guidelines.
- **Hardware Collision Override**: Hard-coded microcontroller safety loop that halts motors regardless of user commands when an obstacle is within 30 cm.
- **Containerized & Fedora Ready**: Complete Dockerfile, Podman compatibility, and launcher scripts (`./run.sh`, `./stop.sh`).

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

Communication between the Laptop Hub, Raspberry Pi, and Arduino Controller uses single-byte ASCII commands:

| Command | Action | Description |
|:---:|:---:|:---|
| `'F'` | **Forward** | Cruising forward propulsion |
| `'S'` | **Stop** | Emergency brake / halt all motors |
| `'L'` | **Turn Left** | Nudge left (differential steering) |
| `'R'` | **Turn Right** | Nudge right (differential steering) |
| `'B'` | **Reverse** | Reverse motors |

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

Refer to [docs/wiring_and_pinout.md](file:///home/laksh/Documents/OS%20project/docs/wiring_and_pinout.md) for detailed schematics.

---

## 🚀 Quick Start

### 1. Prerequisites (Fedora / Linux / macOS)
Ensure Python 3.10+ is installed:
```bash
python3 --version
```

### 2. Launch Local Server
Use the included launcher script, which automatically sets up dependencies and launches the application:
```bash
./run.sh
```
Open **[http://localhost:5000](http://localhost:5000)** in your browser (Firefox, Chrome, etc.).

### 3. Terminate Server
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

### Docker
```bash
docker compose up -d
```

---

## 👥 Authors & Academic Context

- **Developer**: Laksh Jalan ([lakshjalan8@gmail.com](mailto:lakshjalan8@gmail.com))
- **Repository**: [https://github.com/Lakshjalan/AI-POWERED-WHEELCHAIR](https://github.com/Lakshjalan/AI-POWERED-WHEELCHAIR)
- **Target Themes**: Assistive Technology, MedTech, Embedded Systems, Smart India Hackathon (SIH).

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
