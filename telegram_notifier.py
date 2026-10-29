"""
Telegram Alerting Service for Team C: Flood Early Warning System.
Hack4Haldia'26

Integrates with the official Telegram Bot API (sendMessage).
Features:
- Secure credential management via environment variables (never leaked in logs)
- Strict Asia/Kolkata timestamp formatting
- Hydrologically accurate telemetry representation (GloFAS daily forecast vs physical gauge)
- Robust error handling (Telegram failures never crash data ingestion)
- Clean, structured HTML alert formatting
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import requests
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

logger = logging.getLogger("telegram_notifier")

# Kolkata Timezone (UTC +5:30)
try:
    from zoneinfo import ZoneInfo
    KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    KOLKATA_TZ = timezone(timedelta(hours=5, minutes=30))

TELEGRAM_API_URL = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 8.0


def get_telegram_credentials() -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    Strips whitespace and returns (bot_token, chat_id).
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    bot_token = bot_token.strip() if bot_token else None
    chat_id = chat_id.strip() if chat_id else None
    return bot_token, chat_id


def mask_token(token: Optional[str]) -> str:
    """Safely masks Telegram bot token for diagnostic logging without leaking secrets."""
    if not token:
        return "<NOT_SET>"
    if len(token) <= 8:
        return "***"
    return f"{token[:5]}...{token[-4:]}"


def format_kolkata_time(iso_str: Optional[str] = None) -> str:
    """Converts UTC ISO timestamp to human-readable Asia/Kolkata string."""
    try:
        if not iso_str:
            dt = datetime.now(timezone.utc)
        else:
            clean_str = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
        dt_kolkata = dt.astimezone(KOLKATA_TZ)
        return dt_kolkata.strftime("%d %b %Y, %I:%M:%S %p IST")
    except Exception:
        now_kolkata = datetime.now(KOLKATA_TZ)
        return now_kolkata.strftime("%d %b %Y, %I:%M:%S %p IST")


def format_forecast_date(iso_str: Optional[str] = None) -> str:
    """Formats the current/forecast date in Asia/Kolkata."""
    try:
        if not iso_str:
            dt = datetime.now(timezone.utc)
        else:
            clean_str = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
        return dt.astimezone(KOLKATA_TZ).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(KOLKATA_TZ).strftime("%Y-%m-%d")


def build_alert_message(
    zone_data: Dict[str, Any],
    risk_data: Dict[str, Any],
    event_type: str = "NEW_ALERT",
    previous_level: Optional[str] = None
) -> str:
    """
    Constructs an official, hydrologically truthful HTML alert message.
    Satisfies Requirement 9:
    - Catchment name & district
    - Risk score and category
    - Rainfall with time window
    - River discharge with forecast date and GloFAS note
    - Telemetry freshness
    - Timestamp in Asia/Kolkata
    - Precautionary message
    - Clear label for unavailable values; never fabricated zeros.
    """
    zone_name = zone_data.get("zone_name") or zone_data.get("name") or "West Bengal Catchment"
    district = zone_data.get("district") or "West Bengal"
    river_basin = zone_data.get("river_basin") or "Local River Basin"
    
    score = round(float(risk_data.get("risk_score", 0.0)), 1)
    level = str(risk_data.get("risk_level", "LOW")).upper()
    freshness = str(zone_data.get("freshness", "LIVE")).upper()
    timestamp_ist = format_kolkata_time(zone_data.get("timestamp"))
    forecast_date = format_forecast_date(zone_data.get("timestamp"))

    # Event header
    if event_type == "ESCALATION":
        header_badge = "🚨 <b>FLOOD RISK ESCALATION WARNING</b>"
        transition_note = f"⚠️ <i>Risk escalated from {previous_level} to <b>{level}</b></i>"
    elif event_type == "RECOVERY":
        header_badge = "ℹ️ <b>FLOOD RISK RECOVERY ADVISORY</b>"
        transition_note = f"✓ <i>Catchment de-escalated from {previous_level} to safe baseline <b>{level}</b></i>"
    else:
        header_badge = f"🚨 <b>FLOOD EARLY WARNING — {level} RISK</b>"
        transition_note = f"⚠️ <i>Threshold crossed: Catchment entered <b>{level}</b> risk</i>"

    # Rainfall representation (truthful: past 24-hour accumulation)
    raw_rain = zone_data.get("rainfall_24h_mm")
    if raw_rain is not None:
        rain_text = f"<b>{float(raw_rain):.1f} mm</b> (Observed Past 24h)"
    else:
        rain_text = "<i>Unavailable</i>"

    # River discharge representation (truthful: GloFAS daily forecast model)
    raw_discharge = zone_data.get("river_discharge_m3s")
    if raw_discharge is not None:
        discharge_text = (
            f"<b>{float(raw_discharge):.2f} m³/s</b> "
            f"(GloFAS daily forecast for {forecast_date})"
        )
    else:
        discharge_text = "<i>Unavailable (GloFAS river cell n/a)</i>"

    # Primary precautionary action
    precautions = risk_data.get("recommended_precautions", [])
    if precautions:
        primary_action = precautions[0]
    else:
        primary_action = "Maintain continuous hydrological monitoring and adhere to district disaster advisories."

    # Top contributing risk factors
    factors = risk_data.get("contributing_factors", [])
    top_factor_bullets = []
    for f in factors:
        if f.get("points", 0) >= 10.0:
            top_factor_bullets.append(f"• {f.get('factor')}: {f.get('value')} (+{f.get('points')} pts)")
    
    factors_section = ""
    if top_factor_bullets:
        factors_section = "<b>Key Risk Drivers:</b>\n" + "\n".join(top_factor_bullets) + "\n\n"

    # Complete structured message
    message = (
        f"{header_badge}\n"
        f"<b>Project:</b> Flood Early Warning • Team C\n"
        f"{transition_note}\n\n"
        f"📍 <b>Catchment:</b> {zone_name}\n"
        f"🏛 <b>District:</b> {district}\n"
        f"🌊 <b>River Basin:</b> {river_basin}\n"
        f"📊 <b>Risk Index:</b> <b>{score} / 100</b> ({level})\n\n"
        f"🌧 <b>Precipitation:</b> {rain_text}\n"
        f"🌊 <b>River Discharge:</b> {discharge_text}\n"
        f"📡 <b>Source Freshness:</b> {freshness}\n"
        f"🕒 <b>Observed At:</b> {timestamp_ist}\n\n"
        f"{factors_section}"
        f"⚡ <b>Recommended Action:</b>\n{primary_action}\n\n"
        f"ℹ️ <i>Notice: River discharge is derived from Copernicus GloFAS 0.05° daily grid routing. "
        f"Water level (m) requires localized gauge stations.</i>"
    )
    return message


def build_test_message(timestamp_iso: Optional[str] = None) -> str:
    """Builds a verified test notification that does not represent a real emergency."""
    time_ist = format_kolkata_time(timestamp_iso)
    return (
        f"🧪 <b>[INTEGRATION TEST] Flood Early Warning System</b>\n"
        f"<b>Status:</b> Telegram Alerting Service Connected Successfully\n"
        f"<b>Project:</b> Team C: Flood Early Warning • Hack4Haldia'26\n"
        f"<b>Timestamp:</b> {time_ist}\n\n"
        f"✓ Telegram Bot API <code>sendMessage</code> verified.\n"
        f"✓ Formatting mode: HTML enabled.\n"
        f"✓ Asia/Kolkata timezone operational.\n"
        f"ℹ️ <i>This is an authorized verification message. No active flood alert was created.</i>"
    )


def send_telegram_message(
    text: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML"
) -> Dict[str, Any]:
    """
    Sends a message via Telegram Bot API sendMessage endpoint.
    Guarantees:
    - Token is never exposed in logs or exception messages.
    - Network/API failures do not crash the caller.
    - Returns standardized status dict.
    """
    token = bot_token or get_telegram_credentials()[0]
    target_chat = chat_id or get_telegram_credentials()[1]

    if not token or not target_chat:
        logger.warning(
            "Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. (token: %s, chat: %s)",
            mask_token(token),
            target_chat or "<NOT_SET>"
        )
        return {
            "success": False,
            "status": "SKIPPED_NO_CREDS",
            "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured in environment.",
            "message_id": None
        }

    url = f"{TELEGRAM_API_URL}/bot{token}/sendMessage"
    payload = {
        "chat_id": str(target_chat),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        
        if response.status_code == 200:
            res_data = response.json()
            message_id = res_data.get("result", {}).get("message_id")
            logger.info(
                "Telegram message delivered successfully to chat %s (message_id: %s)",
                target_chat,
                message_id
            )
            return {
                "success": True,
                "status": "SUCCESS",
                "message_id": message_id,
                "error": None
            }
        else:
            try:
                err_json = response.json()
                err_desc = err_json.get("description", response.text[:200])
            except Exception:
                err_desc = response.text[:200]

            logger.error(
                "Telegram API error (HTTP %s): %s for chat %s",
                response.status_code,
                err_desc,
                target_chat
            )
            return {
                "success": False,
                "status": "FAILED",
                "http_status": response.status_code,
                "error": err_desc,
                "message_id": None
            }

    except requests.exceptions.Timeout:
        logger.error("Telegram API request timed out after %s seconds for chat %s", REQUEST_TIMEOUT_SECONDS, target_chat)
        return {
            "success": False,
            "status": "FAILED",
            "error": f"Connection timed out after {REQUEST_TIMEOUT_SECONDS}s.",
            "message_id": None
        }
    except Exception as e:
        logger.error("Unexpected error delivering Telegram message to chat %s: %s", target_chat, str(e))
        return {
            "success": False,
            "status": "FAILED",
            "error": str(e),
            "message_id": None
        }


def send_test_notification() -> Dict[str, Any]:
    """Sends a verification test notification to Telegram."""
    msg = build_test_message()
    return send_telegram_message(msg)


def build_simulated_high_risk_message(
    zone_name: str = "Ghatal Sub-Division",
    district: str = "Paschim Medinipur",
    river_basin: str = "Silabati & Kangsabati Confluence",
    rainfall_24h_mm: float = 94.0,
    river_discharge_m3s: float = 142.50,
    risk_score: float = 78.5
) -> str:
    """
    Builds a test-only simulated HIGH-risk alert for drills and verification.
    Clearly and prominently labeled so it is never mistaken for a live emergency.
    Never creates a fake alert in the database or dashboard.
    """
    time_ist = format_kolkata_time()
    forecast_date = format_forecast_date()

    message = (
        f"🧪 <b>[SIMULATED HIGH-RISK ALERT — DRILL ONLY]</b>\n"
        f"<b>Project:</b> Flood Early Warning • Team C (Drill Mode)\n"
        f"⚠️ <i>Threshold drill simulation: Catchment simulated in <b>HIGH</b> risk</i>\n\n"
        f"📍 <b>Catchment:</b> {zone_name}\n"
        f"🏛 <b>District:</b> {district}\n"
        f"🌊 <b>River Basin:</b> {river_basin}\n"
        f"📊 <b>Simulated Risk Index:</b> <b>{risk_score} / 100</b> (HIGH)\n\n"
        f"🌧 <b>Simulated Precipitation:</b> <b>{rainfall_24h_mm:.1f} mm</b> (Simulated Past 24h)\n"
        f"🌊 <b>Simulated River Discharge:</b> <b>{river_discharge_m3s:.2f} m³/s</b> (Simulated GloFAS forecast for {forecast_date})\n"
        f"📡 <b>Source Status:</b> SIMULATED_TEST\n"
        f"🕒 <b>Simulated At:</b> {time_ist}\n\n"
        f"<b>Key Risk Drivers (Simulated):</b>\n"
        f"• 24h Heavy Rainfall: {rainfall_24h_mm:.1f} mm (+32.0 pts)\n"
        f"• High River Discharge: {river_discharge_m3s:.2f} m³/s (+24.0 pts)\n"
        f"• Low-lying Alluvial Basin Surcharge (+15.0 pts)\n\n"
        f"⚡ <b>Recommended Action (Drill Protocol):</b>\n"
        f"Preposition flood-rescue personnel, inspect embankment sluices, and alert riverside gram panchayats.\n\n"
        f"ℹ️ <i>Notice: This is an authorized test simulation. No active emergency alert was added to the live dashboard. "
        f"Copernicus GloFAS 0.05° daily routing simulation.</i>"
    )
    return message


def send_simulated_high_risk_alert() -> Dict[str, Any]:
    """
    Dispatches a test-only simulated HIGH-risk alert message to Telegram.
    Safe for verification drills; does not create a fake live flood alert.
    """
    msg = build_simulated_high_risk_message()
    return send_telegram_message(msg)


