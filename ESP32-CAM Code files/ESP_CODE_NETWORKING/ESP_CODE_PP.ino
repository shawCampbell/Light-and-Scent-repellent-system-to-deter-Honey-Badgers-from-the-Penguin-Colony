#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiServer.h>
#include "esp_wpa2.h"
#include <ArduinoJson.h>
#include "esp_camera.h"

// Camera pins (adjust for your ESP32-CAM model)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

struct PeerInfo {
  String userID;
  String ipAddress;
  int portNumber;
};

const int MAX_PEERS = 10;
PeerInfo peers[MAX_PEERS];
int peerCount = 0;

// Wi-Fi Credentials
const char* ssid = "eduroam";
const char* username = "CMPSHA009@wf.uct.ac.za";
const char* password = "5thDegreePolynomial";

// Server settings
const char* serverIP = "197.239.167.94";//"196.47.241.166";//"196.47.245.58";
const int udpPort = 1234;
const int serverTcpPort = 1235;
const int peerListenPort = 1235;  // Port to listen for forwarded images from peers
WiFiUDP udp;
WiFiClient tcpClient;
WiFiServer peerServer(peerListenPort);  // Server for peer connections

// Device info
const char* userID = "ESP32-CAM-001";
bool detectionEvent = false;
unsigned long lastPingTime = 0;
unsigned long lastDetectionTime = 0;
const long pingInterval = 5000;

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Initialize camera
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Init with high specs for quality
  if(psramFound()){
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }
  
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  connectToWiFi();
  registerWithServer();
  
  // Start TCP server for peer connections
  peerServer.begin();
  Serial.printf("Listening for peer connections on port %d\n", peerListenPort);
  
  lastPingTime = millis();
}

void loop() {
  // Simulate detection event (replace with your actual detection logic)
  if (millis() - lastDetectionTime > 30000 && !detectionEvent) {  // After 30 seconds for testing
    detectionEvent = true;
    lastDetectionTime = millis();
  }

  if (detectionEvent) {
    handleDetection();
    detectionEvent = false;
  }

  // Regular pinging
  if (millis() - lastPingTime >= pingInterval) {
    sendPing();
    lastPingTime = millis();
  }
  
  // Handle incoming peer connections
  handlePeerConnections();
  
  delay(100);
}

void connectToWiFi() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_STA);
  
  esp_wifi_sta_wpa2_ent_set_identity((uint8_t *)username, strlen(username));
  esp_wifi_sta_wpa2_ent_set_username((uint8_t *)username, strlen(username));
  esp_wifi_sta_wpa2_ent_set_password((uint8_t *)password, strlen(password));
  esp_wifi_sta_wpa2_ent_enable();
  
  WiFi.begin(ssid);
  
  Serial.print("Connecting to WiFi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected! IP: " + WiFi.localIP().toString());
}

void registerWithServer() {
  DynamicJsonDocument doc(256);
  doc["userID"] = userID;
  doc["ipAddress"] = WiFi.localIP().toString();
  doc["portNumber"] = peerListenPort;  // Register our peer listen port
  doc["messageType"] = "registration";
  
  String jsonMessage;
  serializeJson(doc, jsonMessage);
  
  udp.beginPacket(serverIP, udpPort);
  udp.print(jsonMessage);
  udp.endPacket();
  
  Serial.println("Sent registration: " + jsonMessage);
}

void sendPing() {
  DynamicJsonDocument doc(256);
  doc["userID"] = userID;
  doc["ipAddress"] = WiFi.localIP().toString();
  doc["portNumber"] = peerListenPort;
  doc["messageType"] = "ping";
  
  String jsonMessage;
  serializeJson(doc, jsonMessage);
  
  udp.beginPacket(serverIP, udpPort);
  udp.print(jsonMessage);
  udp.endPacket();
  
  Serial.println("Sent ping: " + jsonMessage);
  
  // Check for UDP response with peer list
  checkForPeerUpdates();
}

void checkForPeerUpdates() {
  // Check for UDP response with peer list
  int packetSize = udp.parsePacket();
  if (packetSize) {
    char packetBuffer[255];
    int len = udp.read(packetBuffer, 255);
    if (len > 0) {
      packetBuffer[len] = 0;
      
      DynamicJsonDocument doc(1024);
      DeserializationError error = deserializeJson(doc, packetBuffer);
      
      if (!error && doc.containsKey("peers")) {
        // Clear existing peers
        peerCount = 0;
        
        // Add new peers
        JsonArray peerArray = doc["peers"];
        for (JsonObject peer : peerArray) {
          if (peerCount < MAX_PEERS) {
            peers[peerCount].userID = peer["userID"].as<String>();
            peers[peerCount].ipAddress = peer["ipAddress"].as<String>();
            peers[peerCount].portNumber = peer["portNumber"];
            peerCount++;
          }
        }
        
        printPeerList();
      }
    }
  }
}

void printPeerList() {
  Serial.println("\nCurrent Peer List:");
  Serial.println("-----------------");
  for (int i = 0; i < peerCount; i++) {
    Serial.printf("%d: %s at %s:%d\n", 
                 i+1, 
                 peers[i].userID.c_str(), 
                 peers[i].ipAddress.c_str(), 
                 peers[i].portNumber);
  }
  Serial.println("-----------------");
}

void handleDetection() {
  esp_camera_fb_return(esp_camera_fb_get());
  for (int i = 0; i < 3; i++) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
      esp_camera_fb_return(fb);
      delay(50); // Short delay between flushes
    }
  }
  // Capture photo
  camera_fb_t *fb = esp_camera_fb_get();
  //for (int i = 0; i<3; i++){camera_fb_t *fb = esp_camera_fb_get();}
  //camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    return;
  }
  
  Serial.printf("Captured image (%d bytes)\n", fb->len);
  
  // Connect to TCP server
  if (!tcpClient.connect(serverIP, serverTcpPort)) {
    Serial.println("TCP connection failed");
    esp_camera_fb_return(fb);
    return;
  }
  
  // Create JSON header
  DynamicJsonDocument doc(256);
  doc["userID"] = userID;
  doc["timestamp"] = millis();
  doc["imageSize"] = fb->len;
  doc["cameraStatus"] = "working";
  
  String jsonHeader;
  serializeJson(doc, jsonHeader);
  
  // Send header first (terminated with newline)
  tcpClient.print(jsonHeader + "\n");
  
  // Send raw image data
  const uint8_t *fbBuf = fb->buf;
  size_t fbLen = fb->len;
  
  for (size_t n=0; n<fbLen; n+=1024) {
    size_t chunkSize = (1024 < (fbLen - n)) ? 1024 : (fbLen - n);
    tcpClient.write(fbBuf + n, chunkSize);
  }
  
  Serial.println("Image sent to server");
  
  // Clean up
  esp_camera_fb_return(fb);
  tcpClient.stop();
}

void handlePeerConnections() {
  WiFiClient peerClient = peerServer.available();
  if (!peerClient) {
    return;
  }

  Serial.println("\nNew peer connection");
  
  // Set timeout for header reading
  peerClient.setTimeout(5000);
  
  // Read the JSON header line
  String headerLine = peerClient.readStringUntil('\n');
  if (headerLine.length() == 0) {
    Serial.println("Empty header from peer");
    peerClient.stop();
    return;
  }

  // Parse JSON header
  DynamicJsonDocument doc(512);
  DeserializationError error = deserializeJson(doc, headerLine);
  if (error) {
    Serial.print("Failed to parse peer header: ");
    Serial.println(error.c_str());
    peerClient.stop();
    return;
  }

  // Validate required fields
  if (!doc["forwarded"] || !doc["originalSender"] || !doc["imageSize"]) {
    Serial.println("Invalid forwarded message format");
    peerClient.stop();
    return;
  }

  String originalSender = doc["originalSender"];
  size_t imageSize = doc["imageSize"];
  size_t totalRead = 0;

  Serial.printf("Forwarding message from %s (%d bytes)...\n", originalSender.c_str(), imageSize);

  // Connect to main server first
  if (!tcpClient.connect(serverIP, serverTcpPort)) {
    Serial.println("Failed to connect to main server");
    peerClient.stop();
    return;
  }

  // Modify header
  doc["forwardedBy"] = userID;
  String newHeader;
  serializeJson(doc, newHeader);
  tcpClient.print(newHeader + "\n");

  // Forward image data in chunks
  uint8_t buffer[1024];
  unsigned long lastDataTime = millis();
  
  while (totalRead < imageSize) {
    if (millis() - lastDataTime > 30000) {
      Serial.println("Transfer timeout");
      break;
    }

    if (peerClient.available()) {
      size_t toRead = min(sizeof(buffer), imageSize - totalRead);
      size_t read = peerClient.readBytes(buffer, toRead);
      
      if (read > 0) {
        size_t written = tcpClient.write(buffer, read);
        if (written != read) {
          Serial.println("Failed to write to server");
          break;
        }
        totalRead += written;
        lastDataTime = millis();
        Serial.printf("Progress: %d/%d bytes (%.1f%%)\r", totalRead, imageSize, (totalRead*100.0)/imageSize);
      }
    }
    delay(1);
  }

  if (totalRead == imageSize) {
    Serial.println("\nForwarding complete!");
  } else {
    Serial.printf("\nForwarding incomplete: %d/%d bytes\n", totalRead, imageSize);
  }

  peerClient.stop();
  tcpClient.stop();
}
