"""
Data Ingestion Module for Hack4Haldia'26 - Team C Flood Early Warning System.
Integrates with Open-Meteo Weather Forecast API and Flood API.
Provides caching, robust error handling, data provenance tracking, and West Bengal zone definitions.
"""

import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("data_ingestion")

# Open-Meteo API Endpoints
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"

# Configured flood-prone zones in West Bengal, India
WEST_BENGAL_ZONES: Dict[str, Dict[str, Any]] = {
    "haldia": {
        "id": "haldia",
        "name": "Haldia Industrial & Port Zone",
        "district": "Purba Medinipur",
        "river_basin": "Haldi & Hooghly Estuary",
        "lat": 22.0667,
        "lon": 88.0698,
        "vulnerability": "High (Coastal port, tidal storm surge, industrial runoff)",
        "elevation_m": 7.0,
        "discharge_threshold_moderate": 25.0,  # m³/s indicative local river baseline
        "discharge_threshold_severe": 70.0,
        "rainfall_threshold_moderate": 40.0,   # mm in 24h
        "rainfall_threshold_severe": 85.0
    },
    "kolkata": {
        "id": "kolkata",
        "name": "Kolkata Metropolitan",
        "district": "Kolkata",
        "river_basin": "Lower Hooghly Delta",
        "lat": 22.5726,
        "lon": 88.3639,
        "vulnerability": "High (Urban waterlogging, high density, drainage lock during high tide)",
        "elevation_m": 9.0,
        "discharge_threshold_moderate": 40.0,
        "discharge_threshold_severe": 100.0,
        "rainfall_threshold_moderate": 50.0,
        "rainfall_threshold_severe": 95.0
    },
    "howrah": {
        "id": "howrah",
        "name": "Howrah Urban & Industrial Belt",
        "district": "Howrah",
        "river_basin": "Bhagirathi-Hooghly West Bank",
        "lat": 22.5958,
        "lon": 88.2636,
        "vulnerability": "Moderate-High (Low elevation bank, heavy monsoon inundation)",
        "elevation_m": 12.0,
        "discharge_threshold_moderate": 150.0,
        "discharge_threshold_severe": 350.0,
        "rainfall_threshold_moderate": 45.0,
        "rainfall_threshold_severe": 90.0
    },
    "diamond-harbour": {
        "id": "diamond-harbour",
        "name": "Diamond Harbour Estuary",
        "district": "South 24 Parganas",
        "river_basin": "Hooghly Tidal Estuary",
        "lat": 22.1985,
        "lon": 88.1925,
        "vulnerability": "Severe (Tidal bore, cyclone vulnerability, saline embankment breach risk)",
        "elevation_m": 8.0,
        "discharge_threshold_moderate": 30.0,
        "discharge_threshold_severe": 80.0,
        "rainfall_threshold_moderate": 45.0,
        "rainfall_threshold_severe": 90.0
    },
    "ghatal": {
        "id": "ghatal",
        "name": "Ghatal Sub-Division",
        "district": "Paschim Medinipur",
        "river_basin": "Silabati & Kangsabati Confluence",
        "lat": 22.6658,
        "lon": 87.7226,
        "vulnerability": "Critical (Chronically flooded basin; 'Ghatal Master Plan' area)",
        "elevation_m": 5.0,
        "discharge_threshold_moderate": 90.0,
        "discharge_threshold_severe": 220.0,
        "rainfall_threshold_moderate": 35.0,
        "rainfall_threshold_severe": 75.0
    },
    "farakka": {
        "id": "farakka",
        "name": "Farakka Barrage / Malda",
        "district": "Murshidabad / Malda",
        "river_basin": "Upper Ganga / Farakka Feeder",
        "lat": 24.7936,
        "lon": 87.9103,
        "vulnerability": "High (Major barrage, upstream Himalayan runoff discharge control)",
        "elevation_m": 25.0,
        "discharge_threshold_moderate": 200.0,
        "discharge_threshold_severe": 500.0,
        "rainfall_threshold_moderate": 50.0,
        "rainfall_threshold_severe": 100.0
    },
    "digha": {
        "id": "digha",
        "name": "Digha Coastal Belt",
        "district": "Purba Medinipur",
        "river_basin": "Bay of Bengal Coastal Zone",
        "lat": 21.6266,
        "lon": 87.5074,
        "vulnerability": "High (Coastal storm surge, high sea waves, sea-wall overtopping)",
        "elevation_m": 6.0,
        "discharge_threshold_moderate": 20.0,
        "discharge_threshold_severe": 60.0,
        "rainfall_threshold_moderate": 40.0,
        "rainfall_threshold_severe": 85.0
    },
    "jalpaiguri": {
        "id": "jalpaiguri",
        "name": "Jalpaiguri Teesta Basin",
        "district": "Jalpaiguri (North Bengal)",
        "river_basin": "Teesta & Karala Rivers",
        "lat": 26.5405,
        "lon": 88.7194,
        "vulnerability": "Critical (Flash floods, glacial lake outbursts upstream, rapid Teesta surge)",
        "elevation_m": 85.0,
        "discharge_threshold_moderate": 180.0,
        "discharge_threshold_severe": 400.0,
        "rainfall_threshold_moderate": 60.0,
        "rainfall_threshold_severe": 120.0
    }
}

# In-memory cache store: { zone_id: { "timestamp": float, "data": dict, "status": str } }
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 600  # 10 minutes cache to avoid hitting rate limits

# Pre-computed realistic baseline demo readings if external network is unavailable
DEMO_READINGS: Dict[str, Dict[str, Any]] = {
    "haldia": {
        "rainfall_current_mm": 18.5,
        "rainfall_24h_mm": 52.0,
        "forecast_rain_7d_mm": 115.0,
        "river_discharge_m3s": 38.4,
        "discharge_forecast_7d_m3s": [38.4, 42.1, 48.0, 52.5, 46.0, 40.0, 36.0],
        "river_water_level_m": None,  # Open-Meteo provides discharge in m³/s; water level is not measured by GloFAS
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "kolkata": {
        "rainfall_current_mm": 12.0,
        "rainfall_24h_mm": 44.0,
        "forecast_rain_7d_mm": 88.0,
        "river_discharge_m3s": 24.2,
        "discharge_forecast_7d_m3s": [24.2, 28.0, 32.5, 35.0, 30.0, 26.0, 24.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "howrah": {
        "rainfall_current_mm": 8.5,
        "rainfall_24h_mm": 32.0,
        "forecast_rain_7d_mm": 70.0,
        "river_discharge_m3s": 192.5,
        "discharge_forecast_7d_m3s": [192.5, 205.0, 220.0, 210.0, 195.0, 180.0, 175.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "diamond-harbour": {
        "rainfall_current_mm": 25.0,
        "rainfall_24h_mm": 72.0,
        "forecast_rain_7d_mm": 140.0,
        "river_discharge_m3s": 42.0,
        "discharge_forecast_7d_m3s": [42.0, 46.5, 51.0, 55.0, 48.0, 44.0, 40.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "ghatal": {
        "rainfall_current_mm": 34.0,
        "rainfall_24h_mm": 98.0,
        "forecast_rain_7d_mm": 185.0,
        "river_discharge_m3s": 165.0,
        "discharge_forecast_7d_m3s": [165.0, 172.0, 185.0, 198.0, 210.0, 215.0, 220.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "farakka": {
        "rainfall_current_mm": 5.0,
        "rainfall_24h_mm": 18.0,
        "forecast_rain_7d_mm": 45.0,
        "river_discharge_m3s": 320.0,
        "discharge_forecast_7d_m3s": [320.0, 340.0, 365.0, 380.0, 350.0, 330.0, 310.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "digha": {
        "rainfall_current_mm": 21.0,
        "rainfall_24h_mm": 64.0,
        "forecast_rain_7d_mm": 130.0,
        "river_discharge_m3s": 14.8,
        "discharge_forecast_7d_m3s": [14.8, 16.5, 19.0, 21.0, 18.0, 15.5, 14.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    },
    "jalpaiguri": {
        "rainfall_current_mm": 42.0,
        "rainfall_24h_mm": 115.0,
        "forecast_rain_7d_mm": 240.0,
        "river_discharge_m3s": 380.0,
        "discharge_forecast_7d_m3s": [380.0, 395.0, 410.0, 390.0, 360.0, 340.0, 320.0],
        "river_water_level_m": None,
        "discharge_status": "AVAILABLE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Flood/Forecast (Demo Fallback)",
        "freshness": "DEMO"
    }
}


def fetch_zone_data(zone_id: str, force_refresh: bool = False, demo_mode: bool = False) -> Dict[str, Any]:
    """
    Fetch weather and flood data for a single zone.
    Returns structured reading with provenance, units, and timestamps.
    """
    if zone_id not in WEST_BENGAL_ZONES:
        raise ValueError(f"Unknown zone: {zone_id}")

    zone = WEST_BENGAL_ZONES[zone_id]
    now = time.time()

    if demo_mode:
        demo = dict(DEMO_READINGS.get(zone_id, {}))
        demo["zone_id"] = zone_id
        demo["zone_name"] = zone["name"]
        demo["district"] = zone["district"]
        demo["lat"] = zone["lat"]
        demo["lon"] = zone["lon"]
        demo["freshness"] = "DEMO"
        demo["timestamp"] = datetime.now(timezone.utc).isoformat()
        return demo

    # Check cache
    cached = _CACHE.get(zone_id)
    if not force_refresh and cached and (now - cached["timestamp"] < CACHE_TTL_SECONDS):
        res = dict(cached["data"])
        res["freshness"] = "CACHED"
        return res

    lat = zone["lat"]
    lon = zone["lon"]
    weather_resp = None
    flood_resp = None
    errors = []

    # 1. Fetch Weather API
    try:
        w_url = (
            f"{WEATHER_API_URL}?latitude={lat}&longitude={lon}"
            f"&current=precipitation,rain,showers"
            f"&daily=precipitation_sum,rain_sum"
            f"&hourly=precipitation"
            f"&timezone=Asia/Kolkata"
        )
        r = requests.get(w_url, timeout=6.0)
        if r.status_code == 200:
            weather_resp = r.json()
        else:
            errors.append(f"Weather API status {r.status_code}")
    except Exception as e:
        logger.warning(f"Failed to fetch Weather API for {zone_id}: {e}")
        errors.append(f"Weather API exception: {str(e)}")

    # 2. Fetch Flood API (GloFAS river discharge)
    try:
        f_url = (
            f"{FLOOD_API_URL}?latitude={lat}&longitude={lon}"
            f"&daily=river_discharge,river_discharge_mean,river_discharge_max"
            f"&timezone=Asia/Kolkata"
        )
        r = requests.get(f_url, timeout=6.0)
        if r.status_code == 200:
            flood_resp = r.json()
        else:
            errors.append(f"Flood API status {r.status_code}")
    except Exception as e:
        logger.warning(f"Failed to fetch Flood API for {zone_id}: {e}")
        errors.append(f"Flood API exception: {str(e)}")

    # If both failed and we have existing cache, return stale cache
    if not weather_resp and not flood_resp and cached:
        logger.warning(f"Using stale cache for {zone_id} due to API failures.")
        res = dict(cached["data"])
        res["freshness"] = "CACHED"
        res["warning"] = "Upstream API unavailable; served from cache"
        return res

    # If both failed and no cache, fallback to DEMO with clear indicator
    if not weather_resp and not flood_resp:
        logger.error(f"Both APIs failed for {zone_id}. Falling back to demo data.")
        demo = dict(DEMO_READINGS.get(zone_id, {}))
        demo["zone_id"] = zone_id
        demo["zone_name"] = zone["name"]
        demo["district"] = zone["district"]
        demo["lat"] = zone["lat"]
        demo["lon"] = zone["lon"]
        demo["freshness"] = "DEMO"
        demo["api_errors"] = errors
        demo["warning"] = "Live API unavailable. Displaying baseline fallback data."
        return demo

    # Parse weather data
    rainfall_current = None
    rainfall_24h = None
    forecast_rain_7d = None

    if weather_resp:
        curr = weather_resp.get("current", {})
        raw_curr = curr.get("precipitation")
        rainfall_current = float(raw_curr) if raw_curr is not None else 0.0
        
        # Calculate recent 24h precipitation from hourly or daily
        hourly_precip = weather_resp.get("hourly", {}).get("precipitation", [])
        if hourly_precip and len(hourly_precip) >= 24:
            valid_hourly = [float(v) for v in hourly_precip[:24] if v is not None]
            if valid_hourly:
                rainfall_24h = round(float(sum(valid_hourly)), 2)
        else:
            daily_precip = weather_resp.get("daily", {}).get("precipitation_sum", [])
            if daily_precip and daily_precip[0] is not None:
                rainfall_24h = round(float(daily_precip[0]), 2)

        daily_sums = weather_resp.get("daily", {}).get("precipitation_sum", [])
        if daily_sums:
            valid_daily = [float(v) for v in daily_sums[:7] if v is not None]
            if valid_daily:
                forecast_rain_7d = round(float(sum(valid_daily)), 2)

    # Parse river discharge
    river_discharge = None
    discharge_status = "UNAVAILABLE"
    discharge_forecast = []

    if flood_resp:
        daily_flood = flood_resp.get("daily", {})
        discharges = daily_flood.get("river_discharge", [])
        if discharges and any(v is not None for v in discharges):
            # First valid day value
            valid_discharges = [v for v in discharges if v is not None]
            if valid_discharges:
                river_discharge = round(float(valid_discharges[0]), 2)
                discharge_status = "AVAILABLE"
                discharge_forecast = [round(float(v), 2) for v in valid_discharges[:7]]
        else:
            discharge_status = "UNAVAILABLE_FOR_COORDINATE"
    else:
        discharge_status = "API_ERROR"

    # Assemble reading
    reading = {
        "zone_id": zone_id,
        "zone_name": zone["name"],
        "district": zone["district"],
        "river_basin": zone["river_basin"],
        "lat": zone["lat"],
        "lon": zone["lon"],
        "elevation_m": zone["elevation_m"],
        "vulnerability": zone["vulnerability"],
        "rainfall_current_mm": rainfall_current,
        "rainfall_24h_mm": rainfall_24h,
        "forecast_rain_7d_mm": forecast_rain_7d,
        "river_discharge_m3s": river_discharge,
        "discharge_forecast_7d_m3s": discharge_forecast,
        "river_water_level_m": None,  # Explicit: GloFAS produces discharge (m³/s), not water level (m)
        "water_level_note": "Discharge is measured in m³/s. River water level (m) requires local gauge telemetry.",
        "discharge_status": discharge_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Open-Meteo Forecast & GloFAS Flood APIs",
        "freshness": "LIVE",
        "api_errors": errors if errors else None
    }

    # Save in memory cache
    _CACHE[zone_id] = {
        "timestamp": now,
        "data": reading,
        "status": "LIVE"
    }

    return reading


def fetch_all_zones(force_refresh: bool = False, demo_mode: bool = False) -> List[Dict[str, Any]]:
    """
    Fetch current readings for all configured West Bengal zones.
    """
    results = []
    for zone_id in WEST_BENGAL_ZONES:
        try:
            reading = fetch_zone_data(zone_id, force_refresh=force_refresh, demo_mode=demo_mode)
            results.append(reading)
        except Exception as e:
            logger.error(f"Error fetching zone {zone_id}: {e}")
            # Fallback to demo entry
            demo = dict(DEMO_READINGS.get(zone_id, {}))
            demo["zone_id"] = zone_id
            demo["zone_name"] = WEST_BENGAL_ZONES[zone_id]["name"]
            demo["district"] = WEST_BENGAL_ZONES[zone_id]["district"]
            demo["lat"] = WEST_BENGAL_ZONES[zone_id]["lat"]
            demo["lon"] = WEST_BENGAL_ZONES[zone_id]["lon"]
            demo["freshness"] = "DEMO"
            demo["warning"] = f"Fetch failed: {str(e)}"
            results.append(demo)
    return results


def check_upstream_health() -> Dict[str, Any]:
    """
    Check availability of external weather and flood APIs.
    """
    status = {"weather_api": "unknown", "flood_api": "unknown", "overall": "ok"}
    try:
        r = requests.get(f"{WEATHER_API_URL}?latitude=22.06&longitude=88.07&current=precipitation", timeout=4.0)
        status["weather_api"] = "reachable" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        status["weather_api"] = f"unreachable: {str(e)}"

    try:
        r = requests.get(f"{FLOOD_API_URL}?latitude=22.06&longitude=88.07&daily=river_discharge", timeout=4.0)
        status["flood_api"] = "reachable" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        status["flood_api"] = f"unreachable: {str(e)}"

    if "unreachable" in status["weather_api"] and "unreachable" in status["flood_api"]:
        status["overall"] = "degraded"

    return status

