#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>

#define WIFI_SSID ""
#define WIFI_PASSWORD ""

#define RELAY_PIN D1          // Relay connected to D1 (GPIO5)
#define SERVER_PORT 5001      // Port ESP listens on

ESP8266WebServer server(SERVER_PORT);

// Connect to WiFi
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected!");
  Serial.print("ESP IP Address → ");
  Serial.println(WiFi.localIP());   // RPi will talk to this IP
}

// Trigger Water Pump Handler
void handleWater() {
  if (!server.hasArg("seconds")) {
    server.send(400, "application/json", "{\"error\":\"missing seconds parameter\"}");
    return;
  }

  int secs = server.arg("seconds").toInt();
  if (secs <= 0 || secs > 20) {
    server.send(400, "application/json", "{\"error\":\"invalid seconds\"}");
    return;
  }

  // ----- PRINT STATEMENT FOR RASPBERRY PI TRIGGER -----
  Serial.printf("💧 Pump TRIGGERED by Raspberry Pi → %d seconds\n", secs);

  digitalWrite(RELAY_PIN, LOW);   // Relay ON
  delay(secs * 1000);
  digitalWrite(RELAY_PIN, HIGH);  // Relay OFF

  server.send(200, "application/json",
              "{\"status\":\"ok\",\"pump_seconds\":" + String(secs) + "}");
}

// Setup
void setup() {
  Serial.begin(115200);

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH); // relay OFF initially

  connectWiFi();

  // NO MDNS (removed because it caused issues)
  Serial.println("mDNS disabled (using direct IP only)");

  server.on("/water", handleWater);
  server.begin();

  Serial.printf("Server running on port %d\n", SERVER_PORT);
}

// Loop
void loop() {
  server.handleClient();   // Handle /water requests
}