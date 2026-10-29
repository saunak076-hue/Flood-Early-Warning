# Flood Early Warning: Hydrological Risk Intelligence System
**Hack4Haldia'26 — Team C**  
*Hydrological Flood Forecasting, Geospatial Monitoring, and Early Warning Dashboard for West Bengal*

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-black.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/Tests-33%20Passed%20(100%25)-success.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

---

## 1. Project Overview & Problem Statement

Flooding in the Bengal Delta (Bhagirathi-Hooghly, Silabati, Teesta, and coastal Bay of Bengal) causes severe agricultural devastation, industrial disruption, and loss of life every monsoon. Traditional flood warnings frequently arrive too late or lack granular catchment-level actionable advice.

The **Flood Early Warning System** is an end-to-end, deterministic flood intelligence and early-warning platform engineered for disaster management authorities, municipal engineers, port operators, and local citizens. It ingests live high-resolution rainfall forecasts and river discharge telemetry from open atmospheric and hydrological models, evaluates multi-factor flood vulnerability, displays real-time geospatial risk maps, and triggers deduplicated emergency alerts with prioritized civil-defense precautions.

---

## 2. Key Features

- **Real Telemetry Ingestion:** Ingests live precipitation (current, 24h accumulated, 7-day outlook) and river discharge ($m^3/s$) from Open-Meteo Weather Forecast and GloFAS Flood APIs.
- **Explainable Flood Risk Engine:** A transparent, deterministic mathematical baseline model (0–100 risk score) categorizing risk into `LOW`, `MODERATE`, `HIGH`, and `SEVERE`, providing a points breakdown and contributing factors.
- **Strict Hydrological Distinctions:** Rigorously differentiates **Rainfall (mm)**, **River Discharge ($m^3/s$)**, and **River Water Level (m)**. It never treats discharge as water level.
- **Provenance & Quality Tracking:** Explicitly identifies data freshness (`LIVE`, `CACHED`, `DEMO`, `UNAVAILABLE`) and completeness (`COMPLETE`, `PARTIAL_PRECIP_ONLY`, `PARTIAL_DISCHARGE_ONLY`, `DEGRADED`).
- **Emergency Alert Center:** Automatically generates and deduplicates flood advisories and warnings based on zone-specific thresholds.
- **Interactive Geospatial Dashboard:** Leaflet-based map with custom color-coded pins, pulse indicators, catchment popups, and full responsive design.
- **"What-If" Flood Risk Simulator:** Interactive UI tool executing `POST /api/predict` in real time so judges and emergency planners can simulate weather shocks (e.g. 150mm rain + 250 $m^3/s$ discharge).
- **Multi-Day Hydrological Trends:** Chart.js integration visualizing 7-day river discharge forecast and historical precipitation.
- **Deduplicated SQLite Persistence:** Thread-safe SQLite backend with WAL mode indexing for historical trend analysis.
- **Background Ingestion Scheduler:** APScheduler background worker running periodic 15-minute ingestion cycles with single-instance execution locks.

---

## 3. Monitored West Bengal Catchments

The Flood Early Warning System monitors 8 strategic flood-vulnerable catchments across West Bengal:

| Zone ID | Catchment Name | District | River Basin / Waterbody | Lat, Lon | Vulnerability Profile |
|---|---|---|---|---|---|
| `haldia` | **Haldia Port & Industrial Belt** | Purba Medinipur | Haldi & Hooghly Estuary | 22.0667, 88.0698 | Tidal storm surge, port runoff |
| `kolkata` | **Kolkata Metropolitan** | Kolkata | Lower Hooghly Delta | 22.5726, 88.3639 | High-density urban waterlogging |
| `howrah` | **Howrah Urban Belt** | Howrah | Bhagirathi-Hooghly West | 22.5958, 88.2636 | Low-elevation riverbank inundation |
| `diamond-harbour` | **Diamond Harbour Estuary** | South 24 Parganas | Hooghly Tidal Estuary | 22.1985, 88.1925 | Tidal bore, saline embankment breach |
| `ghatal` | **Ghatal Sub-Division** | Paschim Medinipur | Silabati & Kangsabati Confluence | 22.6658, 87.7226 | Chronically inundated depression |
| `farakka` | **Farakka Barrage / Malda** | Murshidabad / Malda | Upper Ganga / Farakka Feeder | 24.7936, 87.9103 | Major barrage, Himalayan runoff |
| `digha` | **Digha Coastal Zone** | Purba Medinipur | Bay of Bengal Coastal Zone | 21.6266, 87.5074 | Coastal cyclone surge & sea-wall overtopping |
| `jalpaiguri` | **Jalpaiguri Teesta Basin** | Jalpaiguri | Teesta & Karala Rivers | 26.5405, 88.7194 | Flash floods, glacial melt surge |

---

## 4. Flood Risk Model Methodology

### Scoring Breakdown (0 to 100 Points)
The risk engine implements a deterministic, weighted scoring formula:

1. **Recent 24-Hour Precipitation (0 – 40 pts):**
   - Scaled against zone-specific moderate (`rain_mod`) and severe (`rain_sev`) thresholds.
   - For example, Ghatal triggers severe at 75 mm, whereas Kolkata triggers at 95 mm.
2. **River Discharge Telemetry (0 – 35 pts):**
   - Ingested from GloFAS model grid cells ($m^3/s$).
   - Evaluated against bankfull carrying limits (`discharge_threshold_moderate` and `discharge_threshold_severe`).
3. **7-Day Cumulative Rain Outlook (0 – 15 pts):**
   - Assesses sustained soil saturation and prolonged catchment inflow.
4. **Catchment Geomorphology & Tidal Factor (0 – 10 pts):**
   - Elevation penalty for ultra-low elevation (< 8m AMSL) impairing gravity drainage.
   - Coastal/tidal penalty for estuarine drainage locks during astronomical high tides.
5. **Compound Synergy Bonus (+5 to +10 pts):**
   - When **both** 24h rainfall and river discharge exceed severe thresholds simultaneously, compound amplification reflects saturated soil + overtopping river banks.

### Risk Categories
- **`LOW` (0 – 29):** Green (`#22c55e`). Normal conditions; routine monitoring.
- **`MODERATE` (30 – 59):** Yellow (`#eab308`). Advisory conditions; drainage clearing advised.
- **`HIGH` (60 – 79):** Orange (`#f97316`). Warning conditions; waterlogging expected, river banks at elevated risk.
- **`SEVERE` (80 – 100):** Red (`#ef4444`). Emergency alert; imminent inundation risk, evacuation readiness.

### Normalization for Partial Data
If river discharge is unavailable for a remote coordinate, the model normalizes the remaining meteorological and topological features proportionally so the entire 0–100 scale remains operational, while explicitly marking `data_quality` as `PARTIAL_PRECIP_ONLY`.

---

## 5. Technology Stack

- **Backend:** Python 3, Flask, Flask-CORS, Gunicorn
- **Data Ingestion & Scheduling:** Requests, APScheduler, Python-dotenv
- **Database:** SQLite (WAL mode, foreign keys, index-optimized)
- **Frontend:** Vanilla HTML5, CSS3 (Emergency Navy UI), JavaScript (ES6+)
- **Geospatial & Visualization:** Leaflet.js, CartoDB basemaps, Chart.js 4.4
- **Testing:** Python `unittest` (22 unit & integration tests)
- **Deployment Platform:** Render (Web Service via Gunicorn & Procfile)

---

## 6. REST API Reference

### 1. `GET /health`
Returns system status, background scheduler state, and upstream API availability.
```json
{
  "status": "ok",
  "project": "Team C: Flood Early Warning",
  "stack": "flask",
  "version": "1.0.0",
  "zones_monitored": 8,
  "active_alerts_count": 0,
  "upstream_apis": {
    "weather_api": "reachable",
    "flood_api": "reachable",
    "overall": "ok"
  }
}
```

### 2. `GET /api/readings`
Returns latest telemetry readings for all monitored zones.
- Optional query params: `?demo=true`, `?refresh=true`
```json
{
  "count": 8,
  "source": "SQLite Persisted Telemetry & Risk Engine",
  "readings": [
    {
      "zone_id": "haldia",
      "zone_name": "Haldia Industrial & Port Zone",
      "district": "Purba Medinipur",
      "river_basin": "Haldi & Hooghly Estuary",
      "rainfall_current_mm": 0.7,
      "rainfall_24h_mm": 32.4,
      "forecast_rain_7d_mm": 68.0,
      "river_discharge_m3s": 1.69,
      "river_water_level_m": null,
      "risk_score": 27.0,
      "risk_level": "LOW",
      "risk_color": "#22c55e",
      "freshness": "LIVE",
      "data_quality": "COMPLETE"
    }
  ]
}
```

### 3. `POST /api/predict`
Accepts simulated or real parameters and returns risk score, breakdown, and precautions.
**Request Body:**
```json
{
  "zone_id": "haldia",
  "rainfall_24h_mm": 75.0,
  "forecast_rain_7d_mm": 120.0,
  "river_discharge_m3s": 60.0
}
```
**Response (200 OK):**
```json
{
  "success": true,
  "zone_id": "haldia",
  "inputs": {
    "rainfall_24h_mm": 75.0,
    "forecast_rain_7d_mm": 120.0,
    "river_discharge_m3s": 60.0
  },
  "prediction": {
    "risk_score": 64.6,
    "risk_level": "HIGH",
    "color": "#f97316",
    "breakdown": {
      "rainfall_points": 26.7,
      "discharge_points": 22.9,
      "forecast_points": 11.7,
      "topography_points": 10.0
    },
    "contributing_factors": [
      {
        "factor": "24h Precipitation",
        "value": "75.0 mm",
        "impact": "Significant",
        "points": 26.7,
        "explanation": "Heavy rainfall exceeding moderate threshold (40.0 mm)."
      }
    ],
    "recommended_precautions": [
      "Inspect and reinforce vulnerable earthen river embankments and sluice gates.",
      "Clear blockages in trunk stormwater canals, municipal drains, and culverts."
    ]
  }
}
```

### 4. `GET /api/alerts`
Returns active alerts generated by documented thresholds.
```json
{
  "count": 1,
  "alerts": [
    {
      "alert_id": "alert-ghatal-severe",
      "zone_id": "ghatal",
      "zone_name": "Ghatal Sub-Division",
      "severity": "SEVERE",
      "title": "Flood Warning - Ghatal Sub-Division (SEVERE)",
      "reason": "River Discharge: 165.00 m³/s | 24h Precipitation: 98.0 mm",
      "risk_score": 88.5,
      "recommended_action": "EMERGENCY: Immediate evacuation of low-lying floodplains and fragile river embankments."
    }
  ]
}
```

### 5. `GET /api/zones`
Returns metadata and thresholds for all configured catchments.

### 6. `GET /api/summary`
Returns high-level KPI card metrics.

### 7. `GET /api/history?zone_id=haldia&limit=30`
Returns chronological observations for plotting trends.

### 8. `POST /api/refresh`
Triggers an immediate background fetch and risk re-evaluation.

---

## 7. Local Setup & Execution

### Prerequisites
- Python 3.10+ (tested on Python 3.11 and Python 3.14 on Windows)
- Git

### Installation
```bash
# Clone repository
git clone https://github.com/Voyage-Hack4Haldia-26/TEAM-C.git
cd TEAM-C

# Switch to solution branch
git checkout team-c-solution

# (Optional) Create virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run the Application
```bash
python app.py
```
Open your browser and navigate to:  
👉 **`http://localhost:5000`**

---

## 8. Automated Testing

Run the complete test suite (22 unit and integration tests):
```bash
python -m unittest discover tests
```

Output:
```
Ran 22 tests in 2.4s
OK
```

The test suite covers:
- Zero, negative, and extreme input validation (`sanitize_input`)
- Deterministic risk scoring and boundary condition validation
- Partial data handling (missing rainfall or missing river discharge)
- Compound storm surge synergy
- All REST API endpoints (`/health`, `/api/readings`, `/api/predict`, `/api/alerts`, `/api/zones`, `/api/history`, `/api/summary`)
- Error handling (bad JSON, invalid zones, out-of-bounds inputs, 404 handler)

---

## 9. Render Deployment Instructions

The application is fully prepared for zero-config production deployment on [Render](https://render.com).

### Option A: Automatic via Render Blueprint (`render.yaml`)
1. In the Render Dashboard, click **New +** -> **Blueprint**.
2. Connect the GitHub repository `Voyage-Hack4Haldia-26/TEAM-C` and branch `team-c-solution`.
3. Render automatically reads `render.yaml` and starts the service using Gunicorn.

### Option B: Manual Web Service
1. In Render, select **New Web Service**.
2. Connect repository `Voyage-Hack4Haldia-26/TEAM-C` with branch `team-c-solution`.
3. Configure settings:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
4. Deploy!

---

## 10. Data Attribution & Limitations

- **Precipitation Data:** Open-Meteo Weather Forecast API ([open-meteo.com](https://open-meteo.com/)). Open access under CC BY 4.0.
- **River Discharge Data:** Global Flood Awareness System (GloFAS) via Open-Meteo Flood API ([open-meteo.com/en/docs/flood-api](https://open-meteo.com/en/docs/flood-api)).
- **River Water Level Note:** In accordance with hydrological science, GloFAS models river discharge in volume rate ($m^3/s$). River water level in metres (gauge stage) is a local hydraulic property requiring calibrated cross-sectional bathymetry and physical staff gauges; our platform explicitly marks water level as gauge telemetry and never confuses discharge with gauge height.
- **Alert Nature:** All alerts generated by the Flood Early Warning System are heuristic early-warning indicators intended for emergency planning and hackathon evaluation; they do not supersede statutory civil defense directives issued by the West Bengal State Disaster Management Authority (WB-SDMA) or National Disaster Management Authority (NDMA).

---

## 11. Team C Contributors

- Hack4Haldia'26 — Team C
- Role: Full-Stack Engineering, Hydrological Modeling, Geospatial UI/UX, QA & Cloud Deployment
