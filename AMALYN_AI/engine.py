"""Lifecycle-managed real-time audio analysis for the AMALYN API."""

from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Any

import numpy as np

try:
    import pyaudio
except ImportError:  # Allows the API's non-audio endpoints to remain available.
    pyaudio = None

from alerts import available_sensitivity_profiles, check_for_feedback
from audio_utils import get_dominant_frequency, get_frequency_map
from config import CHANNELS, CHUNK, RATE, get_pyaudio_format
from eq_engine import suggest_eq
from library import get_perfect_state
from logger import log_event
from mixer import AmalynMixerBridge
from sentinel import AmalynSentinel


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
        "ml_status": None,
        "ml_confidence": None,
        "sentinel": {"health_score": 100, "alerts": [], "signal_stats": {}},
    }


class AudioEngine:
    """Owns the microphone stream, worker thread, and latest API frame."""

    def __init__(
        self,
        mixer_type: str = "simulator",
        channel: int = 1,
        sensitivity: str = "balanced",
        enable_ml: bool = False,
    ) -> None:
        if sensitivity not in available_sensitivity_profiles():
            profiles = ", ".join(available_sensitivity_profiles())
            raise ValueError(f"Unknown sensitivity '{sensitivity}'. Supported: {profiles}")
        self.mixer_type = mixer_type
        self.channel = channel
        self.sensitivity = sensitivity
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
        self._last_correction_at = 0.0
        self._last_error: str | None = None
        self._sentinel = AmalynSentinel()
        self._ml_check = self._load_ml_check() if enable_ml else None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @staticmethod
    def _load_ml_check():
        """Load ML inference only for live API use, not offline DSP callers."""
        try:
            from ml_inference import ml_check

            return ml_check
        except Exception as error:
            logger.warning("ML inference is unavailable: %s", error)
            return None

    def set_sensitivity(self, sensitivity: str) -> None:
        """Select the early, balanced, or strict feedback profile."""
        if sensitivity not in available_sensitivity_profiles():
            profiles = ", ".join(available_sensitivity_profiles())
            raise ValueError(f"Unknown sensitivity '{sensitivity}'. Supported: {profiles}")
        with self._lock:
            self.sensitivity = sensitivity

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
        except Exception as error:
            if stream is not None:
                stream.close()
            audio.terminate()
            self._last_error = str(error)
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

    def apply_safe_profile(self) -> bool:
        """Apply the mixer safe profile when a connected mixer is available."""
        with self._lock:
            mixer = self._mixer
        return bool(mixer and mixer.send_safe_profile())

    def process_audio(self, audio_data: np.ndarray) -> dict[str, Any]:
        """Analyze one frame. Kept separate from I/O so the DSP path is testable."""
        frequencies, magnitudes_db = get_frequency_map(audio_data)
        dominant_freq, dominant_mag = get_dominant_frequency(frequencies, magnitudes_db)
        status, danger_freq, danger_mag = check_for_feedback(
            frequencies, magnitudes_db, sensitivity=self.sensitivity
        )
        suggestion = suggest_eq(danger_freq, danger_mag, status)

        ml_status, ml_confidence = None, None
        if self._ml_check is not None:
            ml_status, ml_confidence = self._ml_check(magnitudes_db)

        sentinel_alerts, health_score = self._sentinel.analyze(audio_data, magnitudes_db)

        mixer = self._mixer
        if status == "CLEAN":
            self._last_correction_frequency = None
            self._last_correction_at = 0.0
        elif suggestion and mixer is not None:
            correction_frequency = round(danger_freq, 1)
            frequency_tolerance = max(20.0, RATE / CHUNK * 0.75)
            correction_is_new = (
                self._last_correction_frequency is None
                or abs(correction_frequency - self._last_correction_frequency)
                >= frequency_tolerance
            )
            cooldown_complete = time.monotonic() - self._last_correction_at >= 0.75
            if correction_is_new and cooldown_complete and mixer.send_eq_correction(suggestion):
                self._last_correction_frequency = correction_frequency
                self._last_correction_at = time.monotonic()

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
            "ml_status": ml_status,
            "ml_confidence": ml_confidence,
            "sentinel": {
                "health_score": health_score,
                "alerts": sentinel_alerts[:3],
                "signal_stats": self._sentinel.get_signal_stats(),
            },
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
