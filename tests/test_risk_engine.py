"""
Unit tests for Flood Risk Engine (tests/test_risk_engine.py).
Tests deterministic scoring, edge cases, partial data, boundary values, and explainability.
"""

import unittest
from risk_engine import (
    compute_flood_risk,
    sanitize_input,
    get_risk_category,
    ZONE_HYDROLOGY_DEFAULTS
)


class TestRiskEngine(unittest.TestCase):

    def test_sanitize_input(self):
        self.assertEqual(sanitize_input(10.5), 10.5)
        self.assertEqual(sanitize_input("25.4"), 25.4)
        self.assertIsNone(sanitize_input(None))
        self.assertIsNone(sanitize_input("invalid"))
        self.assertIsNone(sanitize_input(-15.0), "Negative values must be rejected as physically invalid")
        self.assertEqual(sanitize_input(15000.0), 10000.0, "Extreme values must be capped at max_val")

    def test_risk_categories(self):
        cat, col = get_risk_category(15.0)
        self.assertEqual(cat, "LOW")
        self.assertEqual(col, "#22c55e")

        cat, col = get_risk_category(45.0)
        self.assertEqual(cat, "MODERATE")
        self.assertEqual(col, "#eab308")

        cat, col = get_risk_category(72.0)
        self.assertEqual(cat, "HIGH")
        self.assertEqual(col, "#f97316")

        cat, col = get_risk_category(92.0)
        self.assertEqual(cat, "SEVERE")
        self.assertEqual(col, "#ef4444")

    def test_dry_baseline_condition(self):
        """Zero rainfall and low discharge should produce LOW risk."""
        result = compute_flood_risk(
            zone_id="haldia",
            rainfall_24h_mm=0.0,
            forecast_rain_7d_mm=0.0,
            river_discharge_m3s=2.0
        )
        self.assertIn("risk_score", result)
        self.assertLess(result["risk_score"], 30.0)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["data_quality"], "COMPLETE")
        self.assertTrue(len(result["contributing_factors"]) > 0)
        self.assertTrue(len(result["recommended_precautions"]) > 0)

    def test_extreme_flood_surge(self):
        """Torrential rain + critical river discharge should yield SEVERE risk."""
        result = compute_flood_risk(
            zone_id="ghatal",
            rainfall_24h_mm=130.0,
            forecast_rain_7d_mm=220.0,
            river_discharge_m3s=320.0
        )
        self.assertGreaterEqual(result["risk_score"], 80.0)
        self.assertEqual(result["risk_level"], "SEVERE")
        self.assertEqual(result["color"], "#ef4444")
        # Check evacuation precaution is generated
        precaution_text = " ".join(result["recommended_precautions"])
        self.assertIn("EMERGENCY", precaution_text)

    def test_moderate_threshold_trigger(self):
        """Rainfall and discharge around moderate thresholds."""
        result = compute_flood_risk(
            zone_id="haldia",
            rainfall_24h_mm=45.0,
            forecast_rain_7d_mm=75.0,
            river_discharge_m3s=28.0
        )
        self.assertGreaterEqual(result["risk_score"], 30.0)
        self.assertIn(result["risk_level"], ["MODERATE", "HIGH"])

    def test_partial_data_discharge_missing(self):
        """When discharge is missing, data_quality should be PARTIAL_PRECIP_ONLY and score normalized."""
        result = compute_flood_risk(
            zone_id="digha",
            rainfall_24h_mm=95.0,
            forecast_rain_7d_mm=150.0,
            river_discharge_m3s=None
        )
        self.assertEqual(result["data_quality"], "PARTIAL_PRECIP_ONLY")
        # Because rain is very high (95mm > 85mm severe threshold), normalized score should reach HIGH or SEVERE
        self.assertGreaterEqual(result["risk_score"], 60.0)

    def test_partial_data_rainfall_missing(self):
        """When rainfall is missing, data_quality should be PARTIAL_DISCHARGE_ONLY."""
        result = compute_flood_risk(
            zone_id="jalpaiguri",
            rainfall_24h_mm=None,
            forecast_rain_7d_mm=None,
            river_discharge_m3s=420.0  # Above severe threshold (400)
        )
        self.assertEqual(result["data_quality"], "PARTIAL_DISCHARGE_ONLY")
        self.assertGreaterEqual(result["risk_score"], 60.0)

    def test_negative_input_safety(self):
        """Negative inputs must not crash or reduce score below zero."""
        result = compute_flood_risk(
            zone_id="kolkata",
            rainfall_24h_mm=-50.0,
            forecast_rain_7d_mm=-20.0,
            river_discharge_m3s=-10.0
        )
        self.assertGreaterEqual(result["risk_score"], 0.0)
        self.assertLessEqual(result["risk_score"], 100.0)
        self.assertEqual(result["data_quality"], "DEGRADED")

    def test_boundary_zero_and_maximum(self):
        """Boundary tests for 0 and 1000mm rainfall."""
        zero_res = compute_flood_risk(
            zone_id="generic",
            rainfall_24h_mm=0.0,
            forecast_rain_7d_mm=0.0,
            river_discharge_m3s=0.0
        )
        self.assertGreaterEqual(zero_res["risk_score"], 0.0)

        max_res = compute_flood_risk(
            zone_id="generic",
            rainfall_24h_mm=1000.0,
            forecast_rain_7d_mm=1000.0,
            river_discharge_m3s=5000.0
        )
        self.assertEqual(max_res["risk_score"], 100.0)
        self.assertEqual(max_res["risk_level"], "SEVERE")

    def test_explainable_breakdown(self):
        """Result must contain explainable breakdown points and factor lists."""
        result = compute_flood_risk(
            zone_id="diamond-harbour",
            rainfall_24h_mm=55.0,
            forecast_rain_7d_mm=90.0,
            river_discharge_m3s=35.0
        )
        self.assertIn("breakdown", result)
        bd = result["breakdown"]
        self.assertIn("rainfall_points", bd)
        self.assertIn("discharge_points", bd)
        self.assertIn("forecast_points", bd)
        self.assertIn("topography_points", bd)
        self.assertTrue(any(f["factor"] == "24h Precipitation" for f in result["contributing_factors"]))


if __name__ == "__main__":
    unittest.main()

