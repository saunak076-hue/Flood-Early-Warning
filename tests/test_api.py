"""
Integration and API endpoint tests for Team C Flood Early Warning System.
Tests /health, /api/readings, /api/predict, /api/alerts, /api/zones, /api/summary, /api/history.
"""

import json
import unittest
from app import app
import database as db
from data_ingestion import WEST_BENGAL_ZONES


class TestFloodApi(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project"], "Team C: Flood Early Warning")
        self.assertEqual(data["stack"], "flask")
        self.assertIn("upstream_apis", data)
        self.assertIn("zones_monitored", data)

    def test_get_zones_endpoint(self):
        resp = self.client.get("/api/zones")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("count", data)
        self.assertIn("zones", data)
        self.assertGreaterEqual(data["count"], 5)
        # Check Haldia exists
        zone_ids = [z["id"] for z in data["zones"]]
        self.assertIn("haldia", zone_ids)

    def test_get_readings_endpoint(self):
        resp = self.client.get("/api/readings?demo=true")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("readings", data)
        readings = data["readings"]
        self.assertGreaterEqual(len(readings), 1)

        first = readings[0]
        self.assertIn("zone_id", first)
        self.assertIn("rainfall_24h_mm", first)
        self.assertIn("river_discharge_m3s", first)
        self.assertIn("risk_score", first)
        self.assertIn("risk_level", first)
        self.assertIn("freshness", first)

    def test_predict_endpoint_valid(self):
        payload = {
            "zone_id": "haldia",
            "rainfall_24h_mm": 65.0,
            "forecast_rain_7d_mm": 120.0,
            "river_discharge_m3s": 55.0
        }
        resp = self.client.post(
            "/api/predict",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        pred = data["prediction"]
        self.assertIn("risk_score", pred)
        self.assertIn("risk_level", pred)
        self.assertIn("contributing_factors", pred)
        self.assertIn("recommended_precautions", pred)
        self.assertGreaterEqual(pred["risk_score"], 30.0)

    def test_predict_endpoint_invalid_json(self):
        resp = self.client.post(
            "/api/predict",
            data="not-a-json",
            content_type="text/plain"
        )
        self.assertEqual(resp.status_code, 400)

    def test_predict_endpoint_negative_value(self):
        payload = {
            "zone_id": "haldia",
            "rainfall_24h_mm": -25.0
        }
        resp = self.client.post(
            "/api/predict",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("cannot be negative", data.get("message", ""))

    def test_predict_endpoint_unknown_zone(self):
        payload = {
            "zone_id": "nonexistent_zone_xyz"
        }
        resp = self.client.post(
            "/api/predict",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("Unknown zone", data.get("error", ""))

    def test_get_alerts_endpoint(self):
        resp = self.client.get("/api/alerts")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("alerts", data)
        self.assertIn("count", data)

    def test_get_summary_endpoint(self):
        resp = self.client.get("/api/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("total_monitored_zones", data)
        self.assertIn("highest_risk_score", data)
        self.assertIn("active_alerts_count", data)

    def test_get_history_endpoint(self):
        resp = self.client.get("/api/history?zone_id=haldia")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("history", data)
        self.assertEqual(data["zone_id"], "haldia")

    def test_get_history_invalid_zone(self):
        resp = self.client.get("/api/history?zone_id=invalid_zone")
        self.assertEqual(resp.status_code, 404)

    def test_404_handler(self):
        resp = self.client.get("/api/nonexistent_path")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()

