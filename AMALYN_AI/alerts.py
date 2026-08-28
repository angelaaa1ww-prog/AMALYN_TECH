from config import (
    FEEDBACK_FREQ_MIN,
    FEEDBACK_FREQ_MAX,
    WARNING_THRESHOLD_DB,
    CRITICAL_THRESHOLD_DB,
)


def check_for_feedback(frequencies, magnitudes_db):
    """
    Scans the frequency map for signs of feedback.
    Checks every frequency bin within the human hearing range
    and flags anything that crosses the danger thresholds.

    Returns:
        status (str): 'CLEAN', 'WARNING', or 'CRITICAL'
        danger_freq (float): the frequency causing the problem (0 if clean)
        danger_mag (float): its magnitude in dB (0 if clean)
    """
    candidates = [
        (float(freq), float(magnitude))
        for freq, magnitude in zip(frequencies, magnitudes_db)
        if FEEDBACK_FREQ_MIN <= freq <= FEEDBACK_FREQ_MAX
    ]
    if not candidates:
        return "CLEAN", 0.0, 0.0

    critical = [candidate for candidate in candidates if candidate[1] >= CRITICAL_THRESHOLD_DB]
    warning = [candidate for candidate in candidates if candidate[1] >= WARNING_THRESHOLD_DB]

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
