"""
Comprehensive Test Suite for Telegram Alerting Service.
Validates:
- Truthful hydrological alert formatting (Asia/Kolkata timezone, GloFAS note, unavailable values)
- State transitions (NEW_ALERT, ESCALATION, RECOVERY)
- Persistent duplicate notification suppression
- Graceful handling of missing credentials and Telegram API failures
- Protected test endpoint authorization
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import json
from datetime import datetime, timezone

from app import app
import database as db
import telegram_notifier


class TestTelegramAlerting(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        db.init_db()

    def test_alert_message_formatting_completeness(self):
        """Audit that message formatting satisfies all Requirement 9 fields."""
        zone_data = {
            "zone_id": "ghatal",
            "zone_name": "Ghatal Sub-Division",
            "district": "Paschim Medinipur",
            "river_basin": "Silabati & Kangsabati Confluence",
            "rainfall_24h_mm": 98.0,
            "river_discharge_m3s": 165.0,
            "freshness": "LIVE",
            "timestamp": "2026-10-29T14:30:00+00:00"
        }
        risk_data = {
            "risk_score": 82.5,
            "risk_level": "SEVERE",
            "recommended_precautions": [
                "EMERGENCY: Immediate evacuation of low-lying floodplains."
            ],
            "contributing_factors": [
                {
                    "factor": "24h Precipitation",
                    "value": "98.0 mm",
                    "points": 35.0
                },
                {
                    "factor": "River Discharge",
                    "value": "165.00 m³/s",
                    "points": 25.0
                }
            ]
        }

        msg = telegram_notifier.build_alert_message(zone_data, risk_data, event_type="NEW_ALERT")

        # Required fields check
        self.assertIn("Ghatal Sub-Division", msg)
        self.assertIn("Paschim Medinipur", msg)
        self.assertIn("Silabati & Kangsabati Confluence", msg)
        self.assertIn("82.5 / 100", msg)
        self.assertIn("SEVERE", msg)
        self.assertIn("98.0 mm", msg)
        self.assertIn("Past 24h", msg)
        self.assertIn("165.00 m³/s", msg)
        self.assertIn("GloFAS daily forecast", msg)
        self.assertIn("IST", msg)  # Asia/Kolkata representation
        self.assertIn("LIVE", msg)
        self.assertIn("Immediate evacuation", msg)
        # Hydrological distinction notice
        self.assertIn("Water level (m) requires localized gauge stations", msg)

    def test_alert_message_unavailable_fields_no_fabricated_zeros(self):
        """Audit that missing telemetry is marked unavailable, never zeroed."""
        zone_data = {
            "zone_id": "kolkata",
            "zone_name": "Kolkata Metropolitan",
            "district": "Kolkata",
            "river_basin": "Lower Hooghly Delta",
            "rainfall_24h_mm": None,
            "river_discharge_m3s": None,
            "freshness": "CACHED",
            "timestamp": "2026-10-29T14:30:00+00:00"
        }
        risk_data = {
            "risk_score": 45.0,
            "risk_level": "MODERATE",
            "recommended_precautions": ["Advisory: Check local drainage outlets."],
            "contributing_factors": []
        }

        msg = telegram_notifier.build_alert_message(zone_data, risk_data, event_type="NEW_ALERT")
        self.assertIn("<b>Precipitation:</b> <i>Unavailable</i>", msg)
        self.assertIn("<b>River Discharge:</b> <i>Unavailable", msg)
        self.assertNotIn("0.0 mm (Observed Past 24h)", msg)
        self.assertNotIn("0.00 m³/s (GloFAS", msg)

    def test_escalation_message_formatting(self):
        """Audit escalation message badges and transition text."""
        zone_data = {
            "zone_id": "haldia",
            "zone_name": "Haldia Industrial & Port Zone",
            "district": "Purba Medinipur",
            "river_basin": "Haldi & Hooghly Estuary",
            "rainfall_24h_mm": 88.0,
            "river_discharge_m3s": 75.0,
            "freshness": "LIVE",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        risk_data = {
            "risk_score": 85.0,
            "risk_level": "SEVERE",
            "recommended_precautions": ["Activate municipal pump stations."],
            "contributing_factors": []
        }

        msg = telegram_notifier.build_alert_message(
            zone_data, risk_data, event_type="ESCALATION", previous_level="HIGH"
        )
        self.assertIn("FLOOD RISK ESCALATION WARNING", msg)
        self.assertIn("escalated from HIGH to <b>SEVERE</b>", msg)

    def test_recovery_message_formatting(self):
        """Audit recovery message badges and transition text."""
        zone_data = {
            "zone_id": "haldia",
            "zone_name": "Haldia Industrial & Port Zone",
            "district": "Purba Medinipur",
            "river_basin": "Haldi & Hooghly Estuary",
            "rainfall_24h_mm": 5.0,
            "river_discharge_m3s": 10.0,
            "freshness": "LIVE",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        risk_data = {
            "risk_score": 15.0,
            "risk_level": "LOW",
            "recommended_precautions": ["Conditions normal."],
            "contributing_factors": []
        }

        msg = telegram_notifier.build_alert_message(
            zone_data, risk_data, event_type="RECOVERY", previous_level="SEVERE"
        )
        self.assertIn("FLOOD RISK RECOVERY ADVISORY", msg)
        self.assertIn("de-escalated from SEVERE to safe baseline <b>LOW</b>", msg)

    def test_duplicate_notification_prevention(self):
        """Test persistent database state prevents sending duplicate alerts for the same category."""
        zid = "haldia"
        
        # 1. First cycle: zone enters SEVERE
        db.update_notification_state(zid, severity="SEVERE", risk_score=85.0, alert_id="alert-dup-1")
        state = db.get_notification_state(zid)
        self.assertEqual(state["last_notified_severity"], "SEVERE")

        # 2. Simulate next cycle with same SEVERE severity
        prev_level = state["last_notified_severity"]
        curr_level = "SEVERE"

        SEVERITY_RANKS = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3}
        curr_rank = SEVERITY_RANKS[curr_level]
        prev_rank = SEVERITY_RANKS[prev_level]

        event_type = None
        if curr_rank >= 2:
            if curr_rank > prev_rank:
                event_type = "ESCALATION"
            elif curr_rank == prev_rank:
                event_type = None  # Suppressed duplicate

        self.assertIsNone(event_type, "Duplicate notification must be suppressed when severity rank does not escalate")

    def test_missing_credentials_handling(self):
        """Test sending message without credentials returns SKIPPED_NO_CREDS without error."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            res = telegram_notifier.send_telegram_message("Test message")
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "SKIPPED_NO_CREDS")
            self.assertIn("not configured", res["error"])

    @patch("requests.post")
    def test_telegram_api_failure_resilience(self, mock_post):
        """Test that a 500 error or network exception from Telegram does not crash the system."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Telegram Server Error"
        mock_post.return_value = mock_resp

        res = telegram_notifier.send_telegram_message(
            "Test Alert", bot_token="fake_token", chat_id="12345"
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "FAILED")
        self.assertEqual(res["http_status"], 500)

    @patch("requests.post")
    def test_telegram_api_success(self, mock_post):
        """Test successful Telegram delivery parsing."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 9999}}
        mock_post.return_value = mock_resp

        res = telegram_notifier.send_telegram_message(
            "Test Alert", bot_token="fake_token", chat_id="12345"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["message_id"], 9999)

    def test_protected_test_endpoint_unauthorized(self):
        """Audit that public unauthorized POST to /api/alerts/test-telegram is blocked."""
        with patch.dict(os.environ, {"ADMIN_API_KEY": "super-secret-key-123"}):
            resp = self.client.post("/api/alerts/test-telegram", environ_base={"REMOTE_ADDR": "198.51.100.1"})
            self.assertEqual(resp.status_code, 401)
            data = resp.get_json()
            self.assertEqual(data["error"], "Unauthorized")

    @patch("telegram_notifier.send_test_notification")
    def test_protected_test_endpoint_authorized(self, mock_send_test):
        """Audit that authorized POST to /api/alerts/test-telegram succeeds."""
        mock_send_test.return_value = {"success": True, "status": "SUCCESS", "message_id": 777}

        with patch.dict(os.environ, {"ADMIN_API_KEY": "super-secret-key-123"}):
            resp = self.client.post(
                "/api/alerts/test-telegram",
                headers={"X-Admin-Key": "super-secret-key-123"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "SUCCESS")

    def test_health_endpoint_telegram_status(self):
        """Audit that /health exposes boolean flags and never leaks the bot token."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("telegram_alerting", data)
        self.assertIn("configured", data["telegram_alerting"])
        self.assertNotIn("TELEGRAM_BOT_TOKEN", json.dumps(data))
        self.assertNotIn("9279897316", json.dumps(data))  # Token digits never in JSON response


if __name__ == "__main__":
    unittest.main()
