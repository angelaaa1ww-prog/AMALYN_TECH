import pyaudio
import numpy as np

from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback, print_alert


def start_detector():
    """
    Main AMALYN feedback detection loop.
    Opens the microphone, analyzes audio in real time,
    and fires alerts when feedback is detected.
    """
    p = pyaudio.PyAudio()

    try:
        # Open microphone stream
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        print("\n" + "=" * 50)
        print("   AMALYN TECH — Feedback Detector Active")
        print("   Listening to your room...")
        print("   Press Ctrl+C to stop")
        print("=" * 50 + "\n")

        while True:
            # 1. Read raw audio from microphone
            data = stream.read(CHUNK, exception_on_overflow=False)

            # 2. Convert binary data to numpy array
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)

            # 3. Get full frequency map via FFT
            frequencies, magnitudes_db = get_frequency_map(audio_data)

            # 4. Find the single loudest frequency right now
            dominant_freq, dominant_mag = get_dominant_frequency(
                frequencies, magnitudes_db
            )

            # 5. Scan for feedback danger
            status, danger_freq, danger_mag = check_for_feedback(
                frequencies, magnitudes_db
            )

            # 6. Print the appropriate alert
            print_alert(
                status,
                danger_freq,
                danger_mag,
                dominant_freq,
                dominant_mag
            )

    except KeyboardInterrupt:
        print("\n\n--- AMALYN: Detector stopped cleanly ---\n")

    except Exception as e:
        print(f"\n❌ AMALYN ERROR: {e}")

    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    start_detector()