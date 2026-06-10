from config import (
    FEEDBACK_FREQ_MIN,
    FEEDBACK_FREQ_MAX,
    WARNING_THRESHOLD_DB,
    CRITICAL_THRESHOLD_DB,
    FEEDBACK_THRESHOLD_DB
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
    danger_freq = 0.0
    danger_mag = -999.0  # Must start below any real dB value (all dB values are negative)
    status = "CLEAN"

    for freq, mag in zip(frequencies, magnitudes_db):

        # Only analyze frequencies in the audible feedback range
        if not (FEEDBACK_FREQ_MIN <= freq <= FEEDBACK_FREQ_MAX):
            continue

        # Check for CRITICAL level first
        if mag >= CRITICAL_THRESHOLD_DB:
            # Only update if this is louder than previous danger found
            if mag > danger_mag:
                status = "CRITICAL"
                danger_freq = freq
                danger_mag = mag

        # Check for WARNING level
        elif mag >= WARNING_THRESHOLD_DB:
            if mag > danger_mag and status != "CRITICAL":
                status = "WARNING"
                danger_freq = freq
                danger_mag = mag

    # Reset to 0 if no danger was found, to preserve clean return format
    if status == "CLEAN":
        danger_mag = 0.0

    return status, danger_freq, danger_mag


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