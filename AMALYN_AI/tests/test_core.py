import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alerts import check_for_feedback
from audio_utils import MIN_DBFS, get_dominant_frequency, get_frequency_map
from config import CHUNK, ML_FEATURE_COUNT
from engine import AudioEngine
from eq_engine import suggest_eq
from library import get_perfect_state
from sentinel import AmalynSentinel


class AudioAnalysisTests(unittest.TestCase):
    def test_bin_centred_sine_is_normalized_to_dbfs(self):
        sample_rate = 4096
        sample_count = 4096
        frequency = 256
        samples = 0.5 * 32767 * np.sin(
            2 * np.pi * frequency * np.arange(sample_count) / sample_rate
        )

        frequencies, magnitudes_db = get_frequency_map(samples, rate=sample_rate)
        dominant_frequency, dominant_magnitude = get_dominant_frequency(
            frequencies, magnitudes_db
        )

        self.assertEqual(dominant_frequency, frequency)
        self.assertAlmostEqual(dominant_magnitude, -6.02, delta=0.15)

    def test_silence_has_a_bounded_floor_and_no_feedback(self):
        frequencies, magnitudes_db = get_frequency_map(np.zeros(512))
        self.assertTrue(np.all(magnitudes_db == MIN_DBFS))
        self.assertEqual(check_for_feedback(frequencies, magnitudes_db), ("CLEAN", 0.0, 0.0))

    def test_odd_length_fft_scales_the_final_positive_frequency_bin(self):
        sample_rate = 4095
        sample_count = 4095
        frequency = 1024
        samples = 0.25 * 32767 * np.sin(
            2 * np.pi * frequency * np.arange(sample_count) / sample_rate
        )
        frequencies, magnitudes_db = get_frequency_map(samples, rate=sample_rate)
        peak = np.argmax(magnitudes_db)

        self.assertEqual(frequencies[peak], frequency)
        self.assertAlmostEqual(magnitudes_db[peak], -12.04, delta=0.15)

    def test_off_bin_tone_uses_interpolated_frequency(self):
        sample_rate = 4096
        sample_count = 4096
        frequency = 256.3
        samples = 0.5 * 32767 * np.sin(
            2 * np.pi * frequency * np.arange(sample_count) / sample_rate
        )

        frequencies, magnitudes_db = get_frequency_map(samples, rate=sample_rate)
        dominant_frequency, _ = get_dominant_frequency(frequencies, magnitudes_db)

        self.assertAlmostEqual(dominant_frequency, frequency, delta=0.1)

    def test_feedback_prefers_the_loudest_critical_frequency(self):
        status, frequency, magnitude = check_for_feedback(
            np.array([150.0, 500.0, 1000.0, 17000.0]),
            np.array([-2.0, -18.0, -12.0, -1.0]),
        )
        self.assertEqual(status, "CRITICAL")
        self.assertEqual(frequency, 1000.0)
        self.assertEqual(magnitude, -12.0)

    def test_early_profile_detects_a_quiet_narrow_tone_without_flagging_broadband_audio(self):
        frequencies = np.arange(100, 16100, 100, dtype=float)
        magnitudes_db = np.full(frequencies.size, -65.0)
        magnitudes_db[np.where(frequencies == 1000)[0][0]] = -28.0

        self.assertEqual(
            check_for_feedback(frequencies, magnitudes_db), ("CLEAN", 0.0, 0.0)
        )
        status, frequency, magnitude = check_for_feedback(
            frequencies, magnitudes_db, sensitivity="early"
        )
        self.assertEqual(status, "WARNING")
        self.assertEqual(frequency, 1000.0)
        self.assertEqual(magnitude, -28.0)

        magnitudes_db.fill(-18.0)
        self.assertEqual(
            check_for_feedback(frequencies, magnitudes_db), ("CLEAN", 0.0, 0.0)
        )

    def test_ml_feature_size_matches_live_fft_size(self):
        self.assertEqual(ML_FEATURE_COUNT, CHUNK // 2 + 1)


class ApplicationStateTests(unittest.TestCase):
    def test_perfect_state_merges_matching_eq_bands_by_deepest_cut(self):
        state = get_perfect_state("church", speaker_key="jbl_srx835p")
        cuts_by_frequency = {item["frequency"]: item["cut_db"] for item in state["combined_eq"]}

        self.assertEqual(state["venue"], "House of Worship")
        self.assertEqual(cuts_by_frequency[250], -3.0)
        self.assertEqual(cuts_by_frequency[2400], -3.0)

    def test_engine_processes_audio_without_opening_a_device(self):
        engine = AudioEngine()
        frame = engine.process_audio(np.zeros(512, dtype=np.int16))

        self.assertEqual(frame["status"], "CLEAN")
        self.assertEqual(frame["mixer_corrections"]["total_corrections"], 0)
        self.assertGreater(len(frame["frequencies"]), 0)
        self.assertIn("sentinel", frame)
        self.assertIn("health_score", frame["sentinel"])

    def test_eq_suggestion_requires_a_real_detected_frequency(self):
        self.assertIsNone(suggest_eq(0.0, -12.0, "CRITICAL"))

    def test_sentinel_detects_a_rising_noise_floor_in_dbfs_direction(self):
        sentinel = AmalynSentinel()
        audio = np.full(512, 3276, dtype=np.int16)
        quiet_spectrum = np.full(257, -100.0)
        noisy_spectrum = np.full(257, -80.0)

        for _ in range(50):
            sentinel.analyze(audio, quiet_spectrum)
        for _ in range(5):
            alerts, _ = sentinel.analyze(audio, noisy_spectrum)

        self.assertTrue(any(alert["type"] == "INTERFERENCE" for alert in alerts))

    def test_api_import_is_safe_without_starting_audio_capture(self):
        import api

        self.assertEqual(api.app.title, "AMALYN TECH API")
        self.assertFalse(hasattr(api.app.state, "engine"))


if __name__ == "__main__":
    unittest.main()
