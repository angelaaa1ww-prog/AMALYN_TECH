"""Interactive spectrum visualizer for a local AMALYN audio input."""


def main():
    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.animation as animation
    import matplotlib.pyplot as plt
    import numpy as np
    import pyaudio

    from alerts import check_for_feedback
    from audio_utils import get_frequency_map
    from config import CHANNELS, CHUNK, RATE, get_pyaudio_format
    from eq_engine import suggest_eq
    from logger import log_event

    audio = pyaudio.PyAudio()
    stream = None
    try:
        stream = audio.open(
            format=get_pyaudio_format(),
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        frequencies = np.fft.rfftfreq(CHUNK, d=1.0 / RATE)
        magnitudes = np.full(len(frequencies), -80.0)
        figure, axis = plt.subplots(figsize=(12, 5))
        figure.patch.set_facecolor("#0a0a0a")
        axis.set_facecolor("#0a0a0a")
        line, = axis.plot(frequencies, magnitudes, color="#00ff88", linewidth=1.5)
        fill = axis.fill_between(frequencies, -80, magnitudes, alpha=0.3, color="#00ff88")

        axis.axhline(y=-25, color="#ffaa00", linestyle="--", linewidth=1, label="Warning (-25dBFS)")
        axis.axhline(y=-15, color="#ff3333", linestyle="--", linewidth=1, label="Critical (-15dBFS)")
        axis.set(xlim=(20, 20000), ylim=(-80, 0), xscale="log")
        axis.set_xlabel("Frequency (Hz)", color="white", fontsize=11)
        axis.set_ylabel("Magnitude (dBFS)", color="white", fontsize=11)
        axis.set_title("AMALYN TECH -- Live Spectrum Analyzer", color="#00ff88", fontsize=14, fontweight="bold")
        axis.tick_params(colors="white")
        for spine in axis.spines.values():
            spine.set_color("#333333")
        axis.legend(facecolor="#1a1a1a", labelcolor="white", fontsize=9, loc="upper right")
        axis.set_xticks([31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000])
        axis.set_xticklabels(["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"], color="white")

        status_text = axis.text(0.02, 0.95, "[LISTENING]", transform=axis.transAxes, color="#00ff88", fontsize=12, fontweight="bold", verticalalignment="top")
        suggestion_text = axis.text(0.02, 0.82, "", transform=axis.transAxes, color="#ffaa00", fontsize=9, verticalalignment="top")
        dominant_text = axis.text(0.02, 0.70, "", transform=axis.transAxes, color="#aaaaaa", fontsize=9, verticalalignment="top")
        plt.tight_layout()
        last_status = "CLEAN"

        def update(_frame):
            nonlocal fill, last_status
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frequencies, values = get_frequency_map(np.frombuffer(data, dtype=np.int16))
                smoothed = np.convolve(values, np.ones(3) / 3, mode="same")
                line.set_ydata(smoothed)
                fill.remove()
                fill = axis.fill_between(frequencies, -80, smoothed, alpha=0.2, color=line.get_color())

                status, danger_freq, danger_mag = check_for_feedback(frequencies, values)
                peak_index = np.argmax(smoothed[1:]) + 1
                dominant_freq, dominant_mag = frequencies[peak_index], smoothed[peak_index]
                color = {"CLEAN": "#00ff88", "WARNING": "#ffaa00", "CRITICAL": "#ff3333"}[status]
                line.set_color(color)
                status_text.set_color(color)
                status_text.set_text(
                    "[CLEAN]" if status == "CLEAN" else f"[{status}] {danger_freq:.0f}Hz at {danger_mag:.1f}dBFS"
                )

                suggestion = suggest_eq(danger_freq, danger_mag, status)
                if suggestion:
                    suggestion_text.set_text(
                        f"[EQ] Cut {suggestion['frequency']}Hz by {suggestion['cut_db']}dB | "
                        f"{suggestion['band_name']} | Q: {suggestion['q_value']}"
                    )
                    if status != last_status:
                        log_event(status, danger_freq, danger_mag, suggestion)
                else:
                    suggestion_text.set_text("")
                last_status = status
                dominant_text.set_text(f"Dominant: {dominant_freq:.0f}Hz at {dominant_mag:.1f}dBFS")
            except Exception as error:
                print(f"Visualizer error: {error}")
            return line, status_text, suggestion_text, dominant_text

        animation.FuncAnimation(figure, update, interval=50, blit=False, cache_frame_data=False)
        print("AMALYN TECH Spectrum Visualizer Active -- close the window to stop")
        plt.show()
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()
        print("AMALYN Visualizer closed cleanly")


if __name__ == "__main__":
    main()
