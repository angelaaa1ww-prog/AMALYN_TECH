# --- AUDIO STREAM SETTINGS ---
CHANNELS = 1
RATE = 44100
CHUNK = 512


def get_pyaudio_format():
    """Load PyAudio only in programs that actually open an audio device."""
    import pyaudio

    return pyaudio.paInt16

# --- FEEDBACK DETECTION SETTINGS ---
FEEDBACK_FREQ_MIN = 200
FEEDBACK_FREQ_MAX = 16000

# --- ALERT LEVELS ---
WARNING_THRESHOLD_DB = -25
CRITICAL_THRESHOLD_DB = -15
