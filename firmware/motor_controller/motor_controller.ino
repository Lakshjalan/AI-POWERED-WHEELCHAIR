/*
 * ======================================================================================
 * OcuSteer - Motor & Safety Controller (Arduino Uno #2)
 * --------------------------------------------------------------------------------------
 * Receives biopotential steering & propulsion commands from Arduino #1 via Serial.
 * Manages:
 *  1. L298N Dual H-Bridge Motor Driver (4 DC Motors, Differential Steering)
 *  2. Front HC-SR04 Ultrasonic Collision Override (< 30 cm)
 *  3. Optional I2C 1602 LCD for real-time status telemetry
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
const uint8_t CMD_LEFT     = 0x01;
const uint8_t CMD_RIGHT    = 0x02;
const uint8_t CMD_STOP     = 0x03;
const uint8_t CMD_GO       = 0x04;

// --- MOTOR SPEEDS (0-255 PWM) ---
const int SPEED_CRUISE     = 180;
const int SPEED_TURN_OUTER = 200;
const int SPEED_TURN_INNER = 50;
const int SAFE_DISTANCE_CM = 30;

// State management
enum DriveState { STATE_STOPPED, STATE_FORWARD, STATE_TURNING_LEFT, STATE_TURNING_RIGHT };
DriveState currentState = STATE_STOPPED;

unsigned long lastUltrasonicCheck = 0;
unsigned long turnStartTime       = 0;
const unsigned long TURN_DURATION_MS = 600; // Duration of an incremental turn nudge
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
  if (Serial.available() > 0) {
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
        // Collision emergency override: FORCE STOP
        currentState = STATE_STOPPED;
        setMotors(0, 0, 0, 0);
        digitalWrite(PIN_STATUS_LED, HIGH);
      }
    } else {
      obstacleDetected = false;
      digitalWrite(PIN_STATUS_LED, LOW);
    }
  }

  // 3. Drive FSM Logic
  updateDriveLogic();
}

void handleCommand(uint8_t cmd) {
  // If obstacle is active, refuse GO commands
  if (obstacleDetected && cmd == CMD_GO) {
    return;
  }

  switch (cmd) {
    case CMD_GO:
      currentState = STATE_FORWARD;
      break;

    case CMD_STOP:
      currentState = STATE_STOPPED;
      break;

    case CMD_LEFT:
      currentState = STATE_TURNING_LEFT;
      turnStartTime = millis();
      break;

    case CMD_RIGHT:
      currentState = STATE_TURNING_RIGHT;
      turnStartTime = millis();
      break;

    default:
      break;
  }
}

void updateDriveLogic() {
  unsigned long currentMillis = millis();

  switch (currentState) {
    case STATE_STOPPED:
      setMotors(0, 0, 0, 0);
      break;

    case STATE_FORWARD:
      // Both sides forward at cruising speed
      setMotors(1, SPEED_CRUISE, 1, SPEED_CRUISE);
      break;

    case STATE_TURNING_LEFT:
      // Turn left: Right motor forward, left motor reduced/slow
      setMotors(1, SPEED_TURN_INNER, 1, SPEED_TURN_OUTER);
      if (currentMillis - turnStartTime >= TURN_DURATION_MS) {
        currentState = STATE_FORWARD; // Resume cruising
      }
      break;

    case STATE_TURNING_RIGHT:
      // Turn right: Left motor forward, right motor reduced/slow
      setMotors(1, SPEED_TURN_OUTER, 1, SPEED_TURN_INNER);
      if (currentMillis - turnStartTime >= TURN_DURATION_MS) {
        currentState = STATE_FORWARD; // Resume cruising
      }
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
