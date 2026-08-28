"""Shared model architecture and feature preparation for AMALYN ML tools."""

import numpy as np
import torch
import torch.nn as nn

from config import ML_FEATURE_COUNT, ML_FEATURE_SCALE

FEATURE_COUNT = ML_FEATURE_COUNT
FEATURE_SCALE = ML_FEATURE_SCALE
LABEL_MAP = {"CLEAN": 0, "WARNING": 1, "CRITICAL": 2}
LABEL_NAMES = {value: key for key, value in LABEL_MAP.items()}


def normalize_magnitudes(magnitudes):
    """Pad/truncate one spectrum and apply the model's dBFS normalization."""
    values = np.asarray(magnitudes, dtype=np.float32).reshape(-1)[:FEATURE_COUNT]
    if values.size < FEATURE_COUNT:
        values = np.pad(values, (0, FEATURE_COUNT - values.size), constant_values=-80.0)
    return (values + 80.0) / 80.0


class AmalynDetector(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(FEATURE_COUNT, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, len(LABEL_NAMES)),
        )

    def forward(self, values):
        return self.network(values)
