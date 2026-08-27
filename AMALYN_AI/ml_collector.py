# ml_collector.py — AMALYN ML Training Data Collector
# Run this during a live session to collect labeled audio data

import pyaudio
import numpy as np
import csv
import os
import time
from datetime import datetime
from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map
from alerts import check_for_feedback

# --- DATA DIRECTORY ---
DATA_DIR = os.path.join(os.path.dirname(__file__), 'ml_data')
os.makedirs(DATA_DIR, exist_ok=True)

timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
DATA_FILE = os.path.join(DATA_DIR, f'training_{timestamp}.csv')

# --- AUDIO ---
p = pyaudio.PyAudio()
stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

print("\n" + "="*50)
print("   AMALYN ML Data Collector")
print("="*50)
print("Commands:")
print("  Press Enter      — label current audio as CLEAN")
print("  Type 'w' + Enter — label as WARNING")
print("  Type 'c' + Enter — label as CRITICAL")
print("  Type 'q' + Enter — quit and save")
print("="*50 + "\n")

frames_collected = {"CLEAN": 0, "WARNING": 0, "CRITICAL": 0}
current_label = "CLEAN"

# Write CSV header
with open(DATA_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    # Header: label + 257 frequency magnitude bins
    header = ['label'] + [f'bin_{i}' for i in range(257)]
    writer.writerow(header)


def collect_frame(label):
    try:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        frequencies, magnitudes_db = get_frequency_map(audio_data)
        mags = magnitudes_db[:257].tolist()
        if len(mags) < 257:
            mags += [-80.0] * (257 - len(mags))
        row = [label] + [round(m, 2) for m in mags]
        with open(DATA_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row)
        frames_collected[label] += 1
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


import threading

collecting = True
label = "CLEAN"


def auto_collect():
    while collecting:
        collect_frame(label)
        time.sleep(0.05)


collector_thread = threading.Thread(target=auto_collect, daemon=True)
collector_thread.start()

try:
    while True:
        cmd = input(f"[{label}] collecting... (Enter=CLEAN, w=WARNING, c=CRITICAL, q=quit): ").strip().lower()
        if cmd == 'q':
            break
        elif cmd == 'w':
            label = "WARNING"
        elif cmd == 'c':
            label = "CRITICAL"
        else:
            label = "CLEAN"

        total = sum(frames_collected.values())
        print(f"Collected: CLEAN={frames_collected['CLEAN']} WARNING={frames_collected['WARNING']} CRITICAL={frames_collected['CRITICAL']} TOTAL={total}")

except KeyboardInterrupt:
    pass
finally:
    collecting = False
    stream.stop_stream()
    stream.close()
    p.terminate()
    total = sum(frames_collected.values())
    print(f"\n[SAVED] {total} frames saved to {DATA_FILE}")
    print(f"  CLEAN    : {frames_collected['CLEAN']}")
    print(f"  WARNING  : {frames_collected['WARNING']}")
    print(f"  CRITICAL : {frames_collected['CRITICAL']}")