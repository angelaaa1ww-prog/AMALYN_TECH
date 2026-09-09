import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_utils import get_frequency_map
from calibration import (
    RTAMeasurement,
    SPLMeter,
    calculate_delay,
    generate_pink_noise,
    rms_dbfs,
    third_octave_levels,
)


class DelayCalculatorTests(unittest.TestCase):
    def test_distance_converts_to_time_of_flight(self):
        result = calculate_delay(34.342, temperature_c=20.0)

        self.assertAlmostEqual(result["delay_ms"], 100.0, delta=0.1)
        self.assertAlmostEqual(result["speed_of_sound_mps"], 343.42, delta=0.01)

    def test_delay_rejects_an_impossible_distance(self):
        with self.assertRaises(ValueError):
            calculate_delay(-0.1)


class SPLMeterTests(unittest.TestCase):
    def test_uncalibrated_meter_is_explicitly_dbfs(self):
        meter = SPLMeter(sample_rate=44_100)
        reading = meter.update(np.full(512, 16384, dtype=np.int16))

        self.assertFalse(reading["calibrated"])
        self.assertEqual(reading["unit"], "dBFS")
        self.assertAlmostEqual(reading["instant_db"], -6.02, delta=0.05)

    def test_calibrated_meter_applies_the_physical_reference_offset(self):
        meter = SPLMeter(sample_rate=44_100)
        meter.set_calibration(reference_dbfs=-20, reference_db_spl=94, limit_db_spl=100)
        reading = meter.update(np.full(512, 3277, dtype=np.int16))

        # -20 dBFS corresponds to 94 dB SPL, so the offset is +114 dB.
        self.assertTrue(reading["calibrated"])
        self.assertEqual(reading["unit"], "dB SPL (Z)")
        self.assertFalse(reading["compliance_ready"])
        self.assertAlmostEqual(reading["instant_db"], 94.0, delta=0.1)
        self.assertEqual(reading["limit_status"], "within_limit")

    def test_calibrated_meter_warns_when_the_limit_is_exceeded(self):
        meter = SPLMeter(sample_rate=44_100)
        meter.set_calibration(reference_dbfs=-20, reference_db_spl=94, limit_db_spl=95)
        reading = meter.update(np.full(512, 16384, dtype=np.int16))

        self.assertEqual(reading["limit_status"], "exceeded")


class RTATests(unittest.TestCase):
    def setUp(self):
        self.rate = 4096
        count = 4096
        self.samples = 0.5 * 32767 * np.sin(2 * np.pi * 1000 * np.arange(count) / self.rate)
        self.frequencies, self.magnitudes = get_frequency_map(self.samples, rate=self.rate)

    def test_third_octave_trace_contains_the_tone_band(self):
        bands = third_octave_levels(self.frequencies, self.magnitudes)
        tone_band = next(band for band in bands if band["frequency_hz"] == 1000.0)

        # A third-octave level is mean band power, so it is lower than the FFT
        # bin peak, but the tone remains clearly above the noise floor.
        self.assertGreater(tone_band["level_dbfs"], -45.0)

    def test_room_measurement_creates_cut_only_recommendations(self):
        measurement = RTAMeasurement()
        with patch("calibration.time.monotonic", side_effect=[0.0, 5.1, 5.1]):
            measurement.start(duration_seconds=5)
            result = measurement.update(self.frequencies, self.magnitudes)

        self.assertEqual(result["state"], "complete")
        correction = result["result"]["correction_eq"]
        self.assertTrue(correction)
        self.assertTrue(all(item["cut_db"] < 0 for item in correction))


class PinkNoiseTests(unittest.TestCase):
    def test_generated_pink_noise_respects_requested_rms_level(self):
        noise = generate_pink_noise(16_384, level_dbfs=-30, seed=7)

        self.assertEqual(noise.dtype, np.int16)
        self.assertAlmostEqual(rms_dbfs(noise), -30.0, delta=0.25)


if __name__ == "__main__":
    unittest.main()
