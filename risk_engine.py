"""
Flood Risk Engine for Hack4Haldia'26 - Team C.
Deterministic, explainable, heuristic flood vulnerability & risk assessment model.
Combines 24h precipitation, forecast precipitation, river discharge rates,
and zone-specific hydrological characteristics into an explainable 0-100 score.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# Documented Risk Level Categorization
# LOW: 0 - 29 (Normal conditions; routine monitoring)
# MODERATE: 30 - 59 (Advisory conditions; check local culverts/drains)
# HIGH: 60 - 79 (Warning conditions; waterlogging expected, high river discharge)
# SEVERE: 80 - 100 (Emergency alert; imminent inundation risk, evacuation readiness)

ZONE_HYDROLOGY_DEFAULTS = {
    "haldia": {
        "elevation_m": 7.0,
        "is_coastal_tidal": True,
        "discharge_threshold_moderate": 25.0,
        "discharge_threshold_severe": 70.0,
        "rainfall_threshold_moderate": 40.0,
        "rainfall_threshold_severe": 85.0,
    },
    "kolkata": {
        "elevation_m": 9.0,
        "is_coastal_tidal": True,
        "discharge_threshold_moderate": 40.0,
        "discharge_threshold_severe": 100.0,
        "rainfall_threshold_moderate": 50.0,
        "rainfall_threshold_severe": 95.0,
    },
    "howrah": {
        "elevation_m": 12.0,
        "is_coastal_tidal": False,
        "discharge_threshold_moderate": 150.0,
        "discharge_threshold_severe": 350.0,
        "rainfall_threshold_moderate": 45.0,
        "rainfall_threshold_severe": 90.0,
    },
    "diamond-harbour": {
        "elevation_m": 8.0,
        "is_coastal_tidal": True,
        "discharge_threshold_moderate": 30.0,
        "discharge_threshold_severe": 80.0,
        "rainfall_threshold_moderate": 45.0,
        "rainfall_threshold_severe": 90.0,
    },
    "ghatal": {
        "elevation_m": 5.0,
        "is_coastal_tidal": False,
        "discharge_threshold_moderate": 90.0,
        "discharge_threshold_severe": 220.0,
        "rainfall_threshold_moderate": 35.0,
        "rainfall_threshold_severe": 75.0,
    },
    "farakka": {
        "elevation_m": 25.0,
        "is_coastal_tidal": False,
        "discharge_threshold_moderate": 200.0,
        "discharge_threshold_severe": 500.0,
        "rainfall_threshold_moderate": 50.0,
        "rainfall_threshold_severe": 100.0,
    },
    "digha": {
        "elevation_m": 6.0,
        "is_coastal_tidal": True,
        "discharge_threshold_moderate": 20.0,
        "discharge_threshold_severe": 60.0,
        "rainfall_threshold_moderate": 40.0,
        "rainfall_threshold_severe": 85.0,
    },
    "jalpaiguri": {
        "elevation_m": 85.0,
        "is_coastal_tidal": False,
        "discharge_threshold_moderate": 180.0,
        "discharge_threshold_severe": 400.0,
        "rainfall_threshold_moderate": 60.0,
        "rainfall_threshold_severe": 120.0,
    }
}


def sanitize_input(value: Any, min_val: float = 0.0, max_val: float = 10000.0) -> Optional[float]:
    """
    Safely validates and casts numeric input.
    Returns None if missing or invalid. Clamps negative values or marks as invalid.
    """
    if value is None:
        return None
    try:
        val = float(value)
        if val < 0:
            return None  # Negative rainfall/discharge is physically invalid
        return min(val, max_val)
    except (ValueError, TypeError):
        return None


def get_risk_category(score: float) -> Tuple[str, str]:
    """
    Maps 0-100 risk score to category and color code.
    """
    if score >= 80.0:
        return "SEVERE", "#ef4444"    # Red
    elif score >= 60.0:
        return "HIGH", "#f97316"      # Orange
    elif score >= 30.0:
        return "MODERATE", "#eab308"  # Yellow
    else:
        return "LOW", "#22c55e"       # Green


def compute_flood_risk(
    zone_id: Optional[str] = None,
    rainfall_24h_mm: Optional[float] = None,
    forecast_rain_7d_mm: Optional[float] = None,
    river_discharge_m3s: Optional[float] = None,
    custom_zone_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Explainable, deterministic baseline flood risk calculation.
    
    Weights & Scoring Breakdown (Total Max = 100):
    1. Recent 24h Rainfall: Up to 40 points
    2. River Discharge: Up to 35 points
    3. Forecast 7-Day Cumulative Rain: Up to 15 points
    4. Zone Geomorphology & Tidal Vulnerability: Up to 10 points
    
    If discharge or rainfall is missing, model normalizes available features
    and indicates data completeness in 'data_quality'.
    """
    factors = []
    zone_key = zone_id.lower() if zone_id else "generic"
    config = custom_zone_config or ZONE_HYDROLOGY_DEFAULTS.get(zone_key, {
        "elevation_m": 10.0,
        "is_coastal_tidal": False,
        "discharge_threshold_moderate": 50.0,
        "discharge_threshold_severe": 150.0,
        "rainfall_threshold_moderate": 45.0,
        "rainfall_threshold_severe": 90.0,
    })

    # Validate inputs
    clean_rain_24h = sanitize_input(rainfall_24h_mm)
    clean_forecast_rain = sanitize_input(forecast_rain_7d_mm)
    clean_discharge = sanitize_input(river_discharge_m3s)

    # Determine Data Quality
    has_rain = clean_rain_24h is not None
    has_discharge = clean_discharge is not None
    has_forecast = clean_forecast_rain is not None

    if has_rain and has_discharge:
        data_quality = "COMPLETE"
        quality_desc = "High confidence: both precipitation and river discharge observed."
    elif has_rain and not has_discharge:
        data_quality = "PARTIAL_PRECIP_ONLY"
        quality_desc = "Moderate confidence: river discharge data unavailable for this coordinate; scaled on precipitation and catchment topology."
    elif not has_rain and has_discharge:
        data_quality = "PARTIAL_DISCHARGE_ONLY"
        quality_desc = "Moderate confidence: precipitation missing; risk scaled primarily on upstream river discharge telemetry."
    else:
        data_quality = "DEGRADED"
        quality_desc = "Low confidence: missing both precipitation and river discharge; baseline contextual risk applied."

    # Component 1: 24-Hour Rainfall Score (0 - 40 points)
    rain_pts = 0.0
    rain_mod = config["rainfall_threshold_moderate"]
    rain_sev = config["rainfall_threshold_severe"]

    if has_rain:
        if clean_rain_24h <= 5.0:
            rain_pts = clean_rain_24h * 0.4  # Minimal risk (0-2 pts)
            factors.append({
                "factor": "24h Precipitation",
                "value": f"{clean_rain_24h:.1f} mm",
                "impact": "Negligible",
                "points": round(rain_pts, 1),
                "explanation": "Dry or minimal rainfall in the past 24 hours."
            })
        elif clean_rain_24h < rain_mod:
            # Linear scaling up to moderate threshold (2 to 15 pts)
            ratio = (clean_rain_24h - 5.0) / max(1.0, (rain_mod - 5.0))
            rain_pts = 2.0 + ratio * 13.0
            factors.append({
                "factor": "24h Precipitation",
                "value": f"{clean_rain_24h:.1f} mm",
                "impact": "Low-Moderate",
                "points": round(rain_pts, 1),
                "explanation": f"Moderate rainfall below zone advisory threshold ({rain_mod} mm)."
            })
        elif clean_rain_24h < rain_sev:
            # Moderate to Severe threshold (15 to 30 pts)
            ratio = (clean_rain_24h - rain_mod) / max(1.0, (rain_sev - rain_mod))
            rain_pts = 15.0 + ratio * 15.0
            factors.append({
                "factor": "24h Precipitation",
                "value": f"{clean_rain_24h:.1f} mm",
                "impact": "Significant",
                "points": round(rain_pts, 1),
                "explanation": f"Heavy rainfall exceeding moderate threshold ({rain_mod} mm)."
            })
        else:
            # Extreme rainfall above severe threshold (30 to 40 pts max)
            excess = min(100.0, clean_rain_24h - rain_sev)
            rain_pts = 30.0 + (excess / 100.0) * 10.0
            factors.append({
                "factor": "24h Precipitation",
                "value": f"{clean_rain_24h:.1f} mm",
                "impact": "Severe",
                "points": round(rain_pts, 1),
                "explanation": f"Torrential precipitation exceeding danger threshold ({rain_sev} mm)."
            })
    else:
        factors.append({
            "factor": "24h Precipitation",
            "value": "Unavailable",
            "impact": "Unknown",
            "points": 0.0,
            "explanation": "No precipitation telemetry available; rainfall risk not computed."
        })

    # Component 2: River Discharge Score (0 - 35 points)
    discharge_pts = 0.0
    disc_mod = config["discharge_threshold_moderate"]
    disc_sev = config["discharge_threshold_severe"]

    if has_discharge:
        if clean_discharge < disc_mod:
            # Within safe bank capacity (0 to 12 pts)
            discharge_pts = (clean_discharge / max(1.0, disc_mod)) * 12.0
            factors.append({
                "factor": "River Discharge",
                "value": f"{clean_discharge:.2f} m³/s",
                "impact": "Within Capacity",
                "points": round(discharge_pts, 1),
                "explanation": f"Discharge is within safe hydrological carrying limits (advisory threshold: {disc_mod} m³/s)."
            })
        elif clean_discharge < disc_sev:
            # Bankfull stage approaching warning levels (12 to 26 pts)
            ratio = (clean_discharge - disc_mod) / max(1.0, (disc_sev - disc_mod))
            discharge_pts = 12.0 + ratio * 14.0
            factors.append({
                "factor": "River Discharge",
                "value": f"{clean_discharge:.2f} m³/s",
                "impact": "High Discharge",
                "points": round(discharge_pts, 1),
                "explanation": f"Discharge exceeds advisory threshold ({disc_mod} m³/s); banks at elevated risk of overtopping."
            })
        else:
            # Overbank danger stage (26 to 35 pts max)
            excess = min(disc_sev * 2, clean_discharge - disc_sev)
            discharge_pts = 26.0 + (excess / max(1.0, disc_sev * 2)) * 9.0
            factors.append({
                "factor": "River Discharge",
                "value": f"{clean_discharge:.2f} m³/s",
                "impact": "Critical Surge",
                "points": round(discharge_pts, 1),
                "explanation": f"Dangerous river surge exceeding severe threshold ({disc_sev} m³/s); flood plain inundation probable."
            })
    else:
        factors.append({
            "factor": "River Discharge",
            "value": "Unavailable (GloFAS)",
            "impact": "Not Monitored",
            "points": 0.0,
            "explanation": "No river discharge sensor or GloFAS river grid cell at this exact coordinate."
        })

    # Component 3: Forecast 7-Day Precipitation Score (0 - 15 points)
    forecast_pts = 0.0
    if has_forecast:
        if clean_forecast_rain > 150.0:
            forecast_pts = 15.0
            factors.append({
                "factor": "7-Day Cumulative Rain Forecast",
                "value": f"{clean_forecast_rain:.1f} mm",
                "impact": "High Inundation Risk",
                "points": 15.0,
                "explanation": "Prolonged intense rain spell will cause severe soil saturation."
            })
        elif clean_forecast_rain > 60.0:
            forecast_pts = 5.0 + ((clean_forecast_rain - 60.0) / 90.0) * 10.0
            factors.append({
                "factor": "7-Day Cumulative Rain Forecast",
                "value": f"{clean_forecast_rain:.1f} mm",
                "impact": "Moderate Outlook",
                "points": round(forecast_pts, 1),
                "explanation": "Substantial rain expected over next 7 days."
            })
        else:
            forecast_pts = (clean_forecast_rain / 60.0) * 5.0
            factors.append({
                "factor": "7-Day Cumulative Rain Forecast",
                "value": f"{clean_forecast_rain:.1f} mm",
                "impact": "Normal Outlook",
                "points": round(forecast_pts, 1),
                "explanation": "Routine forecasted precipitation."
            })

    # Component 4: Geomorphology & Tidal Vulnerability (0 - 10 points)
    topo_pts = 0.0
    if config.get("is_coastal_tidal", False):
        topo_pts += 5.0
        factors.append({
            "factor": "Tidal Estuary / Coastal Factor",
            "value": "Tidal Zone",
            "impact": "Drainage Impedance",
            "points": 5.0,
            "explanation": "Low-lying estuarine terrain experiences drainage lock during astronomical high tides."
        })

    elev = config.get("elevation_m", 15.0)
    if elev < 8.0:
        topo_pts += 5.0
        factors.append({
            "factor": "Low Elevation Terrain",
            "value": f"{elev} m AMSL",
            "impact": "High Susceptibility",
            "points": 5.0,
            "explanation": "Extremely low elevation (< 8m) severely impairs natural gravity drainage."
        })
    elif elev < 15.0:
        topo_pts += 2.0

    # Compound synergy: If both 24h rain and river discharge are above moderate thresholds,
    # compound flood risk compounds exponentially (saturated ground + swollen river).
    compound_bonus = 0.0
    if has_rain and has_discharge:
        if clean_rain_24h >= rain_mod and clean_discharge >= disc_mod:
            compound_bonus = 5.0
        if clean_rain_24h >= rain_sev and clean_discharge >= disc_sev:
            compound_bonus = 10.0

    # Total Raw Score
    raw_score = rain_pts + discharge_pts + forecast_pts + topo_pts + compound_bonus

    # Normalization when one telemetry component is missing
    final_score = raw_score
    if not has_discharge and has_rain:
        # Scale remaining components proportionally so full risk scale is reachable
        # Available max weight was: 40 (rain) + 15 (forecast) + 10 (topo) = 65
        final_score = (raw_score / 65.0) * 100.0
    elif not has_rain and has_discharge:
        # When rain is missing, discharge is our primary hazard indicator (max discharge 35 + topo 10 = 45)
        # If discharge exceeds severe threshold, ensure high/severe risk can be triggered
        final_score = (discharge_pts / 35.0) * 85.0 + (topo_pts / 10.0) * 15.0
    elif not has_rain and not has_discharge:
        # Fallback to topology baseline only
        final_score = min(25.0, raw_score)

    final_score = max(0.0, min(100.0, round(final_score, 1)))
    risk_level, color_hex = get_risk_category(final_score)

    # Precautionary Actions Based on Level & Factors
    precautions = get_precautionary_actions(risk_level, zone_key, final_score)

    return {
        "zone_id": zone_key,
        "risk_score": final_score,
        "risk_level": risk_level,
        "color": color_hex,
        "data_quality": data_quality,
        "data_quality_description": quality_desc,
        "breakdown": {
            "rainfall_points": round(rain_pts, 1),
            "discharge_points": round(discharge_pts, 1),
            "forecast_points": round(forecast_pts, 1),
            "topography_points": round(topo_pts, 1),
            "raw_sum": round(raw_score, 1),
            "normalized_score": final_score
        },
        "contributing_factors": factors,
        "recommended_precautions": precautions,
        "disclaimer": "Heuristic risk indicator based on open atmospheric & hydrological models; not an official NDMA/WB-SDMA civil defense order.",
        "evaluated_at": datetime.now(timezone.utc).isoformat()
    }


def get_precautionary_actions(risk_level: str, zone_id: str, score: float) -> List[str]:
    """
    Returns tailored civil defense and citizen precautionary actions.
    """
    actions = []
    if risk_level == "SEVERE":
        actions.append("EMERGENCY: Immediate evacuation of low-lying floodplains and fragile river embankments.")
        actions.append("Activate municipal high-capacity dewatering pump stations and emergency flood gates.")
        actions.append("Relocate livestock, food grains, and potable water storage to multi-purpose flood shelters.")
        actions.append("Avoid traversing submerged roads, culverts, and causeways; risk of rapid undercurrents.")
        actions.append("Report embankment breaches or sluice gate failures immediately to District Disaster Management.")
    elif risk_level == "HIGH":
        actions.append("Inspect and reinforce vulnerable earthen river embankments and sluice gates.")
        actions.append("Clear blockages in trunk stormwater canals, municipal drains, and culverts.")
        actions.append("Prepare emergency supply kits: dry food, clean drinking water, chlorine tablets, torch, battery radio.")
        actions.append("Secure fishing boats and riverine transport; suspend non-essential water vessel movement.")
        actions.append("Establish localized community alert watchpoints along rising riverbanks.")
    elif risk_level == "MODERATE":
        actions.append("Advisory: Check local municipal drainage outlets and clear debris from street drains.")
        actions.append("Farmers should ensure drainage trenches around standing Kharif crops are unblocked.")
        actions.append("Monitor regional weather updates and river basin advisories regularly.")
        actions.append("Keep emergency helpline numbers (1070 state disaster helpline) accessible.")
    else:  # LOW
        actions.append("Conditions normal: Regular maintenance of drainage infrastructure.")
        actions.append("Routine river level monitoring and meteorological tracking.")

    # Zone-specific nuance
    if "haldia" in zone_id or "diamond-harbour" in zone_id or "digha" in zone_id:
        if score >= 50.0:
            actions.append("Coastal/Estuary Alert: Coordinate with Kolkata Port / Haldia Port Trust regarding high tide synchronization.")

    return actions
