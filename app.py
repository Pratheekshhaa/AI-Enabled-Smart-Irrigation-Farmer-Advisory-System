#!/usr/bin/env python3
# IMPROVED AGENT.PY – Better UI + instant weather updates + Rain Forecast Display (24h)

import time
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import requests
import sys
from datetime import datetime, timezone, timedelta

# Hardware
import board
import adafruit_dht
import RPi.GPIO as GPIO

# ---------------- CONFIG ----------------

ESP_HOST = "esp-pump.local"    # mDNS hostname for ESP8266
ESP_PORT = 5001

OPENWEATHER_API_KEY = ""
CITY = "Bengaluru,IN"             # Default city with country code (city,country)

TEMP_THRESHOLD = 30.0
SOIL_DRY_THRESHOLD = 30
PUMP_TIME = 5
AUTO_ENABLED = True

SENSOR_POLL = 2
AUTO_POLL = 10
WEATHER_POLL = 300  # 5 minutes

DHT_PIN = board.D4
SOIL_PIN = 17

PORT = 5000

# ----------------------------------------

GPIO.setmode(GPIO.BCM)
GPIO.setup(SOIL_PIN, GPIO.IN)

dht = adafruit_dht.DHT11(DHT_PIN, use_pulseio=False)

lock = threading.Lock()
latest = {"temperature": None, "humidity": None, "soil": None, "error": "Initializing"}
# weather now includes forecast summary, boolean for rain next 24h, and rain_times list
weather = {
    "enabled": bool(OPENWEATHER_API_KEY),
    "summary": None,
    "rain": False,
    "temp": None,
    "description": None,
    "rain_next_24h": False,
    "rain_times": []   # human-readable times within next 24h where rain is predicted
}
settings = {
    "TEMP_THRESHOLD": TEMP_THRESHOLD,
    "SOIL_DRY_THRESHOLD": SOIL_DRY_THRESHOLD,
    "PUMP_TIME": PUMP_TIME,
    "AUTO_ENABLED": AUTO_ENABLED
}

# ------------ SENSOR LOOP ------------
def read_soil():
    v = GPIO.input(SOIL_PIN)
    return 100 if v == 0 else 0   # 0=wet, 1=dry

def sensor_loop():
    global latest
    while True:
        try:
            temp = None
            hum = None
            try:
                temp = dht.temperature
                hum = dht.humidity
            except RuntimeError:
                # intermittent DHT failures are normal; keep previous values
                pass

            soil = None
            try:
                soil = read_soil()
            except Exception as e:
                with lock:
                    latest["error"] = f"Soil read error: {e}"

            with lock:
                if temp is not None:
                    latest["temperature"] = float(temp)
                    latest["humidity"] = float(hum)
                    latest["error"] = None
                else:
                    if latest["temperature"] is None:
                        latest["error"] = "Sensor warming up"
                latest["soil"] = soil

        except Exception as e:
            with lock:
                latest["error"] = f"Sensor thread error: {e}"
            traceback.print_exc()
        time.sleep(SENSOR_POLL)

# ------------ WEATHER LOOP (current + 24h forecast) ------------

def fetch_current_weather():
    """Fetch current weather (same as before). Returns JSON or None."""
    if not OPENWEATHER_API_KEY or not CITY:
        return None
    url = f"https://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.json()
        else:
            print("Weather API error (current):", r.status_code, r.text)
    except Exception as e:
        print("Weather error (current):", e)
    return None

def fetch_forecast_3h():
    """Fetch 3-hourly forecast (5-day) and return JSON or None."""
    if not OPENWEATHER_API_KEY or not CITY:
        return None
    url = f"https://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={OPENWEATHER_API_KEY}&units=metric"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.json()
        else:
            print("Weather API error (forecast):", r.status_code, r.text)
    except Exception as e:
        print("Weather error (forecast):", e)
    return None

def analyze_forecast_for_24h(forecast_json):
    """Given forecast JSON (list of 3-hour entries), return (rain_next_24h:bool, rain_times:list[str])."""
    if not forecast_json or "list" not in forecast_json:
        return False, []
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)
    rain_times = []
    for entry in forecast_json["list"]:
        # entry example: { "dt": 169..., "main": {...}, "weather": [ { "main": "Rain", "description":"light rain"} ], "rain": {"3h": 0.5} }
        dt = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
        if dt < now or dt > end:
            continue
        # check either 'rain' key >0 or 'weather' contains 'rain'/'shower'/'drizzle'/'thunderstorm'
        rain_flag = False
        if "rain" in entry and entry["rain"]:
            # value often under '3h'
            try:
                amount = entry["rain"].get("3h", 0)
                if amount and amount > 0:
                    rain_flag = True
            except:
                rain_flag = True
        # fallback to weather description
        if not rain_flag:
            we = entry.get("weather", [])
            if we:
                desc = we[0].get("description", "").lower()
                if any(k in desc for k in ("rain", "shower", "drizzle", "thunder")):
                    rain_flag = True
        if rain_flag:
            # convert to local time string for display
            local_time = dt.astimezone().strftime("%Y-%m-%d %H:%M")
            rain_times.append(local_time)
    return (len(rain_times) > 0), rain_times

def weather_loop():
    global weather
    if not OPENWEATHER_API_KEY:
        weather["enabled"] = False
        return
    weather["enabled"] = True

    # fetch immediately
    try:
        cur = fetch_current_weather()
        fc = fetch_forecast_3h()
        with lock:
            if cur:
                desc = cur.get("weather", [{}])[0].get("description")
                weather["summary"] = desc
                weather["description"] = cur.get("weather", [{}])[0].get("main")
                weather["temp"] = cur.get("main", {}).get("temp")
                weather["rain"] = ("rain" in (desc or "").lower() or "shower" in (desc or "").lower() or "drizzle" in (desc or "").lower() or "thunder" in (desc or "").lower())
            else:
                weather["summary"] = "Unable to fetch"
                weather["rain"] = False

            # forecast analysis
            rain_24, rain_times = analyze_forecast_for_24h(fc)
            weather["rain_next_24h"] = rain_24
            weather["rain_times"] = rain_times
    except Exception as e:
        print("Weather thread initial error:", e)

    while True:
        try:
            time.sleep(WEATHER_POLL)
            cur = fetch_current_weather()
            fc = fetch_forecast_3h()
            with lock:
                if cur:
                    desc = cur.get("weather", [{}])[0].get("description")
                    weather["summary"] = desc
                    weather["description"] = cur.get("weather", [{}])[0].get("main")
                    weather["temp"] = cur.get("main", {}).get("temp")
                    weather["rain"] = ("rain" in (desc or "").lower() or "shower" in (desc or "").lower() or "drizzle" in (desc or "").lower() or "thunder" in (desc or "").lower())
                else:
                    weather["summary"] = None
                    weather["rain"] = False

                rain_24, rain_times = analyze_forecast_for_24h(fc)
                weather["rain_next_24h"] = rain_24
                weather["rain_times"] = rain_times
        except Exception as e:
            print("Weather loop error:", e)
            traceback.print_exc()

# ------------ PUMP CONTROL ------------
def trigger_pump(seconds):
    try:
        url = f"http://{ESP_HOST}:{ESP_PORT}/water?seconds={int(seconds)}"
        print("Calling:", url)
        r = requests.get(url, timeout=4)
        return r.status_code == 200
    except Exception as e:
        print("ESP unreachable:", e)
        return False

# ------------ AUTO WATERING ------------
def auto_loop():
    while True:
        try:
            with lock:
                t = latest["temperature"]
                s = latest["soil"]
                temp_th = settings["TEMP_THRESHOLD"]
                soil_th = settings["SOIL_DRY_THRESHOLD"]
                sec = settings["PUMP_TIME"]
                auto = settings["AUTO_ENABLED"]
                rain = weather.get("rain_next_24h", False) or weather.get("rain", False)

            if auto and t is not None and s is not None:
                if (t > temp_th or s < soil_th) and not rain:
                    print("AUTO WATER: Triggering pump")
                    trigger_pump(sec)
                    time.sleep(sec + 3)

        except Exception as e:
            print("Auto loop error:", e)
        time.sleep(AUTO_POLL)

# ------------ WEB UI (ENHANCED PREMIUM DESIGN) ------------
HTML = """<!doctype html>
<html><head>
<meta charset="UTF-8">
<title>Smart Irrigation</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

* { margin: 0; padding: 0; box-sizing: border-box; }

body { 
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
  background: #0a0e27;
  color: #fff;
  overflow-x: hidden;
  position: relative;
  min-height: 100vh;
}

body::before {
  content: '';
  position: fixed;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: 
    radial-gradient(circle at 20% 50%, rgba(16, 185, 129, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 80%, rgba(59, 130, 246, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 40% 20%, rgba(147, 51, 234, 0.1) 0%, transparent 50%);
  animation: drift 20s ease-in-out infinite;
  z-index: 0;
}

@keyframes drift {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  33% { transform: translate(5%, 5%) rotate(5deg); }
  66% { transform: translate(-5%, 3%) rotate(-5deg); }
}

.container { 
  max-width: 1400px; 
  margin: 0 auto; 
  padding: 40px 20px;
  position: relative;
  z-index: 1;
}

header {
  text-align: center;
  margin-bottom: 50px;
  animation: fadeInDown 0.8s ease;
}

@keyframes fadeInDown {
  from { opacity: 0; transform: translateY(-30px); }
  to { opacity: 1; transform: translateY(0); }
}

h1 {
  font-size: clamp(2rem, 5vw, 3.5rem);
  font-weight: 800;
  background: linear-gradient(135deg, #10b981 0%, #3b82f6 50%, #8b5cf6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 12px;
  letter-spacing: -0.02em;
}

.subtitle {
  font-size: 1.1rem;
  color: rgba(255, 255, 255, 0.6);
  font-weight: 400;
}

.grid { 
  display: grid; 
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); 
  gap: 24px; 
  margin-bottom: 24px;
}

.card { 
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 32px; 
  border-radius: 24px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  animation: fadeInUp 0.8s ease backwards;
}

.card::before {
  content: '';
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.3), rgba(59, 130, 246, 0.3), rgba(139, 92, 246, 0.3));
  border-radius: 24px;
  opacity: 0;
  transition: opacity 0.4s ease;
  z-index: -1;
}

.card:hover::before {
  opacity: 1;
}

.card:hover { 
  transform: translateY(-8px);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(30px); }
  to { opacity: 1; transform: translateY(0); }
}

.card:nth-child(1) { animation-delay: 0.1s; }
.card:nth-child(2) { animation-delay: 0.2s; }
.card:nth-child(3) { animation-delay: 0.3s; }

.card-title {
  font-size: 1.3rem;
  font-weight: 700;
  margin-bottom: 24px;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 12px;
}

.icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  border-radius: 10px;
  font-size: 18px;
}

.sensor-reading { 
  display: flex; 
  justify-content: space-between;
  align-items: center;
  padding: 16px 0; 
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  transition: all 0.3s ease;
}

.sensor-reading:hover {
  padding-left: 8px;
  background: rgba(255, 255, 255, 0.02);
  margin: 0 -8px;
  padding-left: 16px;
  padding-right: 8px;
  border-radius: 12px;
}

.sensor-reading:last-child {
  border-bottom: none;
}

.sensor-label { 
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.95rem;
  font-weight: 500;
}

.sensor-value { 
  font-weight: 700;
  font-size: 1.4rem;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.status-badge {
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-radius: 12px;
  color: #10b981;
  font-size: 0.9rem;
  font-weight: 600;
  text-align: center;
}

.status-badge.error {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

.weather-current {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  margin: 20px 0;
}

.weather-temp {
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.weather-desc {
  flex: 1;
  font-size: 1.1rem;
  color: rgba(255, 255, 255, 0.8);
}

.rain-forecast {
  margin-top: 20px;
}

.forecast-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 12px;
  color: rgba(255, 255, 255, 0.9);
}

.rain-summary {
  padding: 12px 16px;
  border-radius: 12px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.rain-summary.rain-expected {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

.rain-summary.no-rain {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.rain-times {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.rain-pill {
  padding: 8px 14px;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 20px;
  color: #60a5fa;
  font-size: 0.85rem;
  font-weight: 600;
  transition: all 0.3s ease;
}

.rain-pill:hover {
  background: rgba(59, 130, 246, 0.25);
  transform: scale(1.05);
}

.input-group {
  margin-bottom: 20px;
}

.input-label {
  display: block;
  font-size: 0.9rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.8);
  margin-bottom: 8px;
}

input, select { 
  width: 100%;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  color: #fff;
  font-size: 1rem;
  font-family: inherit;
  transition: all 0.3s ease;
}

input:focus, select:focus {
  outline: none;
  border-color: #3b82f6;
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

input::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.btn {
  padding: 14px 28px;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
  position: relative;
  overflow: hidden;
}

.btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
  transition: left 0.5s ease;
}

.btn:hover::before {
  left: 100%;
}

.btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 25px rgba(16, 185, 129, 0.4);
}

.btn:active {
  transform: translateY(0);
}

.btn.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  box-shadow: none;
}

.btn.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.15);
}

.manual-control {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.manual-control input {
  flex: 1;
  max-width: 120px;
}

.control-panel {
  animation: fadeInUp 1s ease backwards;
  animation-delay: 0.4s;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

@media (max-width: 768px) {
  .container { padding: 20px 16px; }
  h1 { font-size: 2rem; }
  .card { padding: 24px; }
  .sensor-value { font-size: 1.2rem; }
  .weather-temp { font-size: 2.5rem; }
  .settings-grid { grid-template-columns: 1fr; }
}

.pulse {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
</style>
</head>
<body>

<div class="container">
  <header>
    <h1>🌱 Smart Irrigation</h1>
    <div class="subtitle">Real-time monitoring & intelligent watering</div>
  </header>

  <div class="grid">
    <!-- Sensors Card -->
    <div class="card">
      <div class="card-title">
        <div class="icon">📊</div>
        Live Sensors
      </div>
      <div class="sensor-reading">
        <div class="sensor-label">Temperature</div>
        <div class="sensor-value" id="t">--°</div>
      </div>
      <div class="sensor-reading">
        <div class="sensor-label">Humidity</div>
        <div class="sensor-value" id="h">--%</div>
      </div>
      <div class="sensor-reading">
        <div class="sensor-label">Soil Moisture</div>
        <div class="sensor-value" id="s">--%</div>
      </div>
      <div id="status" class="status-badge">Initializing...</div>
    </div>

    <!-- Weather Card -->
    <div class="card">
      <div class="card-title">
        <div class="icon">🌤️</div>
        Weather
      </div>
      
      <div class="weather-current">
        <div class="weather-temp" id="wtemp">--°</div>
        <div class="weather-desc" id="wdesc">Loading weather...</div>
      </div>

      <div class="rain-forecast">
        <div class="forecast-title">24-Hour Forecast</div>
        <div id="rain-summary" class="rain-summary">
          <span class="pulse">⏳</span>
          Checking forecast...
        </div>
        <div id="rain-times" class="rain-times"></div>
      </div>

      <div class="input-group" style="margin-top: 24px;">
        <label class="input-label">Location</label>
        <select id="city">
          <option value="Bengaluru,IN">Bengaluru</option>
          <option value="Hyderabad,IN">Hyderabad</option>
          <option value="Mumbai,IN">Mumbai</option>
          <option value="Chennai,IN">Chennai</option>
        </select>
      </div>
      <button onclick="saveCity()" class="btn btn-secondary" style="width: 100%;">Update Location</button>
    </div>

    <!-- Control Card -->
    <div class="card">
      <div class="card-title">
        <div class="icon">💧</div>
        Water Control
      </div>
      
      <div class="input-group">
        <label class="input-label">Duration (seconds)</label>
        <div class="manual-control">
          <input id="sec" type="number" value="5" min="1" />
          <button onclick="water()" class="btn">Activate</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Settings Panel -->
  <div class="card control-panel">
    <div class="card-title">
      <div class="icon">⚙️</div>
      System Settings
    </div>
    
    <div class="settings-grid">
      <div class="input-group">
        <label class="input-label">Temp Threshold (°C)</label>
        <input id="tht" type="number" step="0.1" />
      </div>
      
      <div class="input-group">
        <label class="input-label">Soil Dry Threshold (%)</label>
        <input id="ths" type="number" />
      </div>
      
      <div class="input-group">
        <label class="input-label">Auto Pump Time (s)</label>
        <input id="thp" type="number" />
      </div>
    </div>
    
    <button onclick="save()" class="btn" style="width: 100%;">💾 Save Settings</button>
  </div>
</div>

<script>
async function load(){
  try{
    let r=await fetch('/sensor'); let d=await r.json();
    document.getElementById('t').innerText = d.temperature !== null ? d.temperature.toFixed(1) + '°C' : '--°';
    document.getElementById('h').innerText = d.humidity !== null ? d.humidity.toFixed(0) + '%' : '--%';
    document.getElementById('s').innerText = d.soil !== null ? d.soil + '%' : '--%';
    
    const statusEl = document.getElementById('status');
    if (d.error) {
      statusEl.className = 'status-badge error';
      statusEl.innerHTML = '⚠️ ' + d.error;
    } else {
      statusEl.className = 'status-badge';
      statusEl.innerHTML = '✅ System Online';
    }

    let w = await fetch('/weather'); w = await w.json();
    document.getElementById('wtemp').innerText = w.temp !== null ? Math.round(w.temp) + '°' : '--°';
    document.getElementById('wdesc').innerText = w.summary || 'No data';

    const summaryEl = document.getElementById('rain-summary');
    const timesEl = document.getElementById('rain-times');
    
    if (w.rain_next_24h) {
      summaryEl.className = 'rain-summary rain-expected';
      summaryEl.innerHTML = '🌧️ Rain expected in next 24 hours';
      let times = w.rain_times || [];
      timesEl.innerHTML = '';
      if(times.length){
        times.forEach(t=>{
          const pill = document.createElement('span');
          pill.className = 'rain-pill';
          pill.textContent = t;
          timesEl.appendChild(pill);
        });
      }
    } else {
      summaryEl.className = 'rain-summary no-rain';
      summaryEl.innerHTML = '☀️ No rain predicted in next 24 hours';
      timesEl.innerHTML = '';
    }
  }catch(e){
    console.error(e);
  }
}

async function water(){
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Running...';
  
  let secs = document.getElementById('sec').value;
  await fetch('/water?seconds='+secs);
  
  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = 'Activate';
  }, secs * 1000);
}

async function save(){
  let data = { 
    TEMP_THRESHOLD: parseFloat(document.getElementById('tht').value), 
    SOIL_DRY_THRESHOLD: parseInt(document.getElementById('ths').value), 
    PUMP_TIME: parseInt(document.getElementById('thp').value) 
  };
  await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  
  const btn = event.target;
  const originalText = btn.innerHTML;
  btn.innerHTML = '✓ Saved!';
  btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
  setTimeout(() => {
    btn.innerHTML = originalText;
    btn.style.background = '';
  }, 2000);
}

async function saveCity(){
  let c = document.getElementById('city').value;
  await fetch('/setcity?c='+c);
  
  const btn = event.target;
  btn.innerHTML = '⏳ Updating...';
  btn.disabled = true;
  
  setTimeout(() => {
    btn.innerHTML = 'Update Location';
    btn.disabled = false;
    load();
  }, 1500);
}

async function loadSettings(){
  let r = await fetch('/settings'); let d = await r.json();
  document.getElementById('tht').value = d.TEMP_THRESHOLD;
  document.getElementById('ths').value = d.SOIL_DRY_THRESHOLD;
  document.getElementById('thp').value = d.PUMP_TIME;
}

setInterval(load, 2000); 
load(); 
loadSettings();
</script>

</body></html>
"""

# ------------ HTTP HANDLER ------------
class Handler(BaseHTTPRequestHandler):
    def _json(self, code=200):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path
        q = parse_qs(parsed.query)

        if p == "/":
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
            return

        if p == "/sensor":
            with lock:
                out = dict(latest)
            self._json()
            self.wfile.write(json.dumps(out).encode())
            return

        if p == "/weather":
            with lock:
                out = {
                    "summary": weather.get("summary"),
                    "rain": weather.get("rain"),
                    "temp": weather.get("temp"),
                    "description": weather.get("description"),
                    "rain_next_24h": weather.get("rain_next_24h"),
                    "rain_times": weather.get("rain_times", [])
                }
            self._json()
            self.wfile.write(json.dumps(out).encode())
            return

        if p == "/water":
            sec = int(q.get("seconds",[PUMP_TIME])[0])
            threading.Thread(target=trigger_pump,args=(sec,),daemon=True).start()
            self._json()
            self.wfile.write(b'"OK"')
            return

        if p == "/setcity":
            global CITY
            CITY = q.get("c",[""])[0]
            threading.Thread(target=fetch_and_update_weather, daemon=True).start()
            self._json()
            self.wfile.write(b'"OK"')
            return

        if p == "/settings":
            with lock:
                self._json()
                self.wfile.write(json.dumps(settings).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/settings":
            ln = int(self.headers.get("Content-Length",0))
            body = self.rfile.read(ln).decode()
            data = json.loads(body)
            with lock:
                if "TEMP_THRESHOLD" in data:
                    settings["TEMP_THRESHOLD"] = float(data["TEMP_THRESHOLD"])
                if "SOIL_DRY_THRESHOLD" in data:
                    settings["SOIL_DRY_THRESHOLD"] = int(data["SOIL_DRY_THRESHOLD"])
                if "PUMP_TIME" in data:
                    settings["PUMP_TIME"] = int(data["PUMP_TIME"])
            self._json()
            self.wfile.write(b'"OK"')
            return

        self.send_response(404)
        self.end_headers()

# Helper for immediate weather update
def fetch_and_update_weather():
    global weather
    cur = fetch_current_weather()
    fc = fetch_forecast_3h()
    with lock:
        if cur:
            desc = cur.get("weather", [{}])[0].get("description")
            weather["summary"] = desc
            weather["description"] = cur.get("weather", [{}])[0].get("main")
            weather["temp"] = cur.get("main", {}).get("temp")
            weather["rain"] = ("rain" in (desc or "").lower() or "shower" in (desc or "").lower() or "drizzle" in (desc or "").lower() or "thunder" in (desc or "").lower())
        else:
            weather["summary"] = None
            weather["rain"] = False
        rain_24, rain_times = analyze_forecast_for_24h(fc)
        weather["rain_next_24h"] = rain_24
        weather["rain_times"] = rain_times

# ------------ MAIN ------------
def main():
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=weather_loop, daemon=True).start()
    threading.Thread(target=auto_loop, daemon=True).start()

    # start webserver
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Smart Irrigation System running on port {PORT}")
    print(f"Open http://localhost:{PORT} in your browser")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()