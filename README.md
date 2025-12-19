# AI-Enabled-Smart-Irrigation-Farmer-Advisory-System
Designed an AI-enabled smart irrigation and farmer advisory system using Raspberry Pi and ESP8266, integrating real-time soil moisture, temperature, and humidity with weather forecasts. The system enables predictive irrigation control, chatbot-based guidance, efficient water usage, and remote pump automation for precision agriculture

## Project Overview

This project is a Smart Irrigation System designed to assist farmers by:
- Monitoring temperature, humidity, and soil moisture
- Displaying live data on a web dashboard hosted on Raspberry Pi
- Automatically activating a water pump via ESP8266 when conditions require
- Preventing over-watering using 24-hour rain forecast data

The system combines edge sensing, web-based control, and weather-aware automation.

---

## System Architecture

**Raspberry Pi (Controller & Server)**
- Reads sensors (DHT11 + Soil Moisture)
- Hosts web dashboard (Python HTTP server)
- Fetches weather + rain forecast (OpenWeather API)
- Decides when irrigation is required
- Sends HTTP commands to ESP8266

**ESP8266 (Actuator Node)**
- Hosts lightweight HTTP server
- Controls relay module
- Turns water pump ON/OFF based on Pi commands

---

## Hardware Components

### Raspberry Pi Side
- Raspberry Pi 4B  
- DHT11 Temperature & Humidity Sensor  
- Digital Soil Moisture Sensor  
- Jumper wires  

### ESP8266 Side
- ESP8266 (NodeMCU)
- Single-channel Relay Module
- DC Water Pump
- External 5V Power Supply (for pump)

---

## Pin Connections

### Soil Moisture Sensor → Raspberry Pi
| Sensor Pin | Raspberry Pi |
|-----------|--------------|
| VCC | 3.3V |
| GND | GND |
| DO | GPIO17 |

> Digital mode used (0% = dry, 100% = wet)

### DHT11 → Raspberry Pi
| DHT11 | Raspberry Pi |
|------|--------------|
| VCC | 3.3V |
| DATA | GPIO4 |
| GND | GND |

### Relay + Pump → ESP8266
| Relay Pin | ESP8266 |
|----------|---------|
| IN | D1 (GPIO5) |
| VCC | 5V |
| GND | GND |

Pump is connected to **COM & NO** terminals of relay  
External 5V supply is **mandatory for pump**

---

## 🌐 Communication Flow

- Raspberry Pi sends HTTP request:
```http://<ESP_IP>:5001/water?seconds=5```

ESP8266 receives request and:
- Prints log on Serial Monitor
- Activates relay
- Runs pump for requested duration

---

## Weather Intelligence

- Weather data fetched using OpenWeather API
- APIs used:
    - `/data/2.5/weather` → Current weather
    - `/data/2.5/forecast` → 3-hour interval forecast
- System checks next 24 hours for rain
- Auto-watering is paused if rain is predicted

---

## Web Dashboard Features

- Live temperature, humidity & soil moisture
- 24-hour rain forecast with timestamps
- Manual pump activation
- Auto-watering configuration
- City selection for weather data
- Real-time updates every 2 seconds
- Mobile & desktop responsive UI

Dashboard is hosted directly on Raspberry Pi.

---

## How to Run the Project

### Raspberry Pi (via RealVNC / Terminal)

1. SSH or open terminal using **RealVNC**
2. Navigate to project folder:
 ```bash 
cd smartfarm/smart_farm
``` 
3. Activate virtual environment:
```bash
source smartenv/bin/activate
```
4. Run the server:
```bash
python3 agent.py
```
5. Open browser:
```http
http://<raspberry_pi_ip>:5000
```
The web server runs continuously and hosts the dashboard.

### ESP8266 (Arduino IDE)
1. Open Arduino IDE
2. Select board: NodeMCU ESP8266
3. Paste ESP8266 code
4. Set WiFi credentials:
```c
#define WIFI_SSID "your_wifi"
#define WIFI_PASSWORD "your_password"
```
5. Upload code
6. Open Serial Monitor (115200 baud)
You will see:
```c
ESP IP Address → 192.168.x.x
💧 Pump TRIGGERED by Raspberry Pi → 5 seconds
```
## Auto-Watering Logic
Pump is triggered only when:
- Soil is dry OR
- Temperature exceeds threshold
AND
- No rain is predicted in next 24 hours
This avoids:
- Over-watering
- Wasting water during rainfall

## Testing Summary
- Sensor readings verified against real instruments
- ESP ↔ Pi communication tested via REST API
- Auto-watering validated under simulated conditions
- Weather forecast accuracy cross-checked
- UI tested across mobile & desktop
All components performed as expected.

## Future Enhancements
- Analog soil moisture sensing (ADC)
- ML-based irrigation prediction
- SMS / WhatsApp alerts
- Multi-zone irrigation
- Cloud dashboard integration
- Historical data analytics

## Technologies Used
- Python 3
- ESP8266 Arduino Core
- HTML / CSS / JavaScript
- OpenWeather API
- REST APIs
- Raspberry Pi GPIO
- RealVNC
- Arduino IDE

## Conclusion
This project demonstrates a complete end-to-end smart agriculture solution combining IoT, weather intelligence, and automation to optimize water usage and improve farming efficiency.
