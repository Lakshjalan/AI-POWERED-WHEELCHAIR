/*
 * ======================================================================================
 * OcuSteer - ESP32 Motor Controller (WiFi-Enabled)
 * --------------------------------------------------------------------------------------
 * Runs on ESP32 DevKit V1 mounted on the car chassis.
 * Receives driving commands over WiFi (HTTP) from the Laptop Hub.
 *
 * Wired to:
 *   1. L298N Dual H-Bridge Motor Driver (4 DC Motors, Differential Steering)
 *   2. HC-SR04 Ultrasonic Distance Sensor (future, pins reserved)
 *
 * WiFi HTTP API:
 *   GET /control?cmd=L   → Turn left  (continuous, persists until F or S)
 *   GET /control?cmd=R   → Turn right (continuous, persists until F or S)
 *   GET /control?cmd=F   → Forward    (resume straight)
 *   GET /control?cmd=S   → Stop       (full stop)
 *   GET /control?cmd=B   → Reverse
 *   GET /telemetry       → JSON: {"state":"...", "distance_cm":..., "obstacle":...}
 *   GET /                → Health check
 * ======================================================================================
 */

#include <WiFi.h>
#include <WebServer.h>

// =======================
// WIFI CONFIGURATION
// =======================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";     // <<< CHANGE THIS
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";  // <<< CHANGE THIS

// =======================
// PIN DEFINITIONS
// =======================
// L298N Motor Driver Pins (ESP32 GPIO)
const int PIN_ENA = 25;   // Left Motors PWM Speed
const int PIN_IN1 = 26;   // Left Motors Direction 1
const int PIN_IN2 = 27;   // Left Motors Direction 2
const int PIN_IN3 = 14;   // Right Motors Direction 1
const int PIN_IN4 = 12;   // Right Motors Direction 2
const int PIN_ENB = 13;   // Right Motors PWM Speed

// HC-SR04 Ultrasonic Sensor (reserved for future use)
const int PIN_TRIG = 32;
const int PIN_ECHO = 33;

// Built-in LED
const int PIN_LED = 2;    // ESP32 DevKit V1 onboard LED

// =======================
// LEDC PWM CONFIGURATION
// =======================
// Compatible with both ESP32 Core 2.x and 3.x
const int LEDC_FREQ       = 5000;  // 5 kHz PWM frequency
const int LEDC_RESOLUTION = 8;     // 8-bit resolution (0-255)
const int LEDC_CH_ENA     = 0;     // LEDC channel for left motors (Core 2.x)
const int LEDC_CH_ENB     = 1;     // LEDC channel for right motors (Core 2.x)

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  #define ATTACH_PWM_LEFT()  ledcAttach(PIN_ENA, LEDC_FREQ, LEDC_RESOLUTION)
  #define ATTACH_PWM_RIGHT() ledcAttach(PIN_ENB, LEDC_FREQ, LEDC_RESOLUTION)
  #define WRITE_PWM_LEFT(v)  ledcWrite(PIN_ENA, (v))
  #define WRITE_PWM_RIGHT(v) ledcWrite(PIN_ENB, (v))
#else
  #define ATTACH_PWM_LEFT()  do { ledcSetup(LEDC_CH_ENA, LEDC_FREQ, LEDC_RESOLUTION); ledcAttachPin(PIN_ENA, LEDC_CH_ENA); } while(0)
  #define ATTACH_PWM_RIGHT() do { ledcSetup(LEDC_CH_ENB, LEDC_FREQ, LEDC_RESOLUTION); ledcAttachPin(PIN_ENB, LEDC_CH_ENB); } while(0)
  #define WRITE_PWM_LEFT(v)  ledcWrite(LEDC_CH_ENA, (v))
  #define WRITE_PWM_RIGHT(v) ledcWrite(LEDC_CH_ENB, (v))
#endif

// =======================
// MOTOR SPEEDS (0-255)
// =======================
const int SPEED_NORMAL     = 180;   // Cruising PWM
const int SPEED_TURN_FAST  = 210;   // Outer wheel PWM during turn
const int SPEED_TURN_SLOW  = 60;    // Inner wheel PWM during turn
const int SAFE_DISTANCE_CM = 30;    // Obstacle safety threshold

// =======================
// STATE MACHINE
// =======================
enum CarState { STATE_STOP, STATE_FORWARD, STATE_REVERSE, STATE_TURNING_LEFT, STATE_TURNING_RIGHT };
CarState currentState = STATE_STOP;

unsigned long lastDistanceCheck  = 0;
unsigned long lastCommandTime    = 0;
int currentDistanceCm            = 999;
bool obstacleActive              = false;

// Watchdog: auto-stop if no command received within timeout
const unsigned long COMMAND_TIMEOUT_MS = 2000;

// Web Server on port 80
WebServer server(80);

// =======================
// FUNCTION PROTOTYPES
// =======================
void setMotorOutputs(int leftDir, int leftSpeed, int rightDir, int rightSpeed);
int measureDistance();
void executeCommand(char cmd);
void updateMotors();

// =======================
// HTTP ROUTE HANDLERS
// =======================

void handleRoot() {
  server.send(200, "application/json",
    "{\"service\":\"OcuSteer ESP32 Car Controller\","
    "\"status\":\"online\","
    "\"control\":\"/control?cmd=[F|S|L|R|B]\","
    "\"telemetry\":\"/telemetry\"}"
  );
}

void handleControl() {
  if (!server.hasArg("cmd")) {
    server.send(400, "application/json", "{\"error\":\"Missing cmd parameter\"}");
    return;
  }

  String cmdStr = server.arg("cmd");
  if (cmdStr.length() == 0) {
    server.send(400, "application/json", "{\"error\":\"Empty cmd\"}");
    return;
  }

  char cmd = cmdStr.charAt(0);
  executeCommand(cmd);
  lastCommandTime = millis();

  // Build response
  String stateStr;
  switch (currentState) {
    case STATE_STOP:          stateStr = "STOP"; break;
    case STATE_FORWARD:       stateStr = "FORWARD"; break;
    case STATE_REVERSE:       stateStr = "REVERSE"; break;
    case STATE_TURNING_LEFT:  stateStr = "LEFT"; break;
    case STATE_TURNING_RIGHT: stateStr = "RIGHT"; break;
  }

  server.send(200, "application/json",
    "{\"status\":\"ok\",\"command\":\"" + String(cmd) + "\",\"car_state\":\"" + stateStr + "\"}"
  );
}

void handleTelemetry() {
  String stateStr;
  switch (currentState) {
    case STATE_STOP:          stateStr = "STOP"; break;
    case STATE_FORWARD:       stateStr = "FORWARD"; break;
    case STATE_REVERSE:       stateStr = "REVERSE"; break;
    case STATE_TURNING_LEFT:  stateStr = "LEFT"; break;
    case STATE_TURNING_RIGHT: stateStr = "RIGHT"; break;
  }

  String json = "{";
  json += "\"distance_cm\":" + String(currentDistanceCm) + ",";
  json += "\"car_state\":\"" + stateStr + "\",";
  json += "\"obstacle_active\":" + String(obstacleActive ? "true" : "false") + ",";
  json += "\"uptime_ms\":" + String(millis());
  json += "}";

  server.send(200, "application/json", json);
}

// =======================
// SETUP
// =======================
void setup() {
  Serial.begin(115200);
  Serial.println("\n[OcuSteer] ESP32 Motor Controller Starting...");

  // Motor Driver Pins
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  pinMode(PIN_LED, OUTPUT);

  // Configure LEDC PWM channels for motor speed control
  ATTACH_PWM_LEFT();
  ATTACH_PWM_RIGHT();

  // Ultrasonic (reserved)
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);

  // Stop motors initially
  setMotorOutputs(0, 0, 0, 0);

  // Connect to WiFi
  Serial.print("[WiFi] Connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Blink LED while connecting
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
    digitalWrite(PIN_LED, HIGH);
  } else {
    Serial.println("\n[WiFi] Connection FAILED. Running in offline mode.");
    digitalWrite(PIN_LED, LOW);
  }

  // Register HTTP routes
  server.on("/", handleRoot);
  server.on("/control", handleControl);
  server.on("/telemetry", handleTelemetry);
  server.begin();

  Serial.println("[OcuSteer] ESP32 HTTP Server started on port 80");
  lastCommandTime = millis();
}

// =======================
// MAIN LOOP
// =======================
void loop() {
  // Handle incoming HTTP requests
  server.handleClient();

  unsigned long now = millis();

  // Ultrasonic Safety Check (every 80ms) — ready for when sensor is wired
  if (now - lastDistanceCheck >= 80) {
    lastDistanceCheck = now;
    currentDistanceCm = measureDistance();

    if (currentDistanceCm > 0 && currentDistanceCm < SAFE_DISTANCE_CM) {
      if (!obstacleActive) {
        obstacleActive = true;
        // Emergency brake
        if (currentState != STATE_STOP && currentState != STATE_REVERSE) {
          currentState = STATE_STOP;
          setMotorOutputs(0, 0, 0, 0);
        }
        digitalWrite(PIN_LED, HIGH);
        Serial.println("[SAFETY] Obstacle detected! Emergency brake.");
      }
    } else {
      if (obstacleActive) {
        obstacleActive = false;
        digitalWrite(PIN_LED, LOW);
        Serial.println("[SAFETY] Obstacle cleared.");
      }
    }
  }

  // Watchdog: auto-stop if no command received within timeout
  if (currentState != STATE_STOP && (now - lastCommandTime > COMMAND_TIMEOUT_MS)) {
    Serial.println("[WATCHDOG] No command received, auto-stopping.");
    currentState = STATE_STOP;
    setMotorOutputs(0, 0, 0, 0);
  }

  // Update motor outputs based on current state
  updateMotors();
}

// =======================
// COMMAND EXECUTION
// =======================
void executeCommand(char cmd) {
  // Block forward/turn commands if obstacle is active
  if (obstacleActive && (cmd == 'F' || cmd == 'f' || cmd == 'L' || cmd == 'l' || cmd == 'R' || cmd == 'r')) {
    Serial.println("[CMD] Blocked: obstacle active");
    return;
  }

  switch (cmd) {
    case 'F': case 'f':
      currentState = STATE_FORWARD;
      Serial.println("[CMD] FORWARD");
      break;

    case 'S': case 's':
      currentState = STATE_STOP;
      Serial.println("[CMD] STOP");
      break;

    case 'B': case 'b':
      currentState = STATE_REVERSE;
      Serial.println("[CMD] REVERSE");
      break;

    case 'L': case 'l':
      // Turn left CONTINUOUSLY — persists until F or S
      currentState = STATE_TURNING_LEFT;
      Serial.println("[CMD] TURN LEFT (continuous)");
      break;

    case 'R': case 'r':
      // Turn right CONTINUOUSLY — persists until F or S
      currentState = STATE_TURNING_RIGHT;
      Serial.println("[CMD] TURN RIGHT (continuous)");
      break;

    default:
      Serial.print("[CMD] Unknown: ");
      Serial.println(cmd);
      break;
  }
}

// =======================
// MOTOR STATE MACHINE
// =======================
void updateMotors() {
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
      // Turn left CONTINUOUSLY: right side fast, left side slow
      // No auto-revert — persists until CENTER gaze sends 'F' or double-clench sends 'S'
      setMotorOutputs(1, SPEED_TURN_SLOW, 1, SPEED_TURN_FAST);
      break;

    case STATE_TURNING_RIGHT:
      // Turn right CONTINUOUSLY: left side fast, right side slow
      // No auto-revert — persists until CENTER gaze sends 'F' or double-clench sends 'S'
      setMotorOutputs(1, SPEED_TURN_FAST, 1, SPEED_TURN_SLOW);
      break;
  }
}

// =======================
// LOW-LEVEL MOTOR CONTROL
// =======================
// dir: 1 = Forward, -1 = Reverse, 0 = Brake
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
  WRITE_PWM_LEFT(constrain(leftSpeed, 0, 255));

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
  WRITE_PWM_RIGHT(constrain(rightSpeed, 0, 255));
}

// =======================
// ULTRASONIC DISTANCE
// =======================
int measureDistance() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  long duration = pulseIn(PIN_ECHO, HIGH, 25000);
  if (duration <= 0) return -1;
  return (int)(duration * 0.0343 / 2.0);
}
