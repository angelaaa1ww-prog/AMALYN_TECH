import matplotlib
matplotlib.use('TkAgg')

import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import pyaudio
from config import CHANNELS, RATE, CHUNK, get_pyaudio_format
from audio_utils import get_frequency_map
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event

p = pyaudio.PyAudio()
stream = p.open(
    format=get_pyaudio_format(),
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

frequencies = np.fft.rfftfreq(CHUNK, d=1.0 / RATE)
magnitudes = np.full(len(frequencies), -80.0)

fig, ax = plt.subplots(figsize=(12, 5))
fig.patch.set_facecolor('#0a0a0a')
ax.set_facecolor('#0a0a0a')

line, = ax.plot(frequencies, magnitudes, color='#00ff88', linewidth=1.5)
fill = ax.fill_between(frequencies, -80, magnitudes, alpha=0.3, color='#00ff88')

ax.axhline(y=-25, color='#ffaa00', linestyle='--', linewidth=1, label='Warning (-25dB)')
ax.axhline(y=-15, color='#ff3333', linestyle='--', linewidth=1, label='Critical (-15dB)')

ax.set_xlim(20, 20000)
ax.set_ylim(-80, 0)
ax.set_xscale('log')
ax.set_xlabel('Frequency (Hz)', color='white', fontsize=11)
ax.set_ylabel('Magnitude (dB)', color='white', fontsize=11)
ax.set_title('AMALYN TECH -- Live Spectrum Analyzer', color='#00ff88', fontsize=14, fontweight='bold')
ax.tick_params(colors='white')
ax.spines['bottom'].set_color('#333333')
ax.spines['top'].set_color('#333333')
ax.spines['left'].set_color('#333333')
ax.spines['right'].set_color('#333333')
ax.legend(facecolor='#1a1a1a', labelcolor='white', fontsize=9, loc='upper right')

ax.set_xticks([31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000])
ax.set_xticklabels(['31', '63', '125', '250', '500', '1k', '2k', '4k', '8k', '16k'], color='white')

status_text = ax.text(
    0.02, 0.95, '[LISTENING]',
    transform=ax.transAxes,
    color='#00ff88',
    fontsize=12,
    fontweight='bold',
    verticalalignment='top'
)

suggestion_text = ax.text(
    0.02, 0.82, '',
    transform=ax.transAxes,
    color='#ffaa00',
    fontsize=9,
    verticalalignment='top'
)

dominant_text = ax.text(
    0.02, 0.70, '',
    transform=ax.transAxes,
    color='#aaaaaa',
    fontsize=9,
    verticalalignment='top'
)

plt.tight_layout()

last_viz_status = "CLEAN"


def update(frame):
    global fill, last_viz_status

    try:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        freqs, mags = get_frequency_map(audio_data)
        mags_smooth = np.convolve(mags, np.ones(3) / 3, mode='same')

        line.set_ydata(mags_smooth)
        fill.remove()
        fill = ax.fill_between(freqs, -80, mags_smooth, alpha=0.2, color=line.get_color())

        status, danger_freq, danger_mag = check_for_feedback(freqs, mags)

        peak_index = np.argmax(mags_smooth)
        dominant_freq = freqs[peak_index]
        dominant_mag = mags_smooth[peak_index]

        if status == "CRITICAL":
            line.set_color('#ff3333')
            status_text.set_text(f'[CRITICAL] {danger_freq:.0f}Hz at {danger_mag:.1f}dB')
            status_text.set_color('#ff3333')
        elif status == "WARNING":
            line.set_color('#ffaa00')
            status_text.set_text(f'[WARNING] {danger_freq:.0f}Hz at {danger_mag:.1f}dB')
            status_text.set_color('#ffaa00')
        else:
            line.set_color('#00ff88')
            status_text.set_text('[CLEAN]')
            status_text.set_color('#00ff88')

        suggestion = suggest_eq(danger_freq, danger_mag, status)
        if suggestion:
            suggestion_text.set_text(
                f"[EQ] Cut {suggestion['frequency']}Hz by {suggestion['cut_db']}dB"
                f" | {suggestion['band_name']} | Q: {suggestion['q_value']}"
            )
            if status != last_viz_status:
                log_event(status, danger_freq, danger_mag, suggestion)
                last_viz_status = status
        else:
            suggestion_text.set_text('')
            last_viz_status = status

        dominant_text.set_text(f"Dominant: {dominant_freq:.0f}Hz at {dominant_mag:.1f}dB")

    except Exception as e:
        print(f"Visualizer error: {e}")

    return line, status_text, suggestion_text, dominant_text


ani = animation.FuncAnimation(
    fig,
    update,
    interval=50,
    blit=False,
    cache_frame_data=False
)

print("\n" + "=" * 50)
print("   AMALYN TECH -- Spectrum Visualizer Active")
print("   Close the window to stop")
print("=" * 50 + "\n")

try:
    plt.show()
finally:
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("\n--- AMALYN Visualizer closed cleanly ---\n")
