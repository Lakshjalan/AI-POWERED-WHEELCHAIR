/*
 * ======================================================================================
 * OcuSteer - Signal Processing Unit (Arduino Uno #1)
 * --------------------------------------------------------------------------------------
 * Dual-Modal Biosignal Processor:
 *  1. Electrooculography (EOG) via AD8232 on A0 (Horizontal Left/Right Glances)
 *  2. Mechanical Jaw Clench via MEAS Piezo Vibration Sensor on A1 (Start/Stop)
 *
 * Output Protocol (UART 9600 baud to Motor Controller):
 *  CONTINUOUS GAZE STATE (sent every ~100ms):
 *   0x01 = GAZE LEFT   (user is currently looking left)
 *   0x02 = GAZE RIGHT  (user is currently looking right)
 *   0x03 = GAZE CENTER (user is looking straight ahead)
 *
 *  CLENCH EVENTS (sent once on detection):
 *   0x04 = STOP         (double-clench detected: two clenches within 800ms)
 *   0x05 = GO / START   (single clench with no second clench within 800ms)
 * ======================================================================================
 */

// --- PIN DEFINITIONS ---
const int PIN_EOG_INPUT       = A0;  // AD8232 Output
const int PIN_PIEZO_INPUT     = A1;  // MEAS Piezo sensor
const int PIN_LO_MINUS        = 2;   // AD8232 Lead-Off negative detect
const int PIN_LO_PLUS         = 3;   // AD8232 Lead-Off positive detect
const int PIN_STATUS_LED      = 13;  // Onboard LED indicator

// --- COMMAND BYTE CONSTANTS ---
const uint8_t CMD_GAZE_LEFT   = 0x01;
const uint8_t CMD_GAZE_RIGHT  = 0x02;
const uint8_t CMD_GAZE_CENTER = 0x03;
const uint8_t CMD_STOP        = 0x04;
const uint8_t CMD_GO          = 0x05;

// --- SIGNAL PROCESSING PARAMETERS ---
const unsigned long SAMPLE_INTERVAL_MS = 10;   // 100 Hz sampling rate
const int FILTER_WINDOW_SIZE           = 8;    // Moving average filter window
const unsigned long GAZE_REPORT_INTERVAL_MS = 100; // Report gaze state every 100ms

// Gaze hysteresis: require sustained delta before committing to LEFT/RIGHT
// Uses separate enter/exit thresholds to prevent oscillation at boundary
const unsigned long GAZE_CONFIRM_MS    = 80;   // Must sustain for 80ms before switching state
const unsigned long BLINK_WINDOW_MS    = 180;  // Artifact rejection window

// --- DOUBLE-CLENCH DETECTION PARAMETERS ---
const unsigned long CLENCH_DEBOUNCE_MS       = 300;  // Minimum gap between individual clenches
const unsigned long DOUBLE_CLENCH_WINDOW_MS  = 800;  // Max gap between two clenches to count as double
const unsigned long SINGLE_CLENCH_CONFIRM_MS = 900;  // Wait this long after 1st clench; if no 2nd, it's a single

// Default thresholds (dynamically updated during calibration)
int baselineEOG        = 512;
int leftThresholdDelta = 120;  // +delta above baseline for Left Gaze
int rightThresholdDelta= 120;  // -delta below baseline for Right Gaze
int piezoThreshold     = 350;  // Piezo spike threshold for jaw clench

// Circular buffer for moving average
int filterBuffer[FILTER_WINDOW_SIZE];
int filterIndex = 0;
long filterSum = 0;

// --- STATE TRACKING ---
unsigned long lastSampleTime     = 0;
unsigned long lastGazeReportTime = 0;
unsigned long lastPiezoTime      = 0;

// Current continuous gaze state
enum GazeState { GAZE_CENTER, GAZE_LEFT, GAZE_RIGHT };
GazeState currentGaze     = GAZE_CENTER;
GazeState candidateGaze   = GAZE_CENTER;
unsigned long candidateStartTime = 0;

// Clench state machine
unsigned long firstClenchTime  = 0;
bool awaitingSecondClench      = false;
bool singleClenchDispatched    = false;
bool vehicleMoving             = false;

// Function Prototypes
int readFilteredEOG();
void performAutoCalibration();
void transmitCommand(uint8_t cmd);

void setup() {
  Serial.begin(9600);
  pinMode(PIN_LO_MINUS, INPUT);
  pinMode(PIN_LO_PLUS, INPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  // Initialize filter buffer
  for (int i = 0; i < FILTER_WINDOW_SIZE; i++) {
    filterBuffer[i] = analogRead(PIN_EOG_INPUT);
    filterSum += filterBuffer[i];
    delay(5);
  }

  // Flash LED on startup
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_STATUS_LED, HIGH);
    delay(100);
    digitalWrite(PIN_STATUS_LED, LOW);
    delay(100);
  }

  // Calibrate initial resting baseline
  performAutoCalibration();
}

void loop() {
  unsigned long currentMillis = millis();

  // 100 Hz strict sampling rate
  if (currentMillis - lastSampleTime < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleTime = currentMillis;

  // Check if electrodes are disconnected (Lead-Off detection)
  bool leadsOff = (digitalRead(PIN_LO_PLUS) == 1 || digitalRead(PIN_LO_MINUS) == 1);
  if (leadsOff) {
    digitalWrite(PIN_STATUS_LED, LOW);
    currentGaze = GAZE_CENTER;
    candidateGaze = GAZE_CENTER;
  }

  // =====================================================================
  // 1. PIEZO JAW-CLENCH DETECTION (Double-Clench = STOP, Single = GO)
  // =====================================================================
  int piezoVal = analogRead(PIN_PIEZO_INPUT);

  if (piezoVal > piezoThreshold && (currentMillis - lastPiezoTime > CLENCH_DEBOUNCE_MS)) {
    lastPiezoTime = currentMillis;

    if (awaitingSecondClench) {
      // Second clench arrived within the window → DOUBLE-CLENCH → STOP
      awaitingSecondClench = false;
      singleClenchDispatched = false;
      vehicleMoving = false;
      transmitCommand(CMD_STOP);
    } else {
      // First clench detected, start waiting for a possible second
      firstClenchTime = currentMillis;
      awaitingSecondClench = true;
      singleClenchDispatched = false;
    }
  }

  // If we're waiting for a second clench and the window expires → it was a single clench → GO
  if (awaitingSecondClench && !singleClenchDispatched) {
    if (currentMillis - firstClenchTime > SINGLE_CLENCH_CONFIRM_MS) {
      awaitingSecondClench = false;
      singleClenchDispatched = false;
      vehicleMoving = true;
      transmitCommand(CMD_GO);
    }
  }

  // Suppress EOG processing briefly after piezo spike (artifact rejection)
  if (currentMillis - lastPiezoTime < BLINK_WINDOW_MS) {
    // Still report current gaze state even during suppression
    goto report_gaze;
  }

  // =====================================================================
  // 2. CONTINUOUS GAZE STATE DETECTION (EOG)
  // =====================================================================
  if (!leadsOff) {
    int filteredEOG = readFilteredEOG();
    int delta = filteredEOG - baselineEOG;

    // Determine instantaneous gaze direction from EOG delta
    GazeState instantGaze;
    if (delta > leftThresholdDelta) {
      instantGaze = GAZE_LEFT;
    } else if (delta < -rightThresholdDelta) {
      instantGaze = GAZE_RIGHT;
    } else {
      instantGaze = GAZE_CENTER;
    }

    // Hysteresis state machine: require sustained direction before committing
    if (instantGaze != currentGaze) {
      // Direction changed from current committed state
      if (instantGaze == candidateGaze) {
        // Same candidate direction sustained, check if long enough
        if (currentMillis - candidateStartTime >= GAZE_CONFIRM_MS) {
          currentGaze = candidateGaze;
        }
      } else {
        // New candidate direction, start timer
        candidateGaze = instantGaze;
        candidateStartTime = currentMillis;
      }
    } else {
      // Still in the same committed state, reset candidate
      candidateGaze = currentGaze;
    }

    // Slow adaptive baseline tracking when resting at center
    if (currentGaze == GAZE_CENTER && abs(delta) < 40) {
      baselineEOG = (baselineEOG * 999 + filteredEOG) / 1000;
    }
  }

  // =====================================================================
  // 3. PERIODIC GAZE STATE REPORT (every 100ms)
  // =====================================================================
report_gaze:
  if (currentMillis - lastGazeReportTime >= GAZE_REPORT_INTERVAL_MS) {
    lastGazeReportTime = currentMillis;

    uint8_t gazeCmd;
    switch (currentGaze) {
      case GAZE_LEFT:   gazeCmd = CMD_GAZE_LEFT;   break;
      case GAZE_RIGHT:  gazeCmd = CMD_GAZE_RIGHT;  break;
      default:          gazeCmd = CMD_GAZE_CENTER;  break;
    }
    transmitCommand(gazeCmd);
  }
}

// Moving Average Filter Implementation
int readFilteredEOG() {
  int raw = analogRead(PIN_EOG_INPUT);
  filterSum -= filterBuffer[filterIndex];
  filterBuffer[filterIndex] = raw;
  filterSum += raw;
  filterIndex = (filterIndex + 1) % FILTER_WINDOW_SIZE;
  return (int)(filterSum / FILTER_WINDOW_SIZE);
}

// Initial 2-second calibration routine while user looks straight
void performAutoCalibration() {
  digitalWrite(PIN_STATUS_LED, HIGH);
  long sum = 0;
  int samples = 200;

  for (int i = 0; i < samples; i++) {
    sum += analogRead(PIN_EOG_INPUT);
    delay(10);
  }

  baselineEOG = (int)(sum / samples);
  digitalWrite(PIN_STATUS_LED, LOW);
}

// Transmit command byte to MCU #2 and toggle status LED
void transmitCommand(uint8_t cmd) {
  digitalWrite(PIN_STATUS_LED, HIGH);
  Serial.write(cmd); // Sent across Serial TX to Arduino #2 RX
  delay(15);
  digitalWrite(PIN_STATUS_LED, LOW);
}
