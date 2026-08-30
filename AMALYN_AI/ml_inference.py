import numpy as np
import os
import torch
import torch.nn as nn

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'ml_models')
MODEL_PATH = os.path.join(MODEL_DIR, 'amalyn_detector.pth')

LABEL_NAMES = {0: "CLEAN", 1: "WARNING", 2: "CRITICAL"}


class AmalynDetector(nn.Module):
    def __init__(self):
        super(AmalynDetector, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(257, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, 3)
        )

    def forward(self, x):
        return self.network(x)


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
                torch.load(MODEL_PATH, map_location='cpu')
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
            mags = list(magnitudes_db[:257])
            if len(mags) < 257:
                mags += [-80.0] * (257 - len(mags))
            mags = [(m + 80) / 80 for m in mags]
            x = torch.FloatTensor(mags).unsqueeze(0)
            with torch.no_grad():
                output = self.model(x)
                probs = torch.softmax(output, dim=1)[0]
                pred = torch.argmax(probs).item()
                confidence = probs[pred].item()
            return LABEL_NAMES[pred], round(confidence * 100, 1)
        except Exception as e:
            print(f"[ML] Inference error: {e}")
            return None, None

    def is_ready(self):
        return self.model_loaded


ml_engine = MLInference()


def ml_check(magnitudes_db):
    return ml_engine.predict(magnitudes_db)