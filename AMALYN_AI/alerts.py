from __future__ import annotations

import numpy as np

from audio_utils import interpolate_peak_frequency
from config import (
    CRITICAL_THRESHOLD_DB,
    FEEDBACK_FREQ_MAX,
    FEEDBACK_FREQ_MIN,
    LOCAL_NOISE_BINS,
    MIN_TONE_PROMINENCE_DB,
    WARNING_THRESHOLD_DB,
)


SENSITIVITY_PROFILES = {
    "early": {"warning_db": -30.0, "critical_db": CRITICAL_THRESHOLD_DB},
    "balanced": {"warning_db": WARNING_THRESHOLD_DB, "critical_db": CRITICAL_THRESHOLD_DB},
    "strict": {"warning_db": -21.0, "critical_db": -12.0},
}


def available_sensitivity_profiles():
    """Return supported profile names for API/UI clients."""
    return tuple(SENSITIVITY_PROFILES)


def _tonal_candidates(frequencies, magnitudes_db):
    """Return local spectral peaks which rise above their nearby noise floor."""
    frequencies = np.asarray(frequencies, dtype=np.float64)
    magnitudes_db = np.asarray(magnitudes_db, dtype=np.float64)
    if frequencies.ndim != 1 or magnitudes_db.ndim != 1:
        raise ValueError("frequencies and magnitudes_db must be one-dimensional arrays")
    if len(frequencies) != len(magnitudes_db):
        raise ValueError("frequencies and magnitudes_db must be aligned")

    mask = (
        np.isfinite(frequencies)
        & np.isfinite(magnitudes_db)
        & (frequencies >= FEEDBACK_FREQ_MIN)
        & (frequencies <= FEEDBACK_FREQ_MAX)
    )
    candidate_indices = np.flatnonzero(mask)
    if candidate_indices.size == 0:
        return []

    candidates = []
    for index in candidate_indices:
        level = float(magnitudes_db[index])
        start = max(0, index - LOCAL_NOISE_BINS)
        end = min(len(magnitudes_db), index + LOCAL_NOISE_BINS + 1)
        neighbourhood = magnitudes_db[start:end]
        neighbours = np.delete(neighbourhood, index - start)

        # Tiny/synthetic inputs are still useful for callers and tests; they do
        # not contain enough neighbouring bins for a meaningful prominence test.
        if neighbours.size >= 4:
            if level < float(np.max(neighbours)):
                continue
            prominence = level - float(np.median(neighbours))
            if prominence < MIN_TONE_PROMINENCE_DB:
                continue

        candidates.append(
            (
                interpolate_peak_frequency(frequencies, magnitudes_db, int(index)),
                level,
            )
        )
    return candidates


def check_for_feedback(frequencies, magnitudes_db, sensitivity="balanced"):
    """
    Scans the frequency map for signs of feedback.
    Checks every frequency bin within the human hearing range
    and flags anything that crosses the danger thresholds.

    Returns:
        status (str): 'CLEAN', 'WARNING', or 'CRITICAL'
        danger_freq (float): the frequency causing the problem (0 if clean)
        danger_mag (float): its magnitude in dB (0 if clean)
    """
    try:
        thresholds = SENSITIVITY_PROFILES[sensitivity]
    except KeyError as error:
        profiles = ", ".join(available_sensitivity_profiles())
        raise ValueError(f"Unknown sensitivity '{sensitivity}'. Supported: {profiles}") from error

    candidates = _tonal_candidates(frequencies, magnitudes_db)
    if not candidates:
        return "CLEAN", 0.0, 0.0

    critical = [
        candidate
        for candidate in candidates
        if candidate[1] >= thresholds["critical_db"]
    ]
    warning = [
        candidate
        for candidate in candidates
        if candidate[1] >= thresholds["warning_db"]
    ]

    if critical:
        danger_freq, danger_mag = max(critical, key=lambda candidate: candidate[1])
        return "CRITICAL", danger_freq, danger_mag
    if warning:
        danger_freq, danger_mag = max(warning, key=lambda candidate: candidate[1])
        return "WARNING", danger_freq, danger_mag
    return "CLEAN", 0.0, 0.0


def print_alert(status, danger_freq, danger_mag, dominant_freq, dominant_mag):
    """
    Prints a formatted alert to the terminal based on system status.
    """
    if status == "CLEAN":
        print(
            f"✅ CLEAN       | Dominant: {dominant_freq:.1f}Hz "
            f"at {dominant_mag:.1f}dB                    ",
            end="\r"
        )

    elif status == "WARNING":
        print(
            f"\n⚠️  WARNING     | Feedback building at "
            f"{danger_freq:.1f}Hz — Magnitude: {danger_mag:.1f}dB"
        )
        print("   Recommended action: Reduce gain or pull that frequency on EQ\n")

    elif status == "CRITICAL":
        print(
            f"\n🚨 CRITICAL     | Feedback DETECTED at "
            f"{danger_freq:.1f}Hz — Magnitude: {danger_mag:.1f}dB"
        )
        print("   IMMEDIATE ACTION: Lower gain on this channel NOW\n")
