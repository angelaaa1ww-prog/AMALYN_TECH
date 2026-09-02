"""ML inference for AMALYN feedback detection using PyTorch."""

import os

import numpy as np
import torch

from ml_model import AmalynDetector, LABEL_NAMES, normalize_magnitudes

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'ml_models')
MODEL_PATH = os.path.join(MODEL_DIR, 'amalyn_detector.pth')

# Minimum confidence to promote an ML prediction over threshold detection.
ML_CONFIDENCE_GATE = 75.0


class MLInference:
    def __init__(self):
        self.model = None
        self.model_loaded = False
        self.load_model()

    def load_model(self):
        if not os.path.exists(MODEL_PATH):
            print("[ML] No trained model found — using threshold detection")
            return
        try:
            self.model = AmalynDetector()
            self.model.load_state_dict(
                torch.load(MODEL_PATH, map_location='cpu', weights_only=True)
            )
            self.model.eval()
            self.model_loaded = True
            print("[ML] Model loaded successfully")
        except Exception as e:
            print(f"[ML] Model load failed: {e} — using threshold detection")

    def predict(self, magnitudes_db):
        if not self.model_loaded:
            return None, None
        try:
            normalized = normalize_magnitudes(magnitudes_db)
            x = torch.FloatTensor(normalized).unsqueeze(0)
            with torch.no_grad():
                output = self.model(x)
                probs = torch.softmax(output, dim=1)[0]
                pred = torch.argmax(probs).item()
                confidence = round(probs[pred].item() * 100, 1)
            # Only report non-CLEAN status if confidence exceeds the gate
            label = LABEL_NAMES[pred]
            if label != "CLEAN" and confidence < ML_CONFIDENCE_GATE:
                return "CLEAN", confidence
            return label, confidence
        except Exception as e:
            print(f"[ML] Inference error: {e}")
            return None, None

    def is_ready(self):
        return self.model_loaded


ml_engine = MLInference()


def ml_check(magnitudes_db):
    return ml_engine.predict(magnitudes_db)