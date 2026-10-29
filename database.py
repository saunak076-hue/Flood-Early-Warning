"""
SQLite Database Module for Hack4Haldia'26 - Team C.
Handles persistence for zone configurations, meteorological/hydrological telemetry,
and generated alerts with robust deduplication and index optimization.
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger("database")

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "flood_monitor.db")


def get_connection() -> sqlite3.Connection:
    """Creates a connection to SQLite database with Row factory."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for concurrent reads and writes
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn


def init_db():
    """Initializes schema and tables if they do not exist."""
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                district TEXT NOT NULL,
                river_basin TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                elevation_m REAL,
                vulnerability TEXT,
                discharge_threshold_moderate REAL,
                discharge_threshold_severe REAL,
                rainfall_threshold_moderate REAL,
                rainfall_threshold_severe REAL,
                created_at TEXT NOT NULL
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                rainfall_current_mm REAL,
                rainfall_24h_mm REAL,
                forecast_rain_7d_mm REAL,
                river_discharge_m3s REAL,
                river_water_level_m REAL,
                risk_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                data_quality TEXT,
                freshness TEXT NOT NULL,
                data_source TEXT NOT NULL,
                FOREIGN KEY (zone_id) REFERENCES zones(id),
                UNIQUE(zone_id, timestamp)
            );
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_zone_time 
            ON readings(zone_id, timestamp DESC);
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT UNIQUE NOT NULL,
                zone_id TEXT NOT NULL,
                zone_name TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                risk_score REAL NOT NULL,
                recommended_action TEXT NOT NULL,
                source_status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (zone_id) REFERENCES zones(id)
            );
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_active 
            ON alerts(is_active, severity, timestamp DESC);
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_state (
                zone_id TEXT PRIMARY KEY,
                last_notified_severity TEXT NOT NULL,
                last_notified_score REAL NOT NULL,
                last_notified_at TEXT NOT NULL,
                last_alert_id TEXT,
                FOREIGN KEY (zone_id) REFERENCES zones(id)
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id TEXT,
                event_type TEXT NOT NULL,
                previous_severity TEXT,
                current_severity TEXT NOT NULL,
                risk_score REAL NOT NULL,
                message_text TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                telegram_message_id INTEGER,
                error_message TEXT
            );
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_log_time 
            ON notification_log(sent_at DESC);
        """)
    conn.close()
    logger.info("Database schema initialized successfully at %s", DB_PATH)


def seed_zones(zones_dict: Dict[str, Dict[str, Any]]):
    """Populates or updates zone configurations in the database."""
    conn = get_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    with conn:
        for zid, z in zones_dict.items():
            conn.execute("""
                INSERT INTO zones (
                    id, name, district, river_basin, lat, lon, elevation_m,
                    vulnerability, discharge_threshold_moderate, discharge_threshold_severe,
                    rainfall_threshold_moderate, rainfall_threshold_severe, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    district=excluded.district,
                    river_basin=excluded.river_basin,
                    lat=excluded.lat,
                    lon=excluded.lon,
                    elevation_m=excluded.elevation_m,
                    vulnerability=excluded.vulnerability,
                    discharge_threshold_moderate=excluded.discharge_threshold_moderate,
                    discharge_threshold_severe=excluded.discharge_threshold_severe,
                    rainfall_threshold_moderate=excluded.rainfall_threshold_moderate,
                    rainfall_threshold_severe=excluded.rainfall_threshold_severe;
            """, (
                zid, z["name"], z["district"], z["river_basin"], z["lat"], z["lon"],
                z.get("elevation_m", 10.0), z.get("vulnerability", "Standard"),
                z.get("discharge_threshold_moderate", 50.0), z.get("discharge_threshold_severe", 150.0),
                z.get("rainfall_threshold_moderate", 45.0), z.get("rainfall_threshold_severe", 90.0),
                now_iso
            ))
    conn.close()


def save_reading(reading: Dict[str, Any], risk_data: Dict[str, Any]):
    """Persists a new reading and its associated risk evaluation."""
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO readings (
                zone_id, timestamp, rainfall_current_mm, rainfall_24h_mm,
                forecast_rain_7d_mm, river_discharge_m3s, river_water_level_m,
                risk_score, risk_level, data_quality, freshness, data_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            reading["zone_id"],
            reading.get("timestamp", datetime.now(timezone.utc).isoformat()),
            reading.get("rainfall_current_mm"),
            reading.get("rainfall_24h_mm"),
            reading.get("forecast_rain_7d_mm"),
            reading.get("river_discharge_m3s"),
            reading.get("river_water_level_m"),
            risk_data["risk_score"],
            risk_data["risk_level"],
            risk_data.get("data_quality", "COMPLETE"),
            reading.get("freshness", "LIVE"),
            reading.get("source", "Open-Meteo")
        ))
    conn.close()


def get_latest_readings() -> List[Dict[str, Any]]:
    """Fetches the latest recorded reading for each monitored zone."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, z.name as zone_name, z.district, z.river_basin, z.lat, z.lon, z.vulnerability, z.elevation_m
        FROM readings r
        JOIN zones z ON r.zone_id = z.id
        WHERE r.id IN (
            SELECT MAX(id) FROM readings GROUP BY zone_id
        )
        ORDER BY r.risk_score DESC;
    """)
    rows = cursor.fetchall()
    readings = [dict(row) for row in rows]
    conn.close()
    return readings


def get_zone_history(zone_id: str, limit: int = 40) -> List[Dict[str, Any]]:
    """Retrieves chronological telemetry history for a specific zone."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, rainfall_24h_mm, rainfall_current_mm, forecast_rain_7d_mm,
               river_discharge_m3s, risk_score, risk_level, freshness, data_source
        FROM readings
        WHERE zone_id = ?
        ORDER BY timestamp ASC
        LIMIT ?;
    """, (zone_id, limit))
    rows = cursor.fetchall()
    history = [dict(row) for row in rows]
    conn.close()
    return history


def update_or_create_alert(alert: Dict[str, Any]):
    """
    Inserts or updates an alert.
    Prevents flood alert spamming by checking active alerts per zone and severity.
    """
    conn = get_connection()
    with conn:
        # Check if an identical active alert exists for this zone
        existing = conn.execute("""
            SELECT id FROM alerts 
            WHERE zone_id = ? AND severity = ? AND is_active = 1
        """, (alert["zone_id"], alert["severity"])).fetchone()

        if existing:
            # Update score and timestamp
            conn.execute("""
                UPDATE alerts SET
                    risk_score = ?,
                    reason = ?,
                    recommended_action = ?,
                    timestamp = ?,
                    source_status = ?
                WHERE id = ?;
            """, (
                alert["risk_score"], alert["reason"], alert["recommended_action"],
                alert.get("timestamp", datetime.now(timezone.utc).isoformat()),
                alert.get("source_status", "LIVE"),
                existing["id"]
            ))
        else:
            conn.execute("""
                INSERT INTO alerts (
                    alert_id, zone_id, zone_name, severity, title, reason,
                    risk_score, recommended_action, source_status, timestamp, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
            """, (
                alert["alert_id"], alert["zone_id"], alert["zone_name"],
                alert["severity"], alert["title"], alert["reason"],
                alert["risk_score"], alert["recommended_action"],
                alert.get("source_status", "LIVE"),
                alert.get("timestamp", datetime.now(timezone.utc).isoformat())
            ))
    conn.close()


def clear_inactive_alerts_for_zone(zone_id: str):
    """Deactivates active alerts for a zone when conditions de-escalate."""
    conn = get_connection()
    with conn:
        conn.execute("""
            UPDATE alerts SET is_active = 0 
            WHERE zone_id = ? AND is_active = 1;
        """, (zone_id,))
    conn.close()


def get_active_alerts() -> List[Dict[str, Any]]:
    """Retrieves all currently active flood alerts, ordered by severity and time."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM alerts 
        WHERE is_active = 1 
        ORDER BY 
            CASE severity 
                WHEN 'SEVERE' THEN 1 
                WHEN 'HIGH' THEN 2 
                WHEN 'MODERATE' THEN 3 
                ELSE 4 
            END ASC,
            risk_score DESC,
            timestamp DESC;
    """)
    rows = cursor.fetchall()
    alerts = [dict(row) for row in rows]
    conn.close()
    return alerts


def get_notification_state(zone_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the last notified alert state for a specific zone."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM notification_state WHERE zone_id = ?;",
        (zone_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_notification_state(
    zone_id: str,
    severity: str,
    risk_score: float,
    alert_id: Optional[str] = None
):
    """Updates or inserts the last notified severity and score for a zone."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO notification_state (
                zone_id, last_notified_severity, last_notified_score, last_notified_at, last_alert_id
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(zone_id) DO UPDATE SET
                last_notified_severity=excluded.last_notified_severity,
                last_notified_score=excluded.last_notified_score,
                last_notified_at=excluded.last_notified_at,
                last_alert_id=excluded.last_alert_id;
        """, (zone_id, severity, risk_score, now_iso, alert_id))
    conn.close()


def record_notification_log(
    zone_id: str,
    event_type: str,
    previous_severity: Optional[str],
    current_severity: str,
    risk_score: float,
    message_text: str,
    delivery_status: str,
    telegram_message_id: Optional[int] = None,
    error_message: Optional[str] = None
):
    """Appends an entry to the notification audit log."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO notification_log (
                zone_id, event_type, previous_severity, current_severity,
                risk_score, message_text, sent_at, delivery_status,
                telegram_message_id, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            zone_id, event_type, previous_severity, current_severity,
            risk_score, message_text, now_iso, delivery_status,
            telegram_message_id, error_message
        ))
    conn.close()


def get_notification_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves recent notification logs for audit and verification."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM notification_log ORDER BY id DESC LIMIT ?;",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


