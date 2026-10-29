import unittest
import requests

BASE_URL = "http://127.0.0.1:5000"


def is_server_running():
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


@unittest.skipUnless(is_server_running(), "Live Flask server not active at http://127.0.0.1:5000")
class TestLiveServerEndpoints(unittest.TestCase):

    def test_health_live(self):
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["zones_monitored"], 8)
        self.assertIn("weather_api", data["upstream_apis"])
        self.assertIn("flood_api", data["upstream_apis"])

    def test_readings_live(self):
        r = requests.get(f"{BASE_URL}/api/readings", timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["count"], 8)
        self.assertEqual(len(data["readings"]), 8)
        first = data["readings"][0]
        self.assertIn("zone_id", first)
        self.assertIn("risk_score", first)
        self.assertIn("risk_level", first)
        self.assertIn("freshness", first)

    def test_predict_valid_inputs(self):
        payload = {
            "zone_id": "ghatal",
            "rainfall_24h_mm": 95.0,
            "forecast_rain_7d_mm": 180.0,
            "river_discharge_m3s": 240.0
        }
        r = requests.post(f"{BASE_URL}/api/predict", json=payload, timeout=5)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        pred = data["prediction"]
        self.assertGreaterEqual(pred["risk_score"], 80.0)
        self.assertEqual(pred["risk_level"], "SEVERE")
        self.assertTrue(len(pred["contributing_factors"]) > 0)
        self.assertTrue(len(pred["recommended_precautions"]) > 0)

    def test_predict_invalid_negative_rain(self):
        payload = {"zone_id": "haldia", "rainfall_24h_mm": -15.0}
        r = requests.post(f"{BASE_URL}/api/predict", json=payload, timeout=5)
        self.assertEqual(r.status_code, 400)
        data = r.json()
        self.assertIn("cannot be negative", data["message"])

    def test_predict_invalid_unknown_zone(self):
        payload = {"zone_id": "unknown_district_xyz", "rainfall_24h_mm": 50.0}
        r = requests.post(f"{BASE_URL}/api/predict", json=payload, timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_predict_malformed_json(self):
        r = requests.post(f"{BASE_URL}/api/predict", data="this-is-not-json", headers={"Content-Type": "text/plain"}, timeout=5)
        self.assertEqual(r.status_code, 400)

    def test_alerts_live_and_demo(self):
        # Live
        r_live = requests.get(f"{BASE_URL}/api/alerts", timeout=5)
        self.assertEqual(r_live.status_code, 200)
        # Demo
        r_demo = requests.get(f"{BASE_URL}/api/alerts?demo=true", timeout=5)
        self.assertEqual(r_demo.status_code, 200)
        data_demo = r_demo.json()
        self.assertGreaterEqual(data_demo["count"], 1)
        first_alert = data_demo["alerts"][0]
        self.assertIn(first_alert["severity"], ["HIGH", "SEVERE"])
        self.assertEqual(first_alert["source_status"], "DEMO")

    def test_refresh_endpoint(self):
        r = requests.post(f"{BASE_URL}/api/refresh", timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "refresh_initiated")


if __name__ == "__main__":
    unittest.main()
