#include <DHT.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP085.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <time.h>
#include <math.h>

#define DHT_PIN 15
#define DHT_TYPE DHT22

// ---------------------------------------------------------------------
// Network / MQTT
// The topic and JSON structure MUST match backend/mqtt_subscriber.py
// (and simulator/simulator.py).
// ---------------------------------------------------------------------
const char *wifiSsid = "Wokwi-GUEST";
const char *wifiPassword = "";
const char *mqttBroker = "test.mosquitto.org";
const int mqttPort = 1883;
const char *mqttTopic = "digitaltwin/factory/machine01";
// Connection state: "online" when connected, "offline" if the broker loses us
// (MQTT Last Will, retained) - lets the platform detect a dead device at once.
const char *mqttStatusTopic = "digitaltwin/factory/machine01/status";
const int MACHINE_ID = 1;

const unsigned long PUBLISH_INTERVAL_MS = 3000;

// Set to false for a perfectly healthy machine (no Warning/Critical events).
const bool ENABLE_FAULT_EVENTS = true;

DHT dht(DHT_PIN, DHT_TYPE);
Adafruit_MPU6050 mpu;
Adafruit_BMP085 bmp;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

bool mpuReady = false;
bool bmpReady = false;
unsigned long lastPublish = 0;

// Last good readings, used if a sensor momentarily fails (e.g. DHT22 NaN).
float lastAmbientTemperature = 24.0;
float lastAmbientHumidity = 40.0;
float lastAmbientPressure = 1013.25;

// =====================================================================
// BEGIN TWIN MODEL
// Digital Twin variation layer. Wokwi's virtual sensors stay almost
// perfectly still, so the twin varies realistically AROUND what the real
// sensors read (move the DHT22 / MPU6050 / BMP180 sliders in Wokwi and
// the output follows). Keep in sync with simulator/simulator.py.
// =====================================================================

const float FAULT_CYCLE_SECONDS = 120.0;

// Smooth half-sine bump: 0 -> peak -> 0 between start and start+duration.
float twinPulse(float phase, float start, float duration, float peak) {
  if (phase < start || phase >= start + duration) {
    return 0.0;
  }
  return peak * sinf(PI * (phase - start) / duration);
}

// Random value in [-amplitude, +amplitude].
float twinNoise(float amplitude) {
  return (random(-1000, 1001) / 1000.0) * amplitude;
}

void twinValues(
  float t,
  float ambientT, float ambientH, float ambientP, float jolt,
  bool faults,
  float &temperature, float &humidity, float &vibration, float &pressure
) {
  float phase = fmodf(t, FAULT_CYCLE_SECONDS);

  float bearingWear    = faults ? twinPulse(phase, 40, 20, 5.5)   : 0.0;  // vibration
  float overheating    = faults ? twinPulse(phase, 80, 24, 17.0)  : 0.0;  // temperature
  float coolantLeak    = faults ? twinPulse(phase, 80, 24, 18.0)  : 0.0;  // humidity
  float pressureSurge  = faults ? twinPulse(phase, 108, 10, 50.0) : 0.0;  // pressure

  temperature = ambientT + 3.0 + 4.0 * sinf(t / 12.0) + twinNoise(1.0) + overheating;
  humidity    = ambientH + 15.0 + 15.0 * sinf(t / 15.0) + twinNoise(2.0) + coolantLeak;
  vibration   = jolt + 2.5 + 1.5 * sinf(t / 5.0) + twinNoise(0.8) + bearingWear;
  pressure    = ambientP + 5.0 * sinf(t / 20.0) + twinNoise(1.0) + pressureSurge;

  temperature = constrain(temperature, -40.0, 80.0);   // DHT22 range
  humidity    = constrain(humidity, 0.0, 100.0);
  vibration   = constrain(vibration, 0.0, 20.0);
  pressure    = constrain(pressure, 300.0, 1100.0);    // BMP180 range
}

// =====================================================================
// END TWIN MODEL
// =====================================================================

void connectWiFi() {
  Serial.println("Connecting to WiFi...");

  WiFi.begin(wifiSsid, wifiPassword);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected!");

  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  while (!mqttClient.connected()) {

    Serial.println("Connecting to MQTT...");

    String clientId =
      "ESP32-DigitalTwin-" +
      String((uint32_t)ESP.getEfuseMac(), HEX);

    if (mqttClient.connect(
          clientId.c_str(),
          mqttStatusTopic, 1, true, "offline")) {   // Last Will: retained "offline"
      Serial.println("MQTT connected!");
      mqttClient.publish(mqttStatusTopic, "online", true);   // retained
    }
    else {
      Serial.print("MQTT connection failed, state: ");
      Serial.println(mqttClient.state());
      delay(2000);
    }
  }
}

// Writes an ISO-8601 UTC timestamp. Returns false until NTP has synced.
bool getIsoTimestamp(char *buffer, size_t length) {
  struct tm timeInfo;

  if (!getLocalTime(&timeInfo, 1000)) {
    return false;
  }

  strftime(buffer, length, "%Y-%m-%dT%H:%M:%SZ", &timeInfo);
  return true;
}

void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("====================================");
  Serial.println("       DIGITAL TWIN FACTORY");
  Serial.println("====================================");

  dht.begin();

  Serial.println("DHT22 TEST STARTED");

  Wire.begin(21, 22);

  if (!mpu.begin()) {
    Serial.println("MPU6050 FAILED");
  }
  else {
    mpuReady = true;
    Serial.println("MPU6050 OK");
  }

  if (!bmp.begin()) {
    Serial.println("BMP180 FAILED");
  }
  else {
    bmpReady = true;
    Serial.println("BMP180 OK");
  }

  // Makes every simulation run slightly different.
  randomSeed(micros());

  connectWiFi();

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");

  mqttClient.setServer(mqttBroker, mqttPort);
  mqttClient.setBufferSize(512);
  mqttClient.setKeepAlive(30);

  connectMQTT();
}

void loop() {

  // -----------------------------------------
  // Keep WiFi + MQTT alive
  // -----------------------------------------

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!mqttClient.connected()) {
    connectMQTT();
  }

  mqttClient.loop();

  // -----------------------------------------
  // Publish every PUBLISH_INTERVAL_MS
  // -----------------------------------------

  if (millis() - lastPublish < PUBLISH_INTERVAL_MS) {
    delay(10);
    return;
  }

  lastPublish = millis();

  // =====================================================
  // 1. READ THE REAL (VIRTUAL) SENSORS
  // =====================================================

  float ambientTemperature = dht.readTemperature();
  float ambientHumidity = dht.readHumidity();

  if (isnan(ambientTemperature)) {
    Serial.println("DHT22 temperature read failed - using last good value");
    ambientTemperature = lastAmbientTemperature;
  }
  else {
    lastAmbientTemperature = ambientTemperature;
  }

  if (isnan(ambientHumidity)) {
    Serial.println("DHT22 humidity read failed - using last good value");
    ambientHumidity = lastAmbientHumidity;
  }
  else {
    lastAmbientHumidity = ambientHumidity;
  }

  // Vibration = how far the acceleration magnitude is from 1 g.
  // A still MPU6050 reads ~9.81 m/s^2, i.e. zero vibration.
  float jolt = 0.0;

  if (mpuReady) {

    sensors_event_t accel;
    sensors_event_t gyro;
    sensors_event_t temp;

    mpu.getEvent(&accel, &gyro, &temp);

    float ax = accel.acceleration.x;
    float ay = accel.acceleration.y;
    float az = accel.acceleration.z;

    jolt = fabsf(sqrtf(ax * ax + ay * ay + az * az) - 9.80665);
  }

  float ambientPressure = lastAmbientPressure;

  if (bmpReady) {
    float reading = bmp.readPressure() / 100.0;

    if (reading >= 300.0 && reading <= 1100.0) {
      ambientPressure = reading;
      lastAmbientPressure = reading;
    }
    else {
      Serial.println("BMP180 pressure out of range - using last good value");
    }
  }

  // =====================================================
  // 2. DIGITAL TWIN VARIATION AROUND THOSE READINGS
  // =====================================================

  float temperature;
  float humidity;
  float vibration;
  float pressure;

  twinValues(
    millis() / 1000.0,
    ambientTemperature, ambientHumidity, ambientPressure, jolt,
    ENABLE_FAULT_EVENTS,
    temperature, humidity, vibration, pressure
  );

  // =====================================================
  // 3. PRINT
  // =====================================================

  Serial.println();
  Serial.println("------------------------------------");

  Serial.printf(
    "Raw sensors   : %.2f C, %.2f %%, jolt %.2f, %.2f hPa\n",
    ambientTemperature, ambientHumidity, jolt, ambientPressure
  );

  Serial.print("Temperature: ");
  Serial.print(temperature, 2);
  Serial.println(" C");

  Serial.print("Humidity: ");
  Serial.print(humidity, 2);
  Serial.println(" %");

  Serial.print("Vibration: ");
  Serial.println(vibration, 2);

  Serial.print("Pressure: ");
  Serial.print(pressure, 2);
  Serial.println(" hPa");

  // =====================================================
  // 4. CREATE JSON  (structure shared with the subscriber)
  // =====================================================

  char timestamp[32];
  bool hasTime = getIsoTimestamp(timestamp, sizeof(timestamp));

  char payload[256];

  int written = snprintf(
    payload,
    sizeof(payload),
    "{\"machine_id\":%d,"
    "\"temperature\":%.2f,"
    "\"humidity\":%.2f,"
    "\"vibration\":%.2f,"
    "\"pressure\":%.2f,"
    "\"timestamp\":%s%s%s}",
    MACHINE_ID,
    temperature,
    humidity,
    vibration,
    pressure,
    hasTime ? "\"" : "",
    hasTime ? timestamp : "null",
    hasTime ? "\"" : ""
  );

  if (written < 0 || written >= (int)sizeof(payload)) {
    Serial.println("Payload too large - skipping publish");
    return;
  }

  // =====================================================
  // 5. MQTT PUBLISH
  // =====================================================

  Serial.println();
  Serial.print("Publishing: ");
  Serial.println(payload);

  if (mqttClient.publish(mqttTopic, payload)) {
    Serial.println("MQTT -> Data published successfully!");
  }
  else {
    Serial.println("MQTT -> Data publish failed!");
  }

  Serial.println("------------------------------------");
}
