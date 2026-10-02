# 🔌 Wiring and Pinout Specification

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
- **RL (Right Leg / Reference Ground)**: Behind the right or left ear on the mastoid bone (neutral reference with no muscle activity).
- **Piezo Vibration Sensor**: Placed flat against the lower cheek/masseter area or side of the jaw, held by an elastic sports band.

---

## 2. Arduino Uno #1: Signal Processing Unit

| Component | Pin on Component | Pin on Arduino Uno #1 | Description |
|:---|:---|:---|:---|
| **AD8232 EOG Module** | 3.3V | 3.3V | Power supply (Use 3.3V for cleaner biopotential ADC) |
| | GND | GND | System ground |
| | OUTPUT | A0 | Analog EOG raw output |
| | LO- | D2 | Lead-Off detect negative (optional disconnect detect) |
| | LO+ | D3 | Lead-Off detect positive (optional disconnect detect) |
| | SDN | Not connected (NC) | Shutdown pin (pulled high internally) |
| **MEAS Piezo Sensor** | (+) Signal Pin | A1 | Analog input with 1MΩ parallel pulldown resistor |
| | (-) GND Pin | GND | Common ground |
| **Serial Link to MCU #2** | TX (Pin 1) | RX (Pin 0) on Uno #2 | Send 1-byte command (Cross-connect: TX → RX) |
| | GND | GND on Uno #2 | **MANDATORY**: Common ground between both Arduinos |
| **Status Indicator** | Anode (+) via 220Ω | Pin 13 (Builtin LED)| Flashes upon valid glance / clench detected |

> [!IMPORTANT]
> Always place a **1MΩ resistor** across the Piezo sensor terminals to prevent floating static charges from giving erratic high readings.

---

## 3. Arduino Uno #2: Motor & Safety Controller

| Component | Pin on Component | Pin on Arduino Uno #2 | Description |
|:---|:---|:---|:---|
| **UART from Uno #1** | RX (Pin 0) | TX (Pin 1) on Uno #1 | Receive commands from Signal Processor |
| | GND | GND on Uno #1 | Common reference ground |
| **L298N Motor Driver** | ENA (Left Enable) | Pin 5 (PWM) | Left motors speed control |
| | IN1 | Pin 6 | Left motors forward |
| | IN2 | Pin 7 | Left motors reverse |
| | IN3 | Pin 8 | Right motors forward |
| | IN4 | Pin 9 | Right motors reverse |
| | ENB (Right Enable)| Pin 10 (PWM) | Right motors speed control |
| **HC-SR04 Ultrasonic (Front)** | VCC | 5V | 5V Power rail |
| | GND | GND | Ground |
| | TRIG | Pin 11 | Trigger pulse output |
| | ECHO | Pin 12 | Echo pulse input |
| **HC-SR04 Ultrasonic (Rear)** | VCC | 5V | 5V Power rail |
| | GND | GND | Ground |
| | TRIG | Pin 4 | Trigger pulse output |
| | ECHO | Pin 3 | Echo pulse input |
| **I2C 1602 LCD Display** | VCC | 5V | 5V Power rail |
| | GND | GND | Ground |
| | SDA | A4 (SDA) | I2C Data |
| | SCL | A5 (SCL) | I2C Clock |

---

## 4. Power Architecture & Isolation

```
[ 2S / 3S LiPo Battery or 12V Battery Pack ]
   │
   ├───→ [ L298N 12V In ] ──→ Drives 4x DC Motors
   │
   └───→ [ LM2596 Buck Converter ] (Step down to 5.0V)
            │
            ├───→ [ Arduino #2 5V Pin ] (Motors, Ultrasonic, LCD)
            │
            └───→ [ Arduino #1 5V Pin ] ──→ 3.3V Regulator ──→ [ AD8232 & Piezo ]
```

> [!CAUTION]
> **Safety Rule**: When testing on a human subject, **NEVER power the biosignal Arduino from a mains-connected laptop charger without a USB isolator**. Either:
> 1. Run the laptop purely on battery (unplug charger), OR
> 2. Power the Arduino Uno #1 via a dedicated 9V battery or power bank.
