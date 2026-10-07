/*
 * ======================================================================================
 * EOG + Piezo Sensor - Serial Monitor Test
 * ======================================================================================
 * Reads raw values from:
 *   - AD8232 EOG sensor on A0
 *   - MEAS Piezo vibration sensor on A1
 *
 * Open Serial Monitor at 9600 baud to see live readings.
 * ======================================================================================
 */

// --- PIN DEFINITIONS ---
const int PIN_EOG    = A0;   // AD8232 analog output
const int PIN_PIEZO  = A1;   // Piezo vibration sensor
const int PIN_LO_MINUS = 2;  // AD8232 Lead-Off detect (-)
const int PIN_LO_PLUS  = 3;  // AD8232 Lead-Off detect (+)

// --- THRESHOLDS (adjust based on your readings) ---
const int PIEZO_THRESHOLD  = 350;  // Spike above this = jaw clench detected
const int EOG_LEFT_THRESH  = 120;  // Delta above baseline = Left glance
const int EOG_RIGHT_THRESH = 120;  // Delta below baseline = Right glance

// --- Baseline (captured at startup) ---
int eogBaseline = 512;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_LO_MINUS, INPUT);
  pinMode(PIN_LO_PLUS, INPUT);

  Serial.println("==============================");
  Serial.println("  EOG + Piezo Sensor Test");
  Serial.println("==============================");
  Serial.println("Calibrating EOG baseline...");
  Serial.println(">>> Look STRAIGHT AHEAD for 2 seconds...");
  delay(1000);

  // Capture resting EOG baseline (2 sec average)
  long sum = 0;
  for (int i = 0; i < 200; i++) {
    sum += analogRead(PIN_EOG);
    delay(10);
  }
  eogBaseline = (int)(sum / 200);

  Serial.print("Baseline captured: ");
  Serial.println(eogBaseline);
  Serial.println("------------------------------");
  Serial.println("FORMAT: EOG_RAW | DELTA | PIEZO | STATUS");
  Serial.println("------------------------------");
  delay(500);
}

void loop() {

  // --- Read Sensors ---
  int eogRaw   = analogRead(PIN_EOG);
  int piezoRaw = analogRead(PIN_PIEZO);
  int delta    = eogRaw - eogBaseline;

  // --- Lead-Off Detection ---
  bool leadOff = (digitalRead(PIN_LO_PLUS) == 1 || digitalRead(PIN_LO_MINUS) == 1);

  // --- Determine Status ---
  String status = "---";

  if (leadOff) {
    status = "!! ELECTRODES DISCONNECTED";
  } else if (piezoRaw > PIEZO_THRESHOLD) {
    status = "JAW CLENCH DETECTED!";
  } else if (delta > EOG_LEFT_THRESH) {
    status = "<<< LEFT GLANCE";
  } else if (delta < -EOG_RIGHT_THRESH) {
    status = "RIGHT GLANCE >>>";
  }

  // --- Print to Serial Monitor ---
  Serial.print("EOG: ");
  Serial.print(eogRaw);
  Serial.print("\t| Delta: ");
  Serial.print(delta);
  Serial.print("\t| Piezo: ");
  Serial.print(piezoRaw);
  Serial.print("\t| ");
  Serial.println(status);

  delay(100); // 10 Hz - easy to read in Serial Monitor
}
