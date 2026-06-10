from config import (
    FEEDBACK_FREQ_MIN,
    FEEDBACK_FREQ_MAX,
    WARNING_THRESHOLD_DB,
    CRITICAL_THRESHOLD_DB
)


def check_for_feedback(frequencies, magnitudes_db):
    danger_freq = 0
    danger_mag = 0
    status = "CLEAN"

    for freq, mag in zip(frequencies, magnitudes_db):
        if not (FEEDBACK_FREQ_MIN <= freq <= FEEDBACK_FREQ_MAX):
            continue
        if mag >= CRITICAL_THRESHOLD_DB:
            if mag > danger_mag:
                status = "CRITICAL"
                danger_freq = freq
                danger_mag = mag
        elif mag >= WARNING_THRESHOLD_DB:
            if mag > danger_mag and status != "CRITICAL":
                status = "WARNING"
                danger_freq = freq
                danger_mag = mag

    return status, danger_freq, danger_mag


def print_alert(status, danger_freq, danger_mag, dominant_freq, dominant_mag):
    if status == "CLEAN":
        print(
            f"[CLEAN]    Dominant: {dominant_freq:.1f}Hz at {dominant_mag:.1f}dB          ",
            end="\r"
        )
    elif status == "WARNING":
        print(
            f"\n[WARNING]  Feedback building at {danger_freq:.1f}Hz -- Magnitude: {danger_mag:.1f}dB"
        )
        print("   Action: Reduce gain or pull that frequency on EQ\n")
    elif status == "CRITICAL":
        print(
            f"\n[CRITICAL] Feedback DETECTED at {danger_freq:.1f}Hz -- Magnitude: {danger_mag:.1f}dB"
        )
        print("   IMMEDIATE ACTION: Lower gain on this channel NOW\n")