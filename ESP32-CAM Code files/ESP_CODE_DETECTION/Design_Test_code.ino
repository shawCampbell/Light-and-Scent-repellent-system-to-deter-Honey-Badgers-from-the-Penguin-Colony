#include <Wire.h>
#include <BH1750.h>

// ESP32-CAM I2C pins for the light sensor
#define I2C_SDA 14
#define I2C_SCL 15

// Sensor and control pins
#define POWER_CONTROL_PIN 16  // Transistor controlling sensor power
#define PIR_PIN 12           // PIR motion sensor input
#define IR_BREAK_PIN 2       // IR break beam sensor input
#define FLASH_PIN 4          // Onboard flash LED
#define EXT_LED_PIN 13       // Motion detected LED indicator

// Light thresholds (lux)
const float DARK_THRESHOLD = 20.0;   // Activate system below this (Nighttime)
const float LIGHT_THRESHOLD = 100.0; // Deactivate system above this (Daytime)

// PIR sensor settings
const unsigned long PIR_WARMUP_MS = 1000; // 1s warmup time
const unsigned long PIR_TRIGGER_DURATION = 5000; // 5s trigger duration

BH1750 lightMeter;
unsigned long pirActivationTime = 0;
bool systemActive = false;
bool pirTriggered = false;
unsigned long lastPirTrigger = 0;

void setup() {
  Serial.begin(115200);
  delay(1000); // Stabilization delay
  
  // Initialize I2C
  Wire.begin(I2C_SDA, I2C_SCL);
  
  // Initialize light sensor
  if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
    Serial.println("BH1750 initialized");
  } else {
    Serial.println("BH1750 failed!");
    while(1); // Halt if sensor fails
  }

  // Configure pins
  pinMode(POWER_CONTROL_PIN, OUTPUT);
  pinMode(PIR_PIN, INPUT);
  pinMode(IR_BREAK_PIN, INPUT);
  pinMode(FLASH_PIN, OUTPUT);
  pinMode(EXT_LED_PIN, OUTPUT);
  
  // Initial state
  digitalWrite(POWER_CONTROL_PIN, LOW);
  digitalWrite(FLASH_PIN, LOW);
  digitalWrite(EXT_LED_PIN, LOW);
  
  Serial.println("SYSTEM READY");
}

void loop() {
  // Read light level
  float lux = lightMeter.readLightLevel();
  
  if (isnan(lux)) {
    Serial.println("Light sensor error!");
    delay(1000);
    return;
  }
  
  Serial.print("Light: ");
  Serial.print(lux);
  Serial.println(" lx");

  // System power management
  if (lux < DARK_THRESHOLD && !systemActive) {
    // Activate sensor system
    digitalWrite(POWER_CONTROL_PIN, HIGH);
    systemActive = true;
    pirActivationTime = millis();
    Serial.println("SYSTEM ON - Dark conditions");
    Serial.println("PIR sensor warming up...");
    delay(1000); // Initial delay for power stabilization
  } 
  else if (lux > LIGHT_THRESHOLD && systemActive) {
    // Deactivate sensor system
    digitalWrite(POWER_CONTROL_PIN, LOW);
    digitalWrite(FLASH_PIN, LOW);
    digitalWrite(EXT_LED_PIN, LOW);
    systemActive = false;
    pirTriggered = false;
    Serial.println("SYSTEM OFF - Bright conditions");
  }

  // Sensor processing when active
  if (systemActive) {
    // Check if PIR has warmed up (needs 30-60s after power on)
    if (millis() - pirActivationTime > PIR_WARMUP_MS) {
      // Read PIR sensor (active HIGH when motion detected)
      bool currentPirState = digitalRead(PIR_PIN) == HIGH;
      
      // Detect new motion
      if (currentPirState && !pirTriggered) {
        pirTriggered = true;
        lastPirTrigger = millis();
        digitalWrite(FLASH_PIN, HIGH);
        Serial.println("MOTION DETECTED - Flash ON");
      }
      
      // Read IR break beam (now HIGH when beam is broken)
      bool beamBroken = digitalRead(IR_BREAK_PIN) == HIGH;
      
      // Control external LED based on both sensors
      if (pirTriggered && beamBroken) {
        digitalWrite(EXT_LED_PIN, HIGH);
        Serial.println("DUAL TRIGGER - External LED ON");
        Serial.println("Capturing image!");
      } else {
        digitalWrite(EXT_LED_PIN, LOW);
      }
      
      // Reset PIR trigger after duration
      if (pirTriggered && (millis() - lastPirTrigger > PIR_TRIGGER_DURATION)) {
        pirTriggered = false;
        digitalWrite(FLASH_PIN, LOW);
        Serial.println("MOTION TIMEOUT - Flash OFF");
      }
    }
  }

  delay(2000); // Main loop delay
}