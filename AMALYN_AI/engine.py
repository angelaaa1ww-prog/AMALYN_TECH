"""Lifecycle-managed real-time audio analysis for the AMALYN API."""

from __future__ import annotations

import logging
import threading
from copy import deepcopy
from typing import Any

import numpy as np

try:
    import pyaudio
except ImportError:  # Allows the API's non-audio endpoints to remain available.
    pyaudio = None

from alerts import check_for_feedback
from audio_utils import get_dominant_frequency, get_frequency_map
from config import CHANNELS, CHUNK, RATE, get_pyaudio_format
from eq_engine import suggest_eq
from library import get_perfect_state
from logger import log_event
from mixer import AmalynMixerBridge


logger = logging.getLogger(__name__)


def _empty_frame() -> dict[str, Any]:
    return {
        "status": "CLEAN",
        "dominant_freq": 0.0,
        "dominant_mag": -80.0,
        "danger_freq": 0.0,
        "danger_mag": -80.0,
        "frequencies": [],
        "magnitudes": [],
        "suggestion": None,
        "mixer_corrections": {"total_corrections": 0, "corrections": []},
        "perfect_state": None,
    }


class AudioEngine:
    """Owns the microphone stream, worker thread, and latest API frame."""

    def __init__(self, mixer_type: str = "simulator", channel: int = 1) -> None:
        self.mixer_type = mixer_type
        self.channel = channel
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._audio = None
        self._stream = None
        self._mixer: AmalynMixerBridge | None = None
        self._latest_frame = _empty_frame()
        self._perfect_state: dict[str, Any] | None = None
        self._last_status = "CLEAN"
        self._last_correction_frequency: float | None = None
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> None:
        """Open the audio device and begin analysis. Safe to call more than once."""
        if self.is_running:
            return
        if pyaudio is None:
            raise RuntimeError("PyAudio is not installed; audio capture is unavailable")

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
            mixer = AmalynMixerBridge(mixer_type=self.mixer_type, channel=self.channel)
            mixer.connect()
        except Exception:
            if stream is not None:
                stream.close()
            audio.terminate()
            raise

        with self._lock:
            self._audio = audio
            self._stream = stream
            self._mixer = mixer
            self._last_error = None
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="amalyn-audio-engine", daemon=True
            )
            self._thread.start()
        logger.info("Audio engine started")

    def stop(self) -> None:
        """Stop analysis and release the microphone and OSC client."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

        with self._lock:
            stream, audio, mixer = self._stream, self._audio, self._mixer
            self._stream = None
            self._audio = None
            self._mixer = None
            self._thread = None

        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                logger.exception("Unable to close the audio stream")
        if audio is not None:
            audio.terminate()
        if mixer is not None:
            mixer.disconnect()

    def configure(
        self,
        venue: str,
        speaker: str | None = None,
        mic: str | None = None,
        mixer_type: str | None = None,
    ) -> dict[str, Any]:
        """Build and persist a session's Perfect State profile."""
        perfect_state = get_perfect_state(venue, speaker, mic, mixer_type)
        with self._lock:
            self._perfect_state = perfect_state
            self._latest_frame["perfect_state"] = deepcopy(perfect_state)
        return deepcopy(perfect_state)

    def snapshot(self) -> dict[str, Any]:
        """Return an isolated copy that can safely be serialized by a client."""
        with self._lock:
            return deepcopy(self._latest_frame)

    def process_audio(self, audio_data: np.ndarray) -> dict[str, Any]:
        """Analyze one frame. Kept separate from I/O so the DSP path is testable."""
        frequencies, magnitudes_db = get_frequency_map(audio_data)
        dominant_freq, dominant_mag = get_dominant_frequency(frequencies, magnitudes_db)
        status, danger_freq, danger_mag = check_for_feedback(frequencies, magnitudes_db)
        suggestion = suggest_eq(danger_freq, danger_mag, status)

        mixer = self._mixer
        if status == "CLEAN":
            self._last_correction_frequency = None
        elif suggestion and mixer is not None:
            correction_frequency = round(danger_freq, 1)
            if correction_frequency != self._last_correction_frequency:
                mixer.send_eq_correction(suggestion)
                self._last_correction_frequency = correction_frequency

        if status == "CRITICAL" and self._last_status != "CRITICAL" and mixer is not None:
            mixer.send_safe_profile()
        if status != "CLEAN" and status != self._last_status:
            log_event(status, danger_freq, danger_mag, suggestion)
        self._last_status = status

        mixer_corrections = (
            mixer.get_corrections_summary()
            if mixer is not None
            else {"total_corrections": 0, "corrections": []}
        )
        frame = {
            "status": status,
            "dominant_freq": round(float(dominant_freq), 1),
            "dominant_mag": round(float(dominant_mag), 1),
            "danger_freq": round(float(danger_freq), 1),
            "danger_mag": round(float(danger_mag), 1),
            "frequencies": [round(float(value), 1) for value in frequencies[::2]],
            "magnitudes": [round(float(value), 1) for value in magnitudes_db[::2]],
            "suggestion": suggestion,
            "mixer_corrections": mixer_corrections,
            "perfect_state": self._perfect_state,
        }
        with self._lock:
            self._latest_frame = frame
        return self.snapshot()

    def _run(self) -> None:
        logger.info("Audio analysis loop started")
        while not self._stop_event.is_set():
            stream = self._stream
            if stream is None:
                break
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.int16)
                self.process_audio(samples)
            except OSError as error:
                self._last_error = str(error)
                logger.warning("Audio input error: %s", error)
                self._stop_event.wait(0.1)
            except Exception as error:
                self._last_error = str(error)
                logger.exception("Audio analysis error")
                self._stop_event.wait(0.1)

