"""
Team C: Flood Early Warning System
Flask Backend Application
Hack4Haldia'26
"""

import os
import logging
import threading
import time
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Load environment configuration
load_dotenv()

from data_ingestion import (
    WEST_BENGAL_ZONES,
    fetch_zone_data,
    fetch_all_zones,
    check_upstream_health,
    _CACHE,
    DEMO_READINGS
)
from risk_engine import compute_flood_risk, sanitize_input
import database as db
import telegram_notifier

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("app")

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE, "static"),
    static_url_path="/static"
)
CORS(app)

# Global ingestion state
_INGEST_LOCK = threading.Lock()
_LAST_INGEST_TIME: Optional[str] = None
_SCHEDULER_STARTED = False
_SCHEDULER_LOCK_HANDLE = None


def try_acquire_scheduler_lease() -> bool:
    """
    Acquires an exclusive OS-level lease lock file to elect a single scheduler leader.
    Guarantees that only ONE worker runs the 10-minute monitoring loop in multi-worker
    production environments (e.g., Gunicorn with multiple worker processes).
    """
    global _SCHEDULER_LOCK_HANDLE
    if os.environ.get("RUN_BACKGROUND_SCHEDULER", "true").lower() in ("false", "0", "no"):
        logger.info("Background scheduler disabled via RUN_BACKGROUND_SCHEDULER=false.")
        return False

    lock_dir = os.path.join(BASE, "data")
    os.makedirs(lock_dir, exist_ok=True)
    lock_file_path = os.path.join(lock_dir, "scheduler.lock")

    try:
        handle = open(lock_file_path, "a+")
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        _SCHEDULER_LOCK_HANDLE = handle
        logger.info("Process PID %s elected as background scheduler leader.", os.getpid())
        return True
    except Exception:
        logger.info("Process PID %s: Scheduler lease held by another worker; skipping scheduler start.", os.getpid())
        return False


def run_ingestion_cycle(demo_mode: bool = False, force_refresh: bool = False):
    """
    Executes a complete data fetch, risk computation, and alert evaluation cycle.
    Thread-safe, deduplicated, and dispatches Telegram notifications on risk transitions.
    """
    global _LAST_INGEST_TIME
    if not _INGEST_LOCK.acquire(blocking=False):
        logger.info("Ingestion cycle already in progress, skipping concurrent run.")
        return

    try:
        logger.info(f"Starting ingestion cycle (demo_mode={demo_mode}, force_refresh={force_refresh})...")
        readings = fetch_all_zones(force_refresh=force_refresh, demo_mode=demo_mode)
        now_iso = datetime.now(timezone.utc).isoformat()
        SEVERITY_RANKS = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3}

        for r in readings:
            zid = r["zone_id"]
            # Evaluate flood risk
            risk_eval = compute_flood_risk(
                zone_id=zid,
                rainfall_24h_mm=r.get("rainfall_24h_mm"),
                forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                river_discharge_m3s=r.get("river_discharge_m3s")
            )

            # Persist reading and risk calculation
            try:
                db.save_reading(r, risk_eval)
            except Exception as e:
                logger.error(f"Failed to persist reading for {zid}: {e}")

            # State transition and notification evaluation
            level = risk_eval["risk_level"]
            score = risk_eval["risk_score"]
            zname = r.get("zone_name", zid)
            alert_id = f"alert-{zid}-{level.lower()}"
            curr_rank = SEVERITY_RANKS.get(level, 0)

            # Check persistent notification state from database
            notif_state = db.get_notification_state(zid)
            prev_level = notif_state.get("last_notified_severity") if notif_state else None
            prev_rank = SEVERITY_RANKS.get(prev_level, 0) if prev_level else 0

            # Determine if a state change event occurred
            event_type = None
            if curr_rank >= 2:  # HIGH or SEVERE
                if prev_level is None or prev_rank < 2:
                    event_type = "NEW_ALERT"
                elif curr_rank > prev_rank:
                    event_type = "ESCALATION"
                elif curr_rank == prev_rank:
                    # Same severity category: suppress duplicate Telegram message
                    event_type = None
            elif curr_rank < 2:  # LOW or MODERATE
                if prev_level in ("HIGH", "SEVERE"):
                    event_type = "RECOVERY"

            # 1. Update/create active alert in database for dashboard
            if level in ("HIGH", "SEVERE"):
                top_factors = [
                    f"{f['factor']}: {f['value']}"
                    for f in risk_eval.get("contributing_factors", [])
                    if f.get("points", 0) >= 10.0
                ]
                reason_str = " | ".join(top_factors) if top_factors else f"Compound flood risk index reached {score}/100"

                alert_payload = {
                    "alert_id": alert_id,
                    "zone_id": zid,
                    "zone_name": zname,
                    "severity": level,
                    "title": f"Flood Warning - {zname} ({level})",
                    "reason": reason_str,
                    "risk_score": score,
                    "recommended_action": risk_eval["recommended_precautions"][0] if risk_eval["recommended_precautions"] else "Monitor local flood bulletins.",
                    "source_status": r.get("freshness", "LIVE"),
                    "timestamp": now_iso
                }
                db.update_or_create_alert(alert_payload)
            elif event_type == "RECOVERY" or level == "LOW":
                db.clear_inactive_alerts_for_zone(zid)

            # 2. Dispatch Telegram notification if state changed (Requirement 8, 9, 11, 12)
            if event_type is not None and not demo_mode:
                try:
                    msg_text = telegram_notifier.build_alert_message(
                        zone_data=r,
                        risk_data=risk_eval,
                        event_type=event_type,
                        previous_level=prev_level
                    )
                    delivery_res = telegram_notifier.send_telegram_message(msg_text)

                    db.record_notification_log(
                        zone_id=zid,
                        event_type=event_type,
                        previous_severity=prev_level,
                        current_severity=level,
                        risk_score=score,
                        message_text=msg_text,
                        delivery_status=delivery_res.get("status", "UNKNOWN"),
                        telegram_message_id=delivery_res.get("message_id"),
                        error_message=delivery_res.get("error")
                    )

                    db.update_notification_state(
                        zone_id=zid,
                        severity=level,
                        risk_score=score,
                        alert_id=alert_id if level in ("HIGH", "SEVERE") else None
                    )
                    logger.info(
                        "Telegram notification (%s) processed for %s -> %s",
                        event_type, zid, delivery_res.get("status")
                    )
                except Exception as te:
                    logger.error("Telegram notification dispatch error for %s: %s", zid, te)

        _LAST_INGEST_TIME = now_iso
        logger.info(f"Ingestion cycle completed successfully for {len(readings)} zones.")
    except Exception as e:
        logger.exception(f"Error during ingestion cycle: {e}")
    finally:
        _INGEST_LOCK.release()


def start_background_scheduler():
    """
    Initializes a background thread or APScheduler for periodic ingestion (10m interval).
    Protected by OS-level lease lock to prevent duplicate runs across multi-worker deployments.
    """
    global _SCHEDULER_STARTED
    if _SCHEDULER_STARTED:
        return

    # Check if this worker holds the exclusive lease
    if not try_acquire_scheduler_lease():
        return

    _SCHEDULER_STARTED = True

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(daemon=True)
        # Background monitoring every 10 minutes (Requirement 6)
        scheduler.add_job(
            run_ingestion_cycle,
            "interval",
            minutes=10,
            id="periodic_flood_ingest",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        scheduler.start()
        logger.info("APScheduler background ingestion service started (10m interval, single leader).")
    except Exception as e:
        logger.warning(f"APScheduler init failed; falling back to threading: {e}")
        def background_loop():
            while True:
                time.sleep(600)
                run_ingestion_cycle()
        t = threading.Thread(target=background_loop, daemon=True)
        t.start()


# Initialize database and seed zones
try:
    db.init_db()
    db.seed_zones(WEST_BENGAL_ZONES)
    # Run initial sync synchronously on startup so database is fully primed
    try:
        run_ingestion_cycle(force_refresh=False)
    except Exception as ie:
        logger.warning(f"Initial synchronous sync completed with warning: {ie}")
    start_background_scheduler()
except Exception as e:
    logger.error(f"Startup initialization error: {e}")


# ==========================================
# REST API Endpoints
# ==========================================

@app.route("/")
def index():
    """Serve the primary Flood Monitoring Dashboard."""
    return send_from_directory(BASE, "index.html")


@app.route("/health", methods=["GET"])
def health():
    """Application health, upstream connectivity, and Telegram alerting status."""
    upstream = check_upstream_health()
    active_alerts = len(db.get_active_alerts())
    bot_token, chat_id = telegram_notifier.get_telegram_credentials()
    return jsonify({
        "status": "ok",
        "project": "Team C: Flood Early Warning",
        "stack": "flask",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zones_monitored": len(WEST_BENGAL_ZONES),
        "active_alerts_count": active_alerts,
        "last_ingestion_utc": _LAST_INGEST_TIME,
        "upstream_apis": upstream,
        "telegram_alerting": {
            "configured": bool(bot_token and chat_id),
            "bot_token_configured": bool(bot_token),
            "chat_id_configured": bool(chat_id)
        },
        "environment": os.environ.get("FLASK_ENV", "production")
    })


@app.route("/api/zones", methods=["GET"])
def get_zones():
    """Return all configured monitoring zones and their hydrological metadata."""
    return jsonify({
        "count": len(WEST_BENGAL_ZONES),
        "zones": list(WEST_BENGAL_ZONES.values())
    })


@app.route("/api/readings", methods=["GET"])
def get_readings():
    """
    Return latest telemetry readings for all configured zones.
    Includes rainfall, river discharge in m³/s, data provenance, and freshness.
    """
    demo_param = request.args.get("demo", "").lower() in ("true", "1", "yes")
    force_refresh = request.args.get("refresh", "").lower() in ("true", "1", "yes")

    # If demo mode is explicitly requested, return isolated baseline demo data
    if demo_param:
        demo_readings = fetch_all_zones(demo_mode=True)
        enriched = []
        for r in demo_readings:
            risk = compute_flood_risk(
                zone_id=r["zone_id"],
                rainfall_24h_mm=r.get("rainfall_24h_mm"),
                forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                river_discharge_m3s=r.get("river_discharge_m3s")
            )
            item = dict(r)
            item["source"] = "Pre-computed Baseline Scenario (Demo Mode)"
            item["data_source"] = item["source"]
            item["freshness"] = "DEMO"
            item["risk_score"] = risk["risk_score"]
            item["risk_level"] = risk["risk_level"]
            item["risk_color"] = risk["color"]
            item["data_quality"] = risk["data_quality"]
            item["contributing_factors"] = risk["contributing_factors"]
            item["recommended_precautions"] = risk["recommended_precautions"]
            item["breakdown"] = risk["breakdown"]
            item["units"] = {
                "rainfall": "mm",
                "river_discharge": "m³/s",
                "river_water_level": "m (local gauge only)"
            }
            enriched.append(item)
        return jsonify({
            "count": len(enriched),
            "source": "Demo Scenario Telemetry Feed",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "readings": enriched
        })

    # If force refresh requested
    if force_refresh:
        run_ingestion_cycle(demo_mode=False, force_refresh=True)

    latest_db = db.get_latest_readings()

    # If DB is still empty (e.g. startup thread running), fetch in-memory
    if not latest_db:
        readings = fetch_all_zones(demo_mode=demo_param)
        enriched = []
        for r in readings:
            risk = compute_flood_risk(
                zone_id=r["zone_id"],
                rainfall_24h_mm=r.get("rainfall_24h_mm"),
                forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                river_discharge_m3s=r.get("river_discharge_m3s")
            )
            item = dict(r)
            item["source"] = r.get("source", "Open-Meteo Telemetry Feed")
            item["data_source"] = item["source"]
            item["risk_score"] = risk["risk_score"]
            item["risk_level"] = risk["risk_level"]
            item["risk_color"] = risk["color"]
            item["data_quality"] = risk["data_quality"]
            item["contributing_factors"] = risk["contributing_factors"]
            item["recommended_precautions"] = risk["recommended_precautions"]
            enriched.append(item)
        return jsonify({
            "count": len(enriched),
            "source": "In-Memory Telemetry Feed",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "readings": enriched
        })

    # Enrich latest DB records with risk details
    results = []
    for row in latest_db:
        zid = row["zone_id"]
        risk = compute_flood_risk(
            zone_id=zid,
            rainfall_24h_mm=row["rainfall_24h_mm"],
            forecast_rain_7d_mm=row["forecast_rain_7d_mm"],
            river_discharge_m3s=row["river_discharge_m3s"]
        )
        row_dict = dict(row)
        row_dict["source"] = row_dict.get("data_source", "Open-Meteo Telemetry Feed")
        row_dict["risk_score"] = risk["risk_score"]
        row_dict["risk_level"] = risk["risk_level"]
        row_dict["risk_color"] = risk["color"]
        row_dict["data_quality"] = risk["data_quality"]
        row_dict["contributing_factors"] = risk["contributing_factors"]
        row_dict["recommended_precautions"] = risk["recommended_precautions"]
        row_dict["breakdown"] = risk["breakdown"]
        
        # Attach 7-day GloFAS discharge forecast array
        cache_entry = _CACHE.get(zid, {}).get("data", {})
        row_dict["discharge_forecast_7d_m3s"] = cache_entry.get(
            "discharge_forecast_7d_m3s",
            DEMO_READINGS.get(zid, {}).get("discharge_forecast_7d_m3s", [])
        )
        row_dict["units"] = {
            "rainfall": "mm",
            "river_discharge": "m³/s",
            "river_water_level": "m (local gauge only)"
        }
        results.append(row_dict)

    return jsonify({
        "count": len(results),
        "source": "SQLite Persisted Telemetry & Risk Engine",
        "last_updated": _LAST_INGEST_TIME or datetime.now(timezone.utc).isoformat(),
        "readings": results
    })


@app.route("/api/predict", methods=["POST"])
def predict():
    """
    Accepts validated feature inputs and/or supported zone identifier.
    Returns calculated risk score, category, contributing factors, and precautions.
    """
    if not request.is_json:
        return jsonify({
            "error": "Invalid request body",
            "message": "Content-Type must be application/json"
        }), 400

    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid request format",
            "message": "JSON body must be an object containing feature inputs."
        }), 400

    zone_id = data.get("zone_id")
    if zone_id and zone_id not in WEST_BENGAL_ZONES:
        return jsonify({
            "error": "Unknown zone",
            "message": f"Zone '{zone_id}' not found. Supported zones: {list(WEST_BENGAL_ZONES.keys())}"
        }), 400

    raw_rain = data.get("rainfall_24h_mm")
    raw_forecast = data.get("forecast_rain_7d_mm")
    raw_discharge = data.get("river_discharge_m3s")

    # Validation: check for negative or non-numeric inputs
    for name, val in [("rainfall_24h_mm", raw_rain), ("forecast_rain_7d_mm", raw_forecast), ("river_discharge_m3s", raw_discharge)]:
        if val is not None:
            try:
                num = float(val)
                if num < 0:
                    return jsonify({
                        "error": "Invalid feature value",
                        "field": name,
                        "message": f"{name} cannot be negative ({num}). Physically impossible."
                    }), 400
                if num > 10000:
                    return jsonify({
                        "error": "Out-of-bounds feature value",
                        "field": name,
                        "message": f"{name} exceeds reasonable physical limits (10000)."
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "error": "Type error",
                    "field": name,
                    "message": f"{name} must be a valid float or integer, got: {val}"
                }), 400

    # If zone_id provided and features missing, retrieve current telemetry as defaults
    if zone_id and (raw_rain is None and raw_discharge is None):
        try:
            curr = fetch_zone_data(zone_id)
            raw_rain = curr.get("rainfall_24h_mm")
            raw_forecast = curr.get("forecast_rain_7d_mm")
            raw_discharge = curr.get("river_discharge_m3s")
        except Exception as e:
            logger.warning(f"Could not load zone telemetry for prediction: {e}")

    # Compute risk
    risk_result = compute_flood_risk(
        zone_id=zone_id or "generic",
        rainfall_24h_mm=raw_rain,
        forecast_rain_7d_mm=raw_forecast,
        river_discharge_m3s=raw_discharge
    )

    return jsonify({
        "success": True,
        "zone_id": zone_id or "generic",
        "inputs": {
            "rainfall_24h_mm": raw_rain,
            "forecast_rain_7d_mm": raw_forecast,
            "river_discharge_m3s": raw_discharge
        },
        "prediction": risk_result
    })


@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    """
    Returns active alerts generated by documented thresholds.
    Deduplicated, sorted by severity and timestamp.
    """
    demo_param = request.args.get("demo", "").lower() in ("true", "1", "yes")
    if demo_param:
        demo_readings = fetch_all_zones(demo_mode=True)
        demo_alerts = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for r in demo_readings:
            risk = compute_flood_risk(
                zone_id=r["zone_id"],
                rainfall_24h_mm=r.get("rainfall_24h_mm"),
                forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                river_discharge_m3s=r.get("river_discharge_m3s")
            )
            level = risk["risk_level"]
            if level in ("HIGH", "SEVERE"):
                zid = r["zone_id"]
                zname = r.get("zone_name", zid)
                top_factors = [
                    f"{f['factor']}: {f['value']}"
                    for f in risk.get("contributing_factors", [])
                    if f.get("points", 0) >= 10.0
                ]
                reason_str = " | ".join(top_factors) if top_factors else f"Compound flood risk index reached {risk['risk_score']}/100"
                demo_alerts.append({
                    "alert_id": f"demo-alert-{zid}-{level.lower()}",
                    "zone_id": zid,
                    "zone_name": zname,
                    "severity": level,
                    "title": f"Flood Warning - {zname} ({level})",
                    "reason": reason_str,
                    "risk_score": risk["risk_score"],
                    "recommended_action": risk["recommended_precautions"][0] if risk["recommended_precautions"] else "Monitor local flood bulletins.",
                    "source_status": "DEMO",
                    "timestamp": now_iso
                })
        # Sort by severity and risk_score
        sev_order = {"SEVERE": 1, "HIGH": 2, "MODERATE": 3, "LOW": 4}
        demo_alerts.sort(key=lambda a: (sev_order.get(a["severity"], 5), -a["risk_score"]))
        return jsonify({
            "count": len(demo_alerts),
            "last_checked": now_iso,
            "alerts": demo_alerts,
            "disclaimer": "These are simulated algorithmic alerts for demo evaluation; not official emergency warnings."
        })

    alerts = db.get_active_alerts()
    return jsonify({
        "count": len(alerts),
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "alerts": alerts,
        "disclaimer": "These are algorithmic heuristic alerts for emergency planning, not official civil defense warnings."
    })


@app.route("/api/alerts/test-telegram", methods=["POST"])
def trigger_telegram_test():
    """
    Protected action to verify Telegram notification delivery without creating false alerts.
    Requires ADMIN_API_KEY authorization header or key parameter.
    """
    admin_key = os.environ.get("ADMIN_API_KEY")
    req_key = (
        request.headers.get("X-Admin-Key")
        or request.args.get("key")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    )

    is_loopback = request.remote_addr in ("127.0.0.1", "::1", "localhost")

    # If ADMIN_API_KEY is configured, enforce matching key
    if admin_key:
        if req_key != admin_key:
            return jsonify({
                "success": False,
                "error": "Unauthorized",
                "message": "Valid X-Admin-Key or Authorization required to trigger Telegram test notifications."
            }), 401
    else:
        # If no key configured, permit only from local loopback
        if not is_loopback:
            return jsonify({
                "success": False,
                "error": "Forbidden",
                "message": "ADMIN_API_KEY not set; external test execution is disabled."
            }), 403

    try:
        delivery_res = telegram_notifier.send_test_notification()

        db.record_notification_log(
            zone_id="system-test",
            event_type="TEST",
            previous_severity=None,
            current_severity="TEST",
            risk_score=0.0,
            message_text="[INTEGRATION TEST] Verification test message",
            delivery_status=delivery_res.get("status", "UNKNOWN"),
            telegram_message_id=delivery_res.get("message_id"),
            error_message=delivery_res.get("error")
        )

        status_code = 200 if delivery_res.get("success") else 502
        return jsonify({
            "success": delivery_res.get("success", False),
            "status": delivery_res.get("status"),
            "delivery": delivery_res,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "Verification test dispatched to configured Telegram chat. No active alerts were created."
        }), status_code
    except Exception as e:
        logger.error(f"Error executing test Telegram notification: {e}")
        return jsonify({
            "success": False,
            "error": "Internal Error",
            "message": str(e)
        }), 500


@app.route("/api/alerts/history", methods=["GET"])
def get_alerts_history():
    """
    Returns recent notification audit logs for verification.
    """
    limit = int(request.args.get("limit", 20))
    limit = max(1, min(100, limit))
    logs = db.get_notification_logs(limit=limit)
    return jsonify({
        "count": len(logs),
        "notifications": logs
    })


@app.route("/api/history", methods=["GET"])
def get_history():
    """Return historical readings for a specified zone."""
    zone_id = request.args.get("zone_id", "haldia")
    limit = int(request.args.get("limit", 40))
    limit = max(1, min(limit, 100))

    if zone_id not in WEST_BENGAL_ZONES:
        return jsonify({
            "error": "Zone not found",
            "message": f"Valid zones: {list(WEST_BENGAL_ZONES.keys())}"
        }), 404

    history = db.get_zone_history(zone_id, limit=limit)
    return jsonify({
        "zone_id": zone_id,
        "count": len(history),
        "history": history
    })


@app.route("/api/summary", methods=["GET"])
def get_summary():
    """High-level KPI metrics summary for dashboard cards."""
    demo_param = request.args.get("demo", "").lower() in ("true", "1", "yes")

    if demo_param:
        demo_readings = fetch_all_zones(demo_mode=True)
        readings = []
        for r in demo_readings:
            risk = compute_flood_risk(
                zone_id=r["zone_id"],
                rainfall_24h_mm=r.get("rainfall_24h_mm"),
                forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                river_discharge_m3s=r.get("river_discharge_m3s")
            )
            item = dict(r)
            item["risk_score"] = risk["risk_score"]
            item["risk_level"] = risk["risk_level"]
            readings.append(item)
        alerts_count = sum(1 for r in readings if r["risk_level"] in ("HIGH", "SEVERE"))
    else:
        readings = db.get_latest_readings()
        alerts = db.get_active_alerts()
        # Fallback to in-memory readings if DB is still empty
        if not readings:
            readings = fetch_all_zones(demo_mode=False)
            for r in readings:
                risk = compute_flood_risk(
                    zone_id=r["zone_id"],
                    rainfall_24h_mm=r.get("rainfall_24h_mm"),
                    forecast_rain_7d_mm=r.get("forecast_rain_7d_mm"),
                    river_discharge_m3s=r.get("river_discharge_m3s")
                )
                r["risk_score"] = risk["risk_score"]
                r["risk_level"] = risk["risk_level"]
        alerts_count = len(alerts) if alerts else sum(1 for r in readings if r.get("risk_level") in ("HIGH", "SEVERE"))

    highest_risk_score = 0.0
    highest_risk_zone = "Haldia Industrial & Port Zone"
    highest_risk_level = "LOW"
    max_rainfall = 0.0
    severe_count = 0
    high_count = 0

    if readings:
        highest_risk_zone = readings[0].get("zone_name", readings[0].get("zone_id", "Haldia Industrial & Port Zone"))
        highest_risk_level = readings[0].get("risk_level", "LOW")
        highest_risk_score = float(readings[0].get("risk_score") or 0.0)

    for r in readings:
        score = float(r.get("risk_score", 0.0))
        if score > highest_risk_score:
            highest_risk_score = score
            highest_risk_zone = r.get("zone_name", r.get("zone_id", "Unknown"))
            highest_risk_level = r.get("risk_level", "LOW")

        rain = float(r.get("rainfall_24h_mm") or 0.0)
        if rain > max_rainfall:
            max_rainfall = rain

        level = r.get("risk_level", "LOW")
        if level == "SEVERE":
            severe_count += 1
        elif level == "HIGH":
            high_count += 1

    return jsonify({
        "total_monitored_zones": len(WEST_BENGAL_ZONES),
        "highest_risk_score": round(highest_risk_score, 1),
        "highest_risk_zone": highest_risk_zone,
        "highest_risk_level": highest_risk_level,
        "active_alerts_count": alerts_count,
        "severe_zones_count": severe_count,
        "high_zones_count": high_count,
        "max_24h_rainfall_mm": round(max_rainfall, 2),
        "last_updated": _LAST_INGEST_TIME or datetime.now(timezone.utc).isoformat()
    })


@app.route("/api/refresh", methods=["POST"])
def trigger_refresh():
    """Triggers an on-demand data refresh cycle."""
    demo_mode = request.args.get("demo", "").lower() in ("true", "1")
    force = request.args.get("force", "").lower() in ("true", "1")
    threading.Thread(target=lambda: run_ingestion_cycle(demo_mode=demo_mode, force_refresh=force), daemon=True).start()
    return jsonify({
        "status": "refresh_initiated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "Data ingestion and risk re-evaluation started in background."
    })


# Global error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify(error="Not Found", message="Requested endpoint does not exist."), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal Server Error: {e}")
    return jsonify(error="Internal Server Error", message="An unexpected error occurred."), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    logger.info(f"Starting Team C Flood Early Warning Server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
