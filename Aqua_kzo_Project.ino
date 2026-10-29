const int PUMP_RELAY_PIN = 7;
const int SOIL_PIN = A0;
const int TDS_PIN = A1;

unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 1000;

void setup() {
  Serial.begin(9600);
  
  // Active-HIGH Configuration: Force LOW to keep relay OFF on boot
  digitalWrite(PUMP_RELAY_PIN, LOW); 
  pinMode(PUMP_RELAY_PIN, OUTPUT);
}

void loop() {
  // 1. Send live sensor readings to Python
  if (millis() - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();
    int rawSoil = analogRead(SOIL_PIN);
    int rawTDS = analogRead(TDS_PIN);
    
    Serial.print("TELEMETRY:");
    Serial.print(rawSoil);
    Serial.print(",");
    Serial.println(rawTDS);
  }

  // 2. Listen for execution commands from Python
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command.startsWith("PUMP_ON:")) {
      float durationSeconds = command.substring(8).toFloat();
      unsigned long runTimeMs = (unsigned long)(durationSeconds * 1000.0);

      if (runTimeMs > 15000) runTimeMs = 15000; // 15s Safety clamp
      
      if (runTimeMs > 0) {
        Serial.println("ACK:PUMP_START"); 
        digitalWrite(PUMP_RELAY_PIN, HIGH); // Relay ON (Active-HIGH)
        delay(runTimeMs);
        digitalWrite(PUMP_RELAY_PIN, LOW);  // Relay OFF (Active-HIGH)
        Serial.println("ACK:PUMP_STOP");
      }
    }
    else if (command == "PUMP_OFF") {
      digitalWrite(PUMP_RELAY_PIN, LOW);   // Emergency lockout
      Serial.println("ACK:PUMP_EMERGENCY_STOP");
    }
  }
}