/*
 * ======================================================================================
 * OcuSteer - Signal Processing Unit (Arduino Uno #1)
 * --------------------------------------------------------------------------------------
 * Dual-Modal Biosignal Processor:
 *  1. Electrooculography (EOG) via AD8232 on A0 (Horizontal Left/Right Glances)
 *  2. Mechanical Jaw Clench via MEAS Piezo Vibration Sensor on A1 (Start/Stop)
 *
 * Output Protocol (UART 9600 baud to Motor Controller):
 *  0x01 = TURN LEFT
 *  0x02 = TURN RIGHT
 *  0x03 = STOP / BRAKE
 *  0x04 = FORWARD / GO
 * ======================================================================================
 */

// --- PIN DEFINITIONS ---
const int PIN_EOG_INPUT       = A0;  // AD8232 Output
const int PIN_PIEZO_INPUT     = A1;  // MEAS Piezo sensor
const int PIN_LO_MINUS        = 2;   // AD8232 Lead-Off negative detect
const int PIN_LO_PLUS         = 3;   // AD8232 Lead-Off positive detect
const int PIN_STATUS_LED      = 13;  // Onboard LED indicator

// --- COMMAND BYTE CONSTANTS ---
const uint8_t CMD_LEFT        = 0x01;
const uint8_t CMD_RIGHT       = 0x02;
const uint8_t CMD_STOP        = 0x03;
const uint8_t CMD_GO          = 0x04;
const uint8_t CMD_CALIBRATE   = 0x05;

// --- SIGNAL PROCESSING PARAMETERS ---
const unsigned long SAMPLE_INTERVAL_MS = 10;   // 100 Hz sampling rate
const int FILTER_WINDOW_SIZE           = 8;    // Moving average filter window
const unsigned long MIN_GLANCE_DUR_MS  = 160;  // Minimum duration for deliberate saccade
const unsigned long MAX_GLANCE_DUR_MS  = 600;  // Maximum duration (above this = electrode shift)
const unsigned long COOLDOWN_MS        = 400;  // Cooldown between successive commands
const unsigned long BLINK_WINDOW_MS    = 180;  // Artifact rejection window

// Default thresholds (dynamically updated during calibration)
int baselineEOG        = 512;
int leftThresholdDelta = 120;  // +delta above baseline for Left Glance
int rightThresholdDelta= 120;  // -delta below baseline for Right Glance
int piezoThreshold     = 350;  // Piezo spike threshold for jaw clench

// Circular buffer for moving average
int filterBuffer[FILTER_WINDOW_SIZE];
int filterIndex = 0;
long filterSum = 0;

// State tracking variables
unsigned long lastSampleTime   = 0;
unsigned long glanceStartTime  = 0;
unsigned long lastCommandTime  = 0;
unsigned long lastPiezoTime    = 0;
bool candidateLeft             = false;
bool candidateRight            = false;
bool sawOppositePolarity       = false; // For blink rejection
bool vehicleMoving             = false; // Local state tracker

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
  if (digitalRead(PIN_LO_PLUS) == 1 || digitalRead(PIN_LO_MINUS) == 1) {
    digitalWrite(PIN_STATUS_LED, LOW);
    // Electrodes off: safety reset
    candidateLeft = false;
    candidateRight = false;
    return;
  }

  // 1. Acquire filtered EOG and raw Piezo readings
  int filteredEOG = readFilteredEOG();
  int piezoVal = analogRead(PIN_PIEZO_INPUT);

  // 2. Jaw-Clench Detection (MEAS Piezo)
  // Jaw clenches provide an unambiguous binary toggle for GO / STOP
  if (piezoVal > piezoThreshold) {
    if (currentMillis - lastCommandTime > COOLDOWN_MS) {
      lastPiezoTime = currentMillis;
      vehicleMoving = !vehicleMoving;
      uint8_t cmd = vehicleMoving ? CMD_GO : CMD_STOP;
      transmitCommand(cmd);
      lastCommandTime = currentMillis;

      // Reset any active glance candidates to prevent cross-talk
      candidateLeft = false;
      candidateRight = false;
      return;
    }
  }

  // 3. Artifact Rejection: Suppress EOG if facial muscle / jaw movement happened recently
  if (currentMillis - lastPiezoTime < 150) {
    candidateLeft = false;
    candidateRight = false;
    return;
  }

  // 4. Horizontal EOG Saccade Detection
  int delta = filteredEOG - baselineEOG;

  // --- CANDIDATE DETECTION ---
  if (delta > leftThresholdDelta) {
    // Potential Left Glance
    if (!candidateLeft && !candidateRight) {
      candidateLeft = true;
      glanceStartTime = currentMillis;
      sawOppositePolarity = false;
    } else if (candidateRight) {
      // Swung from Right to Left rapidly -> Blink artifact!
      sawOppositePolarity = true;
    }
  } else if (delta < -rightThresholdDelta) {
    // Potential Right Glance
    if (!candidateRight && !candidateLeft) {
      candidateRight = true;
      glanceStartTime = currentMillis;
      sawOppositePolarity = false;
    } else if (candidateLeft) {
      // Swung from Left to Right rapidly -> Blink artifact!
      sawOppositePolarity = true;
    }
  } else {
    // Signal returned back to resting baseline zone
    if (candidateLeft || candidateRight) {
      unsigned long duration = currentMillis - glanceStartTime;

      // Validate duration and ensure it wasn't a biphasic blink artifact
      if (!sawOppositePolarity && duration >= MIN_GLANCE_DUR_MS && duration <= MAX_GLANCE_DUR_MS) {
        if (currentMillis - lastCommandTime > COOLDOWN_MS) {
          if (candidateLeft) {
            transmitCommand(CMD_LEFT);
          } else if (candidateRight) {
            transmitCommand(CMD_RIGHT);
          }
          lastCommandTime = currentMillis;
        }
      }

      // Reset candidate flags
      candidateLeft = false;
      candidateRight = false;
      sawOppositePolarity = false;
    }
  }

  // Slow adaptive baseline tracking when resting
  if (!candidateLeft && !candidateRight && abs(delta) < 40) {
    baselineEOG = (baselineEOG * 999 + filteredEOG) / 1000;
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
