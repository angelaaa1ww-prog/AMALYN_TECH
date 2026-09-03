import sys
import unittest
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ML_FEATURE_COUNT
from ml_inference import ML_CONFIDENCE_GATE, ml_check, ml_engine
from ml_model import AmalynDetector, FEATURE_COUNT, normalize_magnitudes


class MLPipelineTests(unittest.TestCase):
    def test_model_input_dimension_matches_feature_count(self):
        model = AmalynDetector()
        dummy_input = torch.randn(2, FEATURE_COUNT)
        output = model(dummy_input)
        self.assertEqual(output.shape, (2, 3))

    def test_normalize_magnitudes_pads_and_scales_properly(self):
        short_spectrum = np.array([-40.0, -20.0, -10.0])
        normalized = normalize_magnitudes(short_spectrum)
        self.assertEqual(len(normalized), FEATURE_COUNT)
        # -80 dBFS normalized is 0.0, 0 dBFS is 1.0, -40 dBFS is 0.5
        self.assertAlmostEqual(normalized[0], 0.5, delta=0.01)
        self.assertAlmostEqual(normalized[1], 0.75, delta=0.01)
        self.assertAlmostEqual(normalized[2], 0.875, delta=0.01)
        # Padded elements should be normalized -80.0 -> 0.0
        self.assertAlmostEqual(normalized[10], 0.0, delta=0.01)

    def test_ml_confidence_gate_threshold(self):
        self.assertEqual(ML_CONFIDENCE_GATE, 75.0)

    def test_ml_check_handles_uninitialized_model_gracefully(self):
        # Without model weights loaded, ml_check returns (None, None) safely
        status, conf = ml_check(np.full(ML_FEATURE_COUNT, -60.0))
        if not ml_engine.is_ready():
            self.assertIsNone(status)
            self.assertIsNone(conf)


if __name__ == "__main__":
    unittest.main()
