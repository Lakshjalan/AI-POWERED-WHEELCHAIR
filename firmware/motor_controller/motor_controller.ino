/*
 * ======================================================================================
 * OcuSteer - Motor & Safety Controller (Arduino Uno #2)
 * --------------------------------------------------------------------------------------
 * Receives CONTINUOUS gaze state + clench events from Arduino #1 via Serial.
 * Manages:
 *  1. L298N Dual H-Bridge Motor Driver (4 DC Motors, Differential Steering)
 *  2. Front HC-SR04 Ultrasonic Collision Override (< 30 cm)
 *  3. Optional I2C 1602 LCD for real-time status telemetry
 *
 * Protocol (from Arduino #1):
 *  0x01 = GAZE LEFT   → Turn left continuously
 *  0x02 = GAZE RIGHT  → Turn right continuously
 *  0x03 = GAZE CENTER → Resume forward (if vehicle is moving)
 *  0x04 = STOP        → Emergency stop (double-clench)
 *  0x05 = GO          → Start forward (single-clench)
 * ======================================================================================
 */

#include <Wire.h>

// --- PIN DEFINITIONS ---
// L298N Motor Driver Pins
const int PIN_ENA          = 5;   // Left Motors PWM Speed
const int PIN_IN1          = 6;   // Left Motors Direction 1
const int PIN_IN2          = 7;   // Left Motors Direction 2
const int PIN_IN3          = 8;   // Right Motors Direction 1
const int PIN_IN4          = 9;   // Right Motors Direction 2
const int PIN_ENB          = 10;  // Right Motors PWM Speed

// Ultrasonic Sensor Pins
const int PIN_TRIG_FRONT   = 11;  // Front Ultrasonic Trigger
const int PIN_ECHO_FRONT   = 12;  // Front Ultrasonic Echo

// Built-in status LED
const int PIN_STATUS_LED   = 13;

// --- COMMAND BYTE CONSTANTS ---
const uint8_t CMD_GAZE_LEFT   = 0x01;
const uint8_t CMD_GAZE_RIGHT  = 0x02;
const uint8_t CMD_GAZE_CENTER = 0x03;
const uint8_t CMD_STOP        = 0x04;
const uint8_t CMD_GO          = 0x05;

// --- MOTOR SPEEDS (0-255 PWM) ---
const int SPEED_CRUISE     = 180;
const int SPEED_TURN_OUTER = 200;
const int SPEED_TURN_INNER = 50;
const int SAFE_DISTANCE_CM = 30;

// State management
enum DriveState { STATE_STOPPED, STATE_FORWARD, STATE_TURNING_LEFT, STATE_TURNING_RIGHT };
DriveState currentState = STATE_STOPPED;
bool vehicleEnabled = false;  // Master enable: set by GO, cleared by STOP

unsigned long lastUltrasonicCheck = 0;
int frontDistanceCm               = 999;
bool obstacleDetected             = false;

// Function Prototypes
void setMotors(int leftDir, int leftSpeed, int rightDir, int rightSpeed);
int measureUltrasonic(int trigPin, int echoPin);
void handleCommand(uint8_t cmd);
void updateDriveLogic();

void setup() {
  Serial.begin(9600); // Cross-connected to Arduino #1 TX

  // Motor Driver Pins
  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  pinMode(PIN_ENB, OUTPUT);

  // Ultrasonic Pins
  pinMode(PIN_TRIG_FRONT, OUTPUT);
  pinMode(PIN_ECHO_FRONT, INPUT);

  pinMode(PIN_STATUS_LED, OUTPUT);

  // Stop motors initially
  setMotors(0, 0, 0, 0);
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. Process incoming command bytes from Arduino #1
  while (Serial.available() > 0) {
    uint8_t incomingByte = Serial.read();
    handleCommand(incomingByte);
  }

  // 2. Ultrasonic Safety Check (every 60ms)
  if (currentMillis - lastUltrasonicCheck >= 60) {
    lastUltrasonicCheck = currentMillis;
    frontDistanceCm = measureUltrasonic(PIN_TRIG_FRONT, PIN_ECHO_FRONT);

    if (frontDistanceCm > 0 && frontDistanceCm < SAFE_DISTANCE_CM) {
      if (!obstacleDetected) {
        obstacleDetected = true;
        // Collision emergency override: FORCE STOP motors (but keep vehicleEnabled state)
        currentState = STATE_STOPPED;
        setMotors(0, 0, 0, 0);
        digitalWrite(PIN_STATUS_LED, HIGH);
      }
    } else {
      if (obstacleDetected) {
        obstacleDetected = false;
        // When obstacle clears, resume forward if vehicle is still enabled
        if (vehicleEnabled) {
          currentState = STATE_FORWARD;
        }
        digitalWrite(PIN_STATUS_LED, LOW);
      }
    }
  }

  // 3. Drive FSM Logic
  updateDriveLogic();
}

void handleCommand(uint8_t cmd) {
  switch (cmd) {
    case CMD_GO:
      // Single clench → enable vehicle and go forward
      vehicleEnabled = true;
      if (!obstacleDetected) {
        currentState = STATE_FORWARD;
      }
      break;

    case CMD_STOP:
      // Double clench → full stop, disable vehicle
      vehicleEnabled = false;
      currentState = STATE_STOPPED;
      break;

    case CMD_GAZE_LEFT:
      // Continuous left gaze → turn left (only if vehicle is enabled)
      if (vehicleEnabled && !obstacleDetected) {
        currentState = STATE_TURNING_LEFT;
      }
      break;

    case CMD_GAZE_RIGHT:
      // Continuous right gaze → turn right (only if vehicle is enabled)
      if (vehicleEnabled && !obstacleDetected) {
        currentState = STATE_TURNING_RIGHT;
      }
      break;

    case CMD_GAZE_CENTER:
      // Gaze returned to center → resume forward (only if vehicle is enabled)
      if (vehicleEnabled && !obstacleDetected) {
        currentState = STATE_FORWARD;
      }
      break;

    default:
      break;
  }
}

void updateDriveLogic() {
  switch (currentState) {
    case STATE_STOPPED:
      setMotors(0, 0, 0, 0);
      break;

    case STATE_FORWARD:
      // Both sides forward at cruising speed
      setMotors(1, SPEED_CRUISE, 1, SPEED_CRUISE);
      break;

    case STATE_TURNING_LEFT:
      // Turn left CONTINUOUSLY: Right motor forward fast, left motor slow
      // No auto-revert timer — persists until CENTER or STOP command arrives
      setMotors(1, SPEED_TURN_INNER, 1, SPEED_TURN_OUTER);
      break;

    case STATE_TURNING_RIGHT:
      // Turn right CONTINUOUSLY: Left motor forward fast, right motor slow
      // No auto-revert timer — persists until CENTER or STOP command arrives
      setMotors(1, SPEED_TURN_OUTER, 1, SPEED_TURN_INNER);
      break;
  }
}

// Low-level Motor Control Helper
// dir: 1 = Forward, -1 = Reverse, 0 = Brake
void setMotors(int leftDir, int leftSpeed, int rightDir, int rightSpeed) {
  // Left Motor
  if (leftDir > 0) {
    digitalWrite(PIN_IN1, HIGH);
    digitalWrite(PIN_IN2, LOW);
  } else if (leftDir < 0) {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, HIGH);
  } else {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, LOW);
  }
  analogWrite(PIN_ENA, constrain(leftSpeed, 0, 255));

  // Right Motor
  if (rightDir > 0) {
    digitalWrite(PIN_IN3, HIGH);
    digitalWrite(PIN_IN4, LOW);
  } else if (rightDir < 0) {
    digitalWrite(PIN_IN3, LOW);
    digitalWrite(PIN_IN4, HIGH);
  } else {
    digitalWrite(PIN_IN3, LOW);
    digitalWrite(PIN_IN4, LOW);
  }
  analogWrite(PIN_ENB, constrain(rightSpeed, 0, 255));
}

// Measure HC-SR04 distance in cm
int measureUltrasonic(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // Timeout after 25ms (~4.3m max range) to prevent blocking
  long duration = pulseIn(echoPin, HIGH, 25000);
  if (duration == 0) return -1; // Out of range or sensor disconnected
  return (int)(duration * 0.0343 / 2.0);
}
