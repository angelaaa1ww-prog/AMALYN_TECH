import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel import AmalynSentinel


class SentinelTests(unittest.TestCase):
    def test_initial_health_score_is_perfect(self):
        sentinel = AmalynSentinel()
        status = sentinel.get_status()
        self.assertEqual(status["health_score"], 100)
        self.assertEqual(status["total_events"], 0)

    def test_clipping_detection(self):
        sentinel = AmalynSentinel()
        # Create heavily clipped signal (>95% amplitude)
        clipped_audio = np.full(512, 32000, dtype=np.int16)
        mags_db = np.full(257, -10.0)

        alerts = []
        for _ in range(25):
            alerts, health = sentinel.analyze(clipped_audio, mags_db)

        self.assertTrue(any(a["type"] == "CLIPPING" for a in alerts))
        self.assertLess(health, 100)

    def test_signal_dropout_detection(self):
        sentinel = AmalynSentinel()
        silent_audio = np.zeros(512, dtype=np.int16)
        mags_db = np.full(257, -100.0)

        alerts = []
        for _ in range(25):
            alerts, health = sentinel.analyze(silent_audio, mags_db)

        self.assertTrue(any(a["type"] == "DROPOUT" for a in alerts))
        self.assertLess(health, 100)

    def test_signal_stats_calculation(self):
        sentinel = AmalynSentinel()
        audio = np.full(512, 16384, dtype=np.int16)
        mags_db = np.full(257, -40.0)

        for _ in range(15):
            sentinel.analyze(audio, mags_db)

        stats = sentinel.get_signal_stats()
        self.assertIn("rms", stats)
        self.assertIn("clip_rate", stats)
        self.assertIn("noise_floor", stats)
        self.assertIn("dropout_rate", stats)
        self.assertAlmostEqual(stats["rms"], 0.5, delta=0.05)


if __name__ == "__main__":
    unittest.main()
