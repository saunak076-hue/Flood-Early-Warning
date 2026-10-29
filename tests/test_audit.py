"""
Catchment & Risk Calculation Audit Script
Validates all 8 West Bengal catchments, fields, units, boundary thresholds,
and consistency across the risk engine and telemetry mappings.
"""

import unittest
import requests
from app import app
from data_ingestion import WEST_BENGAL_ZONES
from risk_engine import compute_flood_risk, get_risk_category


class TestCatchmentAndRiskAudit(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_all_eight_catchments_presence_and_coordinates(self):
        """Audit all 8 catchments exist with valid West Bengal coordinates."""
        self.assertEqual(len(WEST_BENGAL_ZONES), 8)
        
        expected_zones = {
            "haldia": (22.0667, 88.0698, "Purba Medinipur"),
            "kolkata": (22.5726, 88.3639, "Kolkata"),
            "howrah": (22.5958, 88.2636, "Howrah"),
            "diamond-harbour": (22.1985, 88.1925, "South 24 Parganas"),
            "ghatal": (22.6658, 87.7226, "Paschim Medinipur"),
            "farakka": (24.7936, 87.9103, "Murshidabad / Malda"),
            "digha": (21.6266, 87.5074, "Purba Medinipur"),
            "jalpaiguri": (26.5405, 88.7194, "Jalpaiguri (North Bengal)")
        }

        for zid, (exp_lat, exp_lon, exp_dist) in expected_zones.items():
            self.assertIn(zid, WEST_BENGAL_ZONES)
            zone = WEST_BENGAL_ZONES[zid]
            self.assertAlmostEqual(zone["lat"], exp_lat, places=3)
            self.assertAlmostEqual(zone["lon"], exp_lon, places=3)
            self.assertEqual(zone["district"], exp_dist)
            # Latitude in West Bengal is between 21.0 and 27.5 N
            self.assertTrue(21.0 <= zone["lat"] <= 27.5)
            # Longitude in West Bengal is between 85.5 and 90.0 E
            self.assertTrue(85.5 <= zone["lon"] <= 90.0)

    def test_risk_category_boundary_precision(self):
        """Audit risk score boundaries: 0-29 LOW, 30-59 MODERATE, 60-79 HIGH, 80-100 SEVERE."""
        test_boundaries = [
            (0.0, "LOW"),
            (15.0, "LOW"),
            (29.9, "LOW"),
            (30.0, "MODERATE"),
            (45.0, "MODERATE"),
            (59.9, "MODERATE"),
            (60.0, "HIGH"),
            (70.0, "HIGH"),
            (79.9, "HIGH"),
            (80.0, "SEVERE"),
            (90.0, "SEVERE"),
            (100.0, "SEVERE")
        ]
        for score, expected_cat in test_boundaries:
            cat, col = get_risk_category(score)
            self.assertEqual(cat, expected_cat, f"Score {score} expected {expected_cat} but got {cat}")

    def test_readings_telemetry_fields_and_types(self):
        """Audit JSON field names for all 8 catchments in /api/readings."""
        resp = self.client.get("/api/readings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["count"], 8)
        readings = data["readings"]

        required_fields = [
            "zone_id", "zone_name", "district", "river_basin", "lat", "lon",
            "rainfall_24h_mm", "river_discharge_m3s", "risk_score", "risk_level",
            "freshness", "source", "contributing_factors", "recommended_precautions"
        ]

        for r in readings:
            for field in required_fields:
                self.assertIn(field, r, f"Missing field {field} in zone {r.get('zone_id')}")

            # Check values
            self.assertIsInstance(r["risk_score"], (int, float))
            self.assertTrue(0.0 <= r["risk_score"] <= 100.0)
            
            # Check level matches score
            cat, _ = get_risk_category(r["risk_score"])
            self.assertEqual(r["risk_level"], cat)

            # Check freshness
            self.assertIn(r["freshness"], ["LIVE", "CACHED", "DEMO", "UNAVAILABLE"])

            # Check precautions
            self.assertTrue(len(r["recommended_precautions"]) > 0)

            # Check units distinction: river_discharge_m3s is m3/s, rainfall_24h_mm is mm
            if r["rainfall_24h_mm"] is not None:
                self.assertGreaterEqual(r["rainfall_24h_mm"], 0.0)
            if r["river_discharge_m3s"] is not None:
                self.assertGreaterEqual(r["river_discharge_m3s"], 0.0)
            self.assertIsNone(r.get("river_water_level_m"), "River water level must be null unless measured by physical gauge")

    def test_table_headers_alignment_in_html(self):
        """Audit that index.html contains exactly 9 table headers matching the requested columns."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("<th>Zone</th>", html)
        self.assertIn("<th>District</th>", html)
        self.assertIn("<th>River Basin</th>", html)
        self.assertIn("<th>Rainfall (mm)</th>", html)
        self.assertIn("<th>River Discharge (m³/s)</th>", html)
        self.assertIn("<th>Risk Score / Category</th>", html)
        self.assertIn("<th>Data Freshness</th>", html)
        self.assertIn("<th>Recommended Action</th>", html)
        self.assertIn("<th>Details</th>", html)
        self.assertNotIn("JAL RAKSHAK", html)
        self.assertNotIn("JAL-RAKSHA", html)
        self.assertIn("Flood Early Warning", html)


if __name__ == "__main__":
    unittest.main()

