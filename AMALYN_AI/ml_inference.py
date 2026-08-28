"""Inference wrapper for the AMALYN feedback-status model."""

import json
import os

import torch

from ml_model import AmalynDetector, FEATURE_COUNT, FEATURE_SCALE, LABEL_NAMES, normalize_magnitudes


MODEL_PATH = os.path.join(os.path.dirname(__file__), "ml_models", "amalyn_detector.pth")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "ml_models", "model_config.json")


class MLInference:
    def __init__(self):
        self.model = None
        self.model_loaded = False
        self.load_model()

    def load_model(self):
        if not os.path.exists(MODEL_PATH):
            print("[ML] No trained model found — using threshold detection")
            return False

        try:
            with open(CONFIG_PATH, encoding="utf-8") as file:
                metadata = json.load(file)
            if metadata.get("input_size") != FEATURE_COUNT or metadata.get("feature_scale") != FEATURE_SCALE:
                print("[ML] Model was trained with an incompatible feature scale; retrain before use")
                return False
            model = AmalynDetector()
            model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True))
            model.eval()
            self.model = model
            self.model_loaded = True
            print("[ML] Model loaded successfully")
            return True
        except Exception as error:
            self.model = None
            self.model_loaded = False
            print(f"[ML] Model load failed: {error} — using threshold detection")
            return False

    def predict(self, magnitudes_db):
        if not self.model_loaded or self.model is None:
            return None, None

        try:
            features = torch.from_numpy(normalize_magnitudes(magnitudes_db)).unsqueeze(0)
            with torch.inference_mode():
                probabilities = torch.softmax(self.model(features), dim=1)[0]
            predicted_class = torch.argmax(probabilities).item()
            return LABEL_NAMES[predicted_class], round(float(probabilities[predicted_class]) * 100, 1)
        except Exception as error:
            print(f"[ML] Inference error: {error}")
            return None, None

    def is_ready(self):
        return self.model_loaded


ml_engine = MLInference()


def ml_check(magnitudes_db):
    """Return a predicted status/confidence pair, or ``(None, None)`` on fallback."""
    return ml_engine.predict(magnitudes_db)
