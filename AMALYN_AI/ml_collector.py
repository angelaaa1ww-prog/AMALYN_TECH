"""Collect explicitly labelled audio frames for AMALYN model training."""

import csv
import os
import threading
import time
from datetime import datetime

import numpy as np

from audio_utils import get_frequency_map
from config import (
    CHANNELS,
    CHUNK,
    ML_FEATURE_COUNT,
    ML_FEATURE_SCALE,
    RATE,
    get_pyaudio_format,
)


DATA_DIR = os.path.join(os.path.dirname(__file__), "ml_data")
FRAME_SIZE = ML_FEATURE_COUNT


class AudioDataCollector:
    def __init__(self, stream, output_path):
        self.stream = stream
        self.output_path = output_path
        self.counts = {"CLEAN": 0, "WARNING": 0, "CRITICAL": 0}
        self._label = "CLEAN"
        self._label_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._file = open(output_path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._frames_since_flush = 0

    @property
    def label(self):
        with self._label_lock:
            return self._label

    def set_label(self, label):
        if label not in self.counts:
            raise ValueError(f"Unsupported label: {label}")
        with self._label_lock:
            self._label = label

    def collect_frame(self):
        label = self.label
        try:
            data = self.stream.read(CHUNK, exception_on_overflow=False)
            _, magnitudes_db = get_frequency_map(
                np.frombuffer(data, dtype=np.int16)
            )
            magnitudes = magnitudes_db[:FRAME_SIZE].tolist()
            magnitudes.extend([-80.0] * (FRAME_SIZE - len(magnitudes)))

            self._writer.writerow(
                [ML_FEATURE_SCALE, label, *[round(value, 2) for value in magnitudes]]
            )
            self._frames_since_flush += 1
            if self._frames_since_flush >= 20:
                self._file.flush()
                self._frames_since_flush = 0
            self.counts[label] += 1
        except Exception as error:
            print(f"[COLLECTOR] Frame skipped: {error}")

    def run(self):
        while not self._stop_event.is_set():
            self.collect_frame()
            self._stop_event.wait(0.05)

    def stop(self):
        self._stop_event.set()
        try:
            self._file.flush()
            self._file.close()
        except Exception:
            pass


def main():
    import pyaudio

    os.makedirs(DATA_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = os.path.join(DATA_DIR, f"training_{timestamp}.csv")

    audio = pyaudio.PyAudio()
    stream = None
    collector = None
    worker = None
    try:
        stream = audio.open(
            format=get_pyaudio_format(),
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        with open(output_path, "w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(
                ["feature_scale", "label", *[f"bin_{index}" for index in range(FRAME_SIZE)]]
            )

        collector = AudioDataCollector(stream, output_path)
        worker = threading.Thread(target=collector.run, name="amalyn-data-collector", daemon=True)
        worker.start()

        print("\nAMALYN ML Data Collector")
        print("Enter = CLEAN | w = WARNING | c = CRITICAL | q = quit\n")
        while True:
            command = input(f"[{collector.label}] collecting: ").strip().lower()
            if command == "q":
                break
            collector.set_label({"w": "WARNING", "c": "CRITICAL"}.get(command, "CLEAN"))
            print(f"Collected: {collector.counts} | total={sum(collector.counts.values())}")
    except KeyboardInterrupt:
        pass
    finally:
        if collector is not None:
            collector.stop()
        if worker is not None:
            worker.join(timeout=1)
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()
        if collector is not None:
            print(f"\n[SAVED] {sum(collector.counts.values())} frames to {output_path}")


if __name__ == "__main__":
    main()
