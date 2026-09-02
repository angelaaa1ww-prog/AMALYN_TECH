"""Central configuration for AMALYN's live audio and analysis pipeline."""

from __future__ import annotations

try:
    import pyaudio
except ImportError:  # The API and offline DSP tests remain usable without PyAudio.
    pyaudio = None


# --- AUDIO STREAM SETTINGS ---
CHANNELS = 1
RATE = 44_100
# 512 samples keeps end-to-end detection latency low (~11.6 ms per captured frame).
CHUNK = 512
FORMAT = pyaudio.paInt16 if pyaudio is not None else None


def get_pyaudio_format() -> int:
    """Return the capture format only when an audio backend is available."""
    if pyaudio is None:
        raise RuntimeError("PyAudio is not installed; audio capture is unavailable")
    return pyaudio.paInt16


# --- FEEDBACK DETECTION SETTINGS ---
FEEDBACK_FREQ_MIN = 200
FEEDBACK_FREQ_MAX = 16_000
# A feedback tone must stand out from its local spectrum to avoid flagging normal
# broad-band programme material as feedback.
MIN_TONE_PROMINENCE_DB = 6.0
LOCAL_NOISE_BINS = 4

# --- ALERT LEVELS ---
WARNING_THRESHOLD_DB = -25
CRITICAL_THRESHOLD_DB = -15

# --- ML SETTINGS ---
ML_FEATURE_COUNT = 257
ML_FEATURE_SCALE = "dBFS-v2"

# Kept for backward compatibility with older integrations.
FEEDBACK_THRESHOLD_DB = WARNING_THRESHOLD_DB
