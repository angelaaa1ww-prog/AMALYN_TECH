import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eq_engine import EQ_BANDS, calculate_cut, get_eq_band, suggest_eq


class EQEngineTests(unittest.TestCase):
    def test_eq_band_boundaries_are_disjoint(self):
        """Boundary frequencies should cleanly belong to the intended upper band."""
        self.assertEqual(get_eq_band(20)["name"], "Sub Bass")
        self.assertEqual(get_eq_band(59.9)["name"], "Sub Bass")
        self.assertEqual(get_eq_band(60)["name"], "Bass")
        self.assertEqual(get_eq_band(250)["name"], "Low Mid")
        self.assertEqual(get_eq_band(500)["name"], "Mid")
        self.assertEqual(get_eq_band(2000)["name"], "High Mid")
        self.assertEqual(get_eq_band(4000)["name"], "Presence")
        self.assertEqual(get_eq_band(8000)["name"], "Air")

    def test_out_of_range_frequencies_return_unknown(self):
        self.assertEqual(get_eq_band(5)["name"], "Unknown")
        self.assertEqual(get_eq_band(25000)["name"], "Unknown")

    def test_calculate_cut_scaling(self):
        # excess <= 3 -> -3 dB
        self.assertEqual(calculate_cut(-23, threshold_db=-25), -3)
        # excess <= 6 -> -6 dB
        self.assertEqual(calculate_cut(-20, threshold_db=-25), -6)
        # excess <= 10 -> -9 dB
        self.assertEqual(calculate_cut(-16, threshold_db=-25), -9)
        # excess > 10 -> -12 dB
        self.assertEqual(calculate_cut(-10, threshold_db=-25), -12)

    def test_suggest_eq_filter_types_and_q(self):
        # > 1000 Hz uses Notch filter with Q=1.4
        suggestion_high = suggest_eq(2500.0, -15.0, "CRITICAL")
        self.assertIsNotNone(suggestion_high)
        self.assertEqual(suggestion_high["filter_type"], "Notch")
        self.assertEqual(suggestion_high["q_value"], 1.4)
        self.assertEqual(suggestion_high["band_name"], "High Mid")

        # <= 1000 Hz uses Bell filter with Q=0.8
        suggestion_low = suggest_eq(300.0, -18.0, "WARNING")
        self.assertIsNotNone(suggestion_low)
        self.assertEqual(suggestion_low["filter_type"], "Bell")
        self.assertEqual(suggestion_low["q_value"], 0.8)
        self.assertEqual(suggestion_low["band_name"], "Low Mid")

    def test_suggest_eq_returns_none_for_clean_or_invalid(self):
        self.assertIsNone(suggest_eq(1000.0, -20.0, "CLEAN"))
        self.assertIsNone(suggest_eq(0.0, -10.0, "CRITICAL"))
        self.assertIsNone(suggest_eq(-50.0, -10.0, "WARNING"))
        self.assertIsNone(suggest_eq(None, -10.0, "CRITICAL"))


if __name__ == "__main__":
    unittest.main()
