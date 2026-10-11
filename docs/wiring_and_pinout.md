# 🔌 Wiring and Pinout Specification

## System Architecture

```
[ Electrodes & Piezo ]
          │
          ▼
[ Arduino Uno (EOG Hub) ]
          │  USB Serial (9600 baud)
          ▼
[ Laptop Hub Dashboard (Flask) ] ◄── Webcam Eye-Tracker
    │                     ▲
    │ WiFi HTTP           │ WiFi MJPEG Video (/video_feed)
    ▼                     │
[ ESP32 Motor Controller ]   [ Raspberry Pi (On Car) ]
    │ L298N H-Bridge             │ USB Webcam / Pi Cam
    ▼                            ▼
 4x DC Motors               Live Video Stream
```

---

## 1. Electrode Placement Diagram

```
                 [Forehead]
                     │
    (LA) ──●                    ●── (RA)
  [Left Temple]              [Right Temple]
    (+) Input                  (-) Input
                     │
                   [Nose]
                     │
                   [Mouth]
                     │
               ● [Jawline / Masseter]
             (MEAS Piezo Sensor)

  Behind Ear (Mastoid Process, Bony Part):
               ●── (RL) Ground Reference
```

- **LA (Left Arm / Lead 1)**: Left temple (~1 cm lateral to the outer canthus of the left eye).
- **RA (Right Arm / Lead 2)**: Right temple (~1 cm lateral to the outer canthus of the right eye).
- **RL (Right Leg / Reference Ground)**: Behind the ear on the mastoid bone (neutral reference with no muscle activity).
- **Piezo Vibration Sensor**: Placed flat against the lower cheek/masseter area or side of the jaw.

---

## 2. Arduino Uno: Signal Processing Unit (EOG + Jaw Clench)

Connects to the **Laptop via USB cable** (`/dev/ttyACM0` or `/dev/ttyUSB0` at 9600 baud).

| Component | Pin on Component | Pin on Arduino Uno | Description |
|:---|:---|:---|:---|
| **AD8232 EOG Module** | 3.3V | 3.3V | Power supply (Use 3.3V for cleaner biopotential ADC) |
| | GND | GND | System ground |
| | OUTPUT | A0 | Analog EOG raw output |
| | LO- | D2 | Lead-Off detect negative (electrode disconnect detect) |
| | LO+ | D3 | Lead-Off detect positive (electrode disconnect detect) |
| | SDN | NC | Shutdown pin (pulled high internally) |
| **MEAS Piezo Sensor** | (+) Signal Pin | A1 | Analog input with 1MΩ parallel pulldown resistor |
| | (-) GND Pin | GND | Common ground |
| **Status Indicator** | Built-in | Pin 13 (LED) | Blinks on glance / clench detection |

> [!IMPORTANT]
> Always place a **1MΩ resistor** across the Piezo sensor terminals to prevent floating static charges from giving erratic high readings.

---

## 3. ESP32 DevKit V1: Motor & Safety Controller

Mounted on the car chassis. Receives HTTP commands directly from Laptop Hub over Wi-Fi.

| Component | Pin on Component | ESP32 GPIO Pin | Description |
|:---|:---|:---|:---|
| **L298N Motor Driver** | ENA (Left Speed) | GPIO 25 (PWM) | Left motors speed control (LEDC) |
| | IN1 | GPIO 26 | Left motors direction 1 |
| | IN2 | GPIO 27 | Left motors direction 2 |
| | IN3 | GPIO 14 | Right motors direction 1 |
| | IN4 | GPIO 12 | Right motors direction 2 |
| | ENB (Right Speed) | GPIO 13 (PWM) | Right motors speed control (LEDC) |
| | GND | GND | Common reference ground |
| **HC-SR04 Ultrasonic (Front)** | VCC | 5V (from buck/VIN) | 5V Power rail |
| | GND | GND | Ground |
| | TRIG | GPIO 32 | Trigger pulse output |
| | ECHO | GPIO 33 | Echo pulse input |
| **Onboard Indicator** | Built-in | GPIO 2 | Solid ON when WiFi connected; alerts on obstacle |

---

## 4. Raspberry Pi: Live Video Streamer

Mounted on the car chassis. Streams FPV video feed to the laptop web interface over Wi-Fi.

| Device | Connection to Pi | Role |
|:---|:---|:---|
| **USB Webcam or Pi Cam** | USB port or CSI Ribbon cable | Captures forward driver view |
| **Power Input** | USB-C (5V / 3A from buck converter) | Powers Raspberry Pi |
| **Network** | Wi-Fi (Same local network / hotspot) | Hosts MJPEG stream at port 5001 |

---

## 5. Power Architecture

```
[ 2S / 3S LiPo Battery or 12V Battery Pack ]
   │
   ├───→ [ L298N 12V In ] ──→ Drives 4x DC Motors
   │
   └───→ [ LM2596 Buck Converter #1 ] (Step down to 5.0V, 3A)
            │
            ├───→ [ Raspberry Pi USB-C / 5V Rail ]
            │
            └───→ [ ESP32 VIN & HC-SR04 VCC ]
```

> [!CAUTION]
> **Safety Rule**: When testing on a human subject, **NEVER power the biosignal Arduino from a mains-connected laptop charger without a USB isolator**.
> Run the laptop purely on battery (unplug charger) when wearing electrodes.
