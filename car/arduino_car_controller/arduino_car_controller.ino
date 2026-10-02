/*
 * ======================================================================================
 * OcuSteer - Car Onboard Controller (Arduino Uno)
 * --------------------------------------------------------------------------------------
 * Mounted on the prototype car and wired directly to:
 *   1. L298N Dual H-Bridge Motor Driver (4 DC Motors)
 *   2. Front HC-SR04 Ultrasonic Distance Sensor
 *   3. Raspberry Pi (via USB Serial at 115200 baud)
 *
 * Safety Interlock:
 *   - Auto-brakes when front obstacle < 30 cm regardless of incoming commands.
 *   - Reports live ultrasonic distance back to the Raspberry Pi.
 * ======================================================================================
 */

// --- PIN DEFINITIONS ---
// L298N H-Bridge Motor Driver
const int PIN_ENA = 5;   // Left Motor Speed (PWM)
const int PIN_IN1 = 6;   // Left Motor Dir 1
const int PIN_IN2 = 7;   // Left Motor Dir 2
const int PIN_IN3 = 8;   // Right Motor Dir 1
const int PIN_IN4 = 9;   // Right Motor Dir 2
const int PIN_ENB = 10;  // Right Motor Speed (PWM)

// HC-SR04 Ultrasonic Distance Sensor
const int PIN_TRIG = 11;
const int PIN_ECHO = 12;

// Built-in status indicator
const int PIN_LED = 13;

// --- PARAMETERS & SPEEDS ---
const int SPEED_NORMAL     = 180;  // Cruising PWM (0-255)
const int SPEED_TURN_FAST  = 210;  // Outer wheel PWM during turn
const int SPEED_TURN_SLOW  = 60;   // Inner wheel PWM during turn
const int SAFE_DISTANCE_CM = 30;   // Obstacle safety threshold
const unsigned long TURN_DURATION_MS = 450; // Turn nudge duration

// --- STATE MACHINE ---
enum CarState { STATE_STOP, STATE_FORWARD, STATE_REVERSE, STATE_TURNING_LEFT, STATE_TURNING_RIGHT };
CarState currentState = STATE_STOP;
CarState previousDriveState = STATE_STOP;

unsigned long lastDistanceCheck = 0;
unsigned long lastTelemetrySend = 0;
unsigned long turnStartTime     = 0;
int currentDistanceCm           = 999;
bool obstacleActive             = false;

// Function Prototypes
void setMotorOutputs(int leftDir, int leftSpeed, int rightDir, int rightSpeed);
int measureDistance();
void executeCommand(char cmd);
void updateState();

void setup() {
  // High-speed serial connection with Raspberry Pi
  Serial.begin(115200);

  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  pinMode(PIN_ENB, OUTPUT);

  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_LED, OUTPUT);

  // Initialize motors to stopped state
  setMotorOutputs(0, 0, 0, 0);
  Serial.println("SYS_READY:CAR_CONTROLLER_ONLINE");
}

void loop() {
  unsigned long now = millis();

  // 1. Read incoming commands from Raspberry Pi
  while (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == '\n' || cmd == '\r') continue;
    executeCommand(cmd);
  }

  // 2. Ultrasonic Safety Check (every 50ms)
  if (now - lastDistanceCheck >= 50) {
    lastDistanceCheck = now;
    currentDistanceCm = measureDistance();

    if (currentDistanceCm > 0 && currentDistanceCm < SAFE_DISTANCE_CM) {
      if (!obstacleActive) {
        obstacleActive = true;
        // Collision emergency brake
        if (currentState == STATE_FORWARD || currentState == STATE_TURNING_LEFT || currentState == STATE_TURNING_RIGHT) {
          previousDriveState = currentState;
          currentState = STATE_STOP;
          setMotorOutputs(0, 0, 0, 0);
        }
        digitalWrite(PIN_LED, HIGH);
        Serial.print("WARN:OBSTACLE_BRAKE:");
        Serial.println(currentDistanceCm);
      }
    } else {
      if (obstacleActive) {
        obstacleActive = false;
        digitalWrite(PIN_LED, LOW);
      }
    }
  }

  // 3. Periodic Telemetry Stream back to Raspberry Pi (every 100ms)
  if (now - lastTelemetrySend >= 100) {
    lastTelemetrySend = now;
    Serial.print("TELEMETRY,");
    Serial.print(currentDistanceCm);
    Serial.print(",");
    Serial.print((int)currentState);
    Serial.print(",");
    Serial.println(obstacleActive ? 1 : 0);
  }

  // 4. Update motor outputs and turn timing
  updateState();
}

void executeCommand(char cmd) {
  // If obstacle is active, refuse forward movement commands
  if (obstacleActive && (cmd == 'F' || cmd == 'f')) {
    Serial.println("ERR:PATH_BLOCKED");
    return;
  }

  switch (cmd) {
    case 'F': // Move Forward
    case 'f':
      currentState = STATE_FORWARD;
      break;

    case 'S': // Emergency Brake / Stop
    case 's':
      currentState = STATE_STOP;
      break;

    case 'B': // Reverse
    case 'b':
      currentState = STATE_REVERSE;
      break;

    case 'L': // Nudge Turn Left
    case 'l':
      previousDriveState = (currentState == STATE_FORWARD) ? STATE_FORWARD : STATE_STOP;
      currentState = STATE_TURNING_LEFT;
      turnStartTime = millis();
      break;

    case 'R': // Nudge Turn Right
    case 'r':
      previousDriveState = (currentState == STATE_FORWARD) ? STATE_FORWARD : STATE_STOP;
      currentState = STATE_TURNING_RIGHT;
      turnStartTime = millis();
      break;

    default:
      break;
  }
}

void updateState() {
  unsigned long now = millis();

  switch (currentState) {
    case STATE_STOP:
      setMotorOutputs(0, 0, 0, 0);
      break;

    case STATE_FORWARD:
      if (obstacleActive) {
        setMotorOutputs(0, 0, 0, 0);
      } else {
        setMotorOutputs(1, SPEED_NORMAL, 1, SPEED_NORMAL);
      }
      break;

    case STATE_REVERSE:
      setMotorOutputs(-1, SPEED_NORMAL, -1, SPEED_NORMAL);
      break;

    case STATE_TURNING_LEFT:
      // Turn left: right side moves fast forward, left side slow forward
      setMotorOutputs(1, SPEED_TURN_SLOW, 1, SPEED_TURN_FAST);
      if (now - turnStartTime >= TURN_DURATION_MS) {
        currentState = previousDriveState; // Return to previous state
      }
      break;

    case STATE_TURNING_RIGHT:
      // Turn right: left side moves fast forward, right side slow forward
      setMotorOutputs(1, SPEED_TURN_FAST, 1, SPEED_TURN_SLOW);
      if (now - turnStartTime >= TURN_DURATION_MS) {
        currentState = previousDriveState; // Return to previous state
      }
      break;
  }
}

// Controls L298N H-Bridge
// Direction: 1 = Forward, -1 = Reverse, 0 = Brake
void setMotorOutputs(int leftDir, int leftSpeed, int rightDir, int rightSpeed) {
  // Left Motor Group
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

  // Right Motor Group
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

// Measures distance via HC-SR04 in centimeters
int measureDistance() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  // 25ms timeout (~4.3m max distance)
  long duration = pulseIn(PIN_ECHO, HIGH, 25000);
  if (duration <= 0) return -1;
  return (int)(duration * 0.0343 / 2.0);
}
