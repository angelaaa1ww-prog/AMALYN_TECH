"""test_analog_advisor.py — Unit tests for AMALYN Analog Outboard Rack Advisor."""

import unittest
import numpy as np

from analog_advisor import (
    ISO_31_BANDS,
    detect_mains_hum,
    find_closest_iso_band,
    format_frequency,
    format_iso_label,
    generate_analog_advice,
)


class TestAnalogAdvisor(unittest.TestCase):
    def test_iso_31_bands_count(self):
        self.assertEqual(len(ISO_31_BANDS), 31)
        self.assertEqual(ISO_31_BANDS[0], 20.0)
        self.assertEqual(ISO_31_BANDS[-1], 20000.0)

    def test_closest_iso_band_snapping(self):
        # 3120 Hz should snap to 3150 Hz (3.15k)
        self.assertEqual(find_closest_iso_band(3120.0), 3150.0)
        # 1025 Hz should snap to 1000 Hz (1k)
        self.assertEqual(find_closest_iso_band(1025.0), 1000.0)
        # 61 Hz should snap to 63 Hz
        self.assertEqual(find_closest_iso_band(61.0), 63.0)
        # 2480 Hz should snap to 2500 Hz
        self.assertEqual(find_closest_iso_band(2480.0), 2500.0)

    def test_format_frequency_and_labels(self):
        self.assertEqual(format_frequency(63.0), "63 Hz")
        self.assertEqual(format_frequency(1000.0), "1 kHz")
        self.assertEqual(format_frequency(3150.0), "3.15 kHz")

        self.assertEqual(format_iso_label(63.0), "63")
        self.assertEqual(format_iso_label(1000.0), "1k")
        self.assertEqual(format_iso_label(3150.0), "3.15k")

    def test_clean_signal_produces_nominal_advice(self):
        advice = generate_analog_advice(
            status="CLEAN",
            danger_freq=0.0,
            danger_mag=-80.0,
            sentinel_stats={"clip_rate": 0.0, "rms": 0.05, "dropout_rate": 0.0, "noise_floor": -75.0}
        )
        self.assertEqual(advice["summary"]["status"], "CLEAN")
        self.assertEqual(advice["summary"]["total_actions"], 0)
        self.assertEqual(len(advice["geq_faders"]), 31)
        self.assertFalse(any(f["is_active"] for f in advice["geq_faders"]))
        self.assertEqual(advice["rack_status"]["geq"]["status"], "NOMINAL")
        self.assertEqual(advice["rack_status"]["console"]["status"], "NOMINAL")

    def test_critical_feedback_triggers_geq_and_sweep_mid(self):
        advice = generate_analog_advice(
            status="CRITICAL",
            danger_freq=3150.0,
            danger_mag=-12.0,
            sentinel_stats={"clip_rate": 0.0, "rms": 0.25, "dropout_rate": 0.0, "noise_floor": -70.0}
        )
        self.assertGreater(advice["summary"]["total_actions"], 0)

        # Check GEQ advice
        geq_actions = [a for a in advice["advice_list"] if a["category"] == "GEQ"]
        self.assertTrue(len(geq_actions) > 0)
        self.assertEqual(geq_actions[0]["iso_hz"], 3150.0)
        self.assertIn("3.15k", geq_actions[0]["action"])

        # Check console sweep mid advice
        console_actions = [a for a in advice["advice_list"] if a["category"] == "CONSOLE"]
        self.assertTrue(any("Mid" in a["title"] for a in console_actions))

        # Check 31-band fader active state
        active_faders = [f for f in advice["geq_faders"] if f["is_active"]]
        self.assertEqual(len(active_faders), 1)
        self.assertEqual(active_faders[0]["freq"], 3150.0)
        self.assertLess(active_faders[0]["cut_db"], 0)

    def test_low_rumble_triggers_80hz_hpf(self):
        advice = generate_analog_advice(
            status="WARNING",
            danger_freq=65.0,
            danger_mag=-20.0,
            sentinel_stats={"clip_rate": 0.0, "rms": 0.15, "dropout_rate": 0.0, "noise_floor": -65.0}
        )
        self.assertTrue(advice["channel_strip"]["hpf_80hz"])
        hpf_actions = [a for a in advice["advice_list"] if a["id"] == "console_hpf"]
        self.assertEqual(len(hpf_actions), 1)
        self.assertIn("80 Hz", hpf_actions[0]["title"])

    def test_crossover_overlap_detection(self):
        advice = generate_analog_advice(
            status="WARNING",
            danger_freq=140.0,
            danger_mag=-22.0,
            sentinel_stats={"clip_rate": 0.0, "rms": 0.15, "dropout_rate": 0.0, "noise_floor": -65.0}
        )
        crossover_actions = [a for a in advice["advice_list"] if a["category"] == "CROSSOVER"]
        self.assertTrue(len(crossover_actions) > 0)
        self.assertIn("Sub / Top Crossover", crossover_actions[0]["title"])

    def test_severe_clipping_triggers_amp_and_preamp_trim(self):
        advice = generate_analog_advice(
            status="CRITICAL",
            danger_freq=2500.0,
            danger_mag=-5.0,
            sentinel_stats={"clip_rate": 8.5, "rms": 0.92, "dropout_rate": 0.0, "noise_floor": -50.0}
        )
        amp_actions = [a for a in advice["advice_list"] if a["category"] == "AMP"]
        self.assertTrue(len(amp_actions) > 0)
        self.assertIn("Attenuator", amp_actions[0]["title"])

        console_gain_actions = [a for a in advice["advice_list"] if a["id"] == "console_gain"]
        self.assertEqual(len(console_gain_actions), 1)

    def test_mains_ground_hum_detection(self):
        # Create synthetic 50 Hz hum spike
        freqs = np.linspace(0, 500, 256)
        mags = np.full(256, -60.0)  # -60 dBFS noise floor
        # Inject 50 Hz hum spike at -30 dBFS
        idx_50 = int(np.argmin(np.abs(freqs - 50.0)))
        mags[idx_50] = -30.0

        hum = detect_mains_hum(freqs, mags)
        self.assertIsNotNone(hum)
        self.assertEqual(hum["hum_freq"], 50.0)
        self.assertGreater(hum["prominence"], 20.0)

        advice = generate_analog_advice(
            status="CLEAN",
            danger_freq=0.0,
            danger_mag=-80.0,
            frequencies=freqs,
            magnitudes_db=mags,
            sentinel_stats={"clip_rate": 0.0, "rms": 0.05, "dropout_rate": 0.0, "noise_floor": -60.0}
        )
        power_actions = [a for a in advice["advice_list"] if a["category"] == "POWER_RACK"]
        self.assertEqual(len(power_actions), 1)
        self.assertIn("Ground Loop", power_actions[0]["title"])
        self.assertIn("GROUND LIFT", power_actions[0]["action"])


if __name__ == "__main__":
    unittest.main()
