"""Measurement utilities for AMALYN's room-calibration workflow.

The functions in this module deliberately keep dBFS and dB SPL separate.  A
microphone capture is dBFS until an engineer supplies a physical SPL reference;
only then may the UI describe a value as dB SPL.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Any

import numpy as np

from audio_utils import FULL_SCALE_INT16, MIN_DBFS


DEFAULT_TEMPERATURE_C = 20.0
MIN_TEMPERATURE_C = -40.0
MAX_TEMPERATURE_C = 60.0
MIN_DISTANCE_M = 0.0
MAX_DISTANCE_M = 2_000.0
MIN_DB_SPL = 0.0
MAX_DB_SPL = 160.0

# IEC-style preferred one-third-octave centres.  Keeping a fixed list makes a
# room trace comparable from one calibration session to the next.
THIRD_OCTAVE_CENTRES_HZ = np.array(
    [
        25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0,
        250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0,
        2000.0, 2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0, 10000.0,
        12500.0, 16000.0,
    ],
    dtype=np.float64,
)


def speed_of_sound_mps(temperature_c: float = DEFAULT_TEMPERATURE_C) -> float:
    """Return the approximate dry-air speed of sound for a room temperature."""
    temperature = float(temperature_c)
    if not MIN_TEMPERATURE_C <= temperature <= MAX_TEMPERATURE_C:
        raise ValueError(
            f"temperature_c must be between {MIN_TEMPERATURE_C:g} and {MAX_TEMPERATURE_C:g}"
        )
    # A practical live-sound approximation. Humidity compensation is intentionally
    # deferred until AMALYN has a real sensor source rather than guessed data.
    return 331.3 + 0.606 * temperature


def calculate_delay(
    distance_m: float, temperature_c: float = DEFAULT_TEMPERATURE_C
) -> dict[str, float]:
    """Calculate time of flight for a delayed/fill loudspeaker."""
    distance = float(distance_m)
    if not MIN_DISTANCE_M <= distance <= MAX_DISTANCE_M:
        raise ValueError(
            f"distance_m must be between {MIN_DISTANCE_M:g} and {MAX_DISTANCE_M:g}"
        )
    sound_speed = speed_of_sound_mps(temperature_c)
    delay_seconds = distance / sound_speed
    return {
        "distance_m": round(distance, 3),
        "temperature_c": round(float(temperature_c), 1),
        "speed_of_sound_mps": round(sound_speed, 2),
        "delay_ms": round(delay_seconds * 1_000, 2),
        "delay_samples_44k1": round(delay_seconds * 44_100, 1),
    }


def rms_dbfs(audio_data: np.ndarray) -> float:
    """Return RMS level in dBFS for signed 16-bit capture data."""
    samples = np.asarray(audio_data, dtype=np.float64)
    if samples.size == 0:
        raise ValueError("audio_data must not be empty")
    rms = float(np.sqrt(np.mean(np.square(samples / FULL_SCALE_INT16))))
    return max(MIN_DBFS, 20.0 * math.log10(max(rms, 10 ** (MIN_DBFS / 20.0))))


def peak_dbfs(audio_data: np.ndarray) -> float:
    """Return sample-peak level in dBFS for signed 16-bit capture data."""
    samples = np.asarray(audio_data, dtype=np.float64)
    if samples.size == 0:
        raise ValueError("audio_data must not be empty")
    peak = float(np.max(np.abs(samples)) / FULL_SCALE_INT16)
    return max(MIN_DBFS, 20.0 * math.log10(max(peak, 10 ** (MIN_DBFS / 20.0))))


@dataclass(frozen=True)
class SPLCalibration:
    """A physical reference mapping between an interface level and dB SPL."""

    reference_dbfs: float
    reference_db_spl: float
    limit_db_spl: float | None = None

    @property
    def offset_db(self) -> float:
        return self.reference_db_spl - self.reference_dbfs

    def to_spl(self, dbfs: float) -> float:
        return dbfs + self.offset_db


class SPLMeter:
    """Session SPL/dBFS meter with slow, equivalent and peak readings."""

    def __init__(self, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = sample_rate
        self._lock = threading.RLock()
        self._calibration: SPLCalibration | None = None
        self.reset()

    def set_calibration(
        self,
        reference_dbfs: float,
        reference_db_spl: float,
        limit_db_spl: float | None = None,
    ) -> dict[str, Any]:
        reference_dbfs = float(reference_dbfs)
        reference_db_spl = float(reference_db_spl)
        if not MIN_DBFS <= reference_dbfs <= 0:
            raise ValueError(f"reference_dbfs must be between {MIN_DBFS:g} and 0")
        if not MIN_DB_SPL <= reference_db_spl <= MAX_DB_SPL:
            raise ValueError(f"reference_db_spl must be between {MIN_DB_SPL:g} and {MAX_DB_SPL:g}")
        if limit_db_spl is not None:
            limit_db_spl = float(limit_db_spl)
            if not MIN_DB_SPL <= limit_db_spl <= MAX_DB_SPL:
                raise ValueError(f"limit_db_spl must be between {MIN_DB_SPL:g} and {MAX_DB_SPL:g}")

        with self._lock:
            self._calibration = SPLCalibration(
                reference_dbfs=reference_dbfs,
                reference_db_spl=reference_db_spl,
                limit_db_spl=limit_db_spl,
            )
            return self.snapshot()

    def clear_calibration(self) -> dict[str, Any]:
        with self._lock:
            self._calibration = None
            return self.snapshot()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            self._slow_mean_square: float | None = None
            self._energy_sum = 0.0
            self._sample_count = 0
            self._session_peak_dbfs = MIN_DBFS
            self._latest_rms_dbfs = MIN_DBFS
            self._latest_peak_dbfs = MIN_DBFS

    def update(self, audio_data: np.ndarray) -> dict[str, Any]:
        samples = np.asarray(audio_data, dtype=np.float64)
        if samples.size == 0:
            return self.snapshot()
        normalised = samples / FULL_SCALE_INT16
        mean_square = float(np.mean(np.square(normalised)))
        duration_s = samples.size / self.sample_rate
        # IEC "slow" is approximately a one-second exponential integration.
        alpha = math.exp(-duration_s / 1.0)

        with self._lock:
            if self._slow_mean_square is None:
                self._slow_mean_square = mean_square
            else:
                self._slow_mean_square = (
                    alpha * self._slow_mean_square + (1.0 - alpha) * mean_square
                )
            self._energy_sum += float(np.sum(np.square(normalised)))
            self._sample_count += int(samples.size)
            self._latest_rms_dbfs = _power_to_db(mean_square)
            self._latest_peak_dbfs = peak_dbfs(samples)
            self._session_peak_dbfs = max(self._session_peak_dbfs, self._latest_peak_dbfs)
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            leq_dbfs = _power_to_db(
                self._energy_sum / self._sample_count if self._sample_count else 0.0
            )
            slow_dbfs = _power_to_db(self._slow_mean_square or 0.0)
            calibration = self._calibration
            values = {
                "instant": self._latest_rms_dbfs,
                "slow": slow_dbfs,
                "leq": leq_dbfs,
                "peak": self._session_peak_dbfs,
            }
            if calibration is None:
                return {
                    "calibrated": False,
                    "compliance_ready": False,
                    "unit": "dBFS",
                    "instant_db": round(values["instant"], 1),
                    "slow_db": round(values["slow"], 1),
                    "leq_db": round(values["leq"], 1),
                    "peak_db": round(values["peak"], 1),
                    "limit_db_spl": None,
                    "limit_status": "uncalibrated",
                    "message": "Calibrate with a physical SPL reference before using this for compliance.",
                }

            spl_values = {key: calibration.to_spl(value) for key, value in values.items()}
            limit = calibration.limit_db_spl
            loudest = max(spl_values["slow"], spl_values["leq"], spl_values["peak"])
            if limit is None:
                limit_status = "not_set"
            elif loudest >= limit:
                limit_status = "exceeded"
            elif loudest >= limit - 3.0:
                limit_status = "approaching"
            else:
                limit_status = "within_limit"
            return {
                "calibrated": True,
                "compliance_ready": False,
                "unit": "dB SPL (Z)",
                "instant_db": round(spl_values["instant"], 1),
                "slow_db": round(spl_values["slow"], 1),
                "leq_db": round(spl_values["leq"], 1),
                "peak_db": round(spl_values["peak"], 1),
                "limit_db_spl": limit,
                "limit_status": limit_status,
                "reference_dbfs": round(calibration.reference_dbfs, 1),
                "reference_db_spl": round(calibration.reference_db_spl, 1),
                "message": "Calibrated unweighted SPL (Z). Use a certified Class 1/2 meter and required weighting for regulatory compliance.",
            }


def _power_to_db(power: float) -> float:
    return max(MIN_DBFS, 10.0 * math.log10(max(float(power), 10 ** (MIN_DBFS / 10.0))))


def third_octave_levels(
    frequencies: np.ndarray, magnitudes_db: np.ndarray
) -> list[dict[str, float]]:
    """Aggregate an FFT into a relative one-third-octave RTA trace.

    Values are summed band power in dBFS, not band SPL.  This keeps the trace
    useful for finding room-response peaks without making a false calibration
    claim from an arbitrary interface and microphone.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    magnitudes_db = np.asarray(magnitudes_db, dtype=np.float64)
    if frequencies.size != magnitudes_db.size:
        raise ValueError("frequencies and magnitudes_db must be aligned")

    half_band_ratio = 2 ** (1 / 6)
    result: list[dict[str, float]] = []
    for centre in THIRD_OCTAVE_CENTRES_HZ:
        lower, upper = centre / half_band_ratio, centre * half_band_ratio
        in_band = (frequencies >= lower) & (frequencies < upper)
        if not np.any(in_band):
            continue
        # Sum, rather than average, the FFT-bin power. Pink noise carries equal
        # energy in equal-ratio bands; averaging would impose a false LF tilt
        # and lead to incorrect room-EQ cuts.
        power = np.sum(np.power(10.0, magnitudes_db[in_band] / 10.0))
        result.append({"frequency_hz": float(centre), "level_dbfs": round(_power_to_db(power), 2)})
    return result


class RTAMeasurement:
    """Capture a bounded, pink-noise room measurement from the live input."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = "idle"
        self._duration_seconds = 15.0
        self._started_at: float | None = None
        self._frames = 0
        self._power_by_band: dict[float, float] = {}
        self._latest_bands: list[dict[str, float]] = []
        self._result: dict[str, Any] | None = None

    def start(self, duration_seconds: float = 15.0) -> dict[str, Any]:
        duration = float(duration_seconds)
        if not 5.0 <= duration <= 90.0:
            raise ValueError("duration_seconds must be between 5 and 90")
        with self._lock:
            if self._state == "measuring":
                raise RuntimeError("A room measurement is already in progress")
            self._state = "measuring"
            self._duration_seconds = duration
            self._started_at = time.monotonic()
            self._frames = 0
            self._power_by_band = {}
            self._result = None
            return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if self._state == "measuring":
                self._state = "cancelled"
            return self.snapshot()

    def update(self, frequencies: np.ndarray, magnitudes_db: np.ndarray) -> dict[str, Any]:
        bands = third_octave_levels(frequencies, magnitudes_db)
        now = time.monotonic()
        with self._lock:
            self._latest_bands = bands
            if self._state != "measuring":
                return self.snapshot()

            for band in bands:
                frequency = band["frequency_hz"]
                power = 10.0 ** (band["level_dbfs"] / 10.0)
                self._power_by_band[frequency] = self._power_by_band.get(frequency, 0.0) + power
            self._frames += 1
            started_at = self._started_at if self._started_at is not None else now
            if now - started_at >= self._duration_seconds:
                self._state = "complete"
                self._result = self._build_result()
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = max(0.0, time.monotonic() - self._started_at) if self._state == "measuring" and self._started_at else 0.0
            data: dict[str, Any] = {
                "state": self._state,
                "duration_seconds": self._duration_seconds,
                "elapsed_seconds": round(min(elapsed, self._duration_seconds), 1),
                "frames": self._frames,
                "latest_bands": self._latest_bands,
                "requires": [
                    "A calibrated omnidirectional measurement microphone",
                    "Pink noise routed through the PA at a safe level",
                    "An engineer review before any EQ is applied",
                ],
            }
            if self._result is not None:
                data["result"] = self._result
            return data

    def _build_result(self) -> dict[str, Any]:
        if not self._frames:
            return {"bands": [], "correction_eq": [], "message": "No audio frames were captured."}

        bands = [
            {
                "frequency_hz": frequency,
                "level_dbfs": round(_power_to_db(power / self._frames), 2),
            }
            for frequency, power in sorted(self._power_by_band.items())
        ]
        # Use a median target so the recommendation is a relative correction and
        # never manufactures a flat SPL curve from uncalibrated input levels.
        levels = np.array([band["level_dbfs"] for band in bands], dtype=np.float64)
        target = float(np.median(levels))
        corrections = []
        for band in bands:
            deviation = band["level_dbfs"] - target
            if deviation >= 3.0:
                corrections.append(
                    {
                        "frequency_hz": band["frequency_hz"],
                        "cut_db": round(-min(deviation, 6.0), 1),
                        "q": 4.3,
                        "reason": f"{deviation:.1f} dB above the measured median",
                    }
                )
        corrections.sort(key=lambda item: item["cut_db"])
        return {
            "bands": bands,
            "median_level_dbfs": round(target, 2),
            "flatness_range_db": round(float(np.max(levels) - np.min(levels)), 2),
            "correction_eq": corrections[:8],
            "message": "Relative 1/3-octave response. Review every cut before applying it to the PA.",
        }


def generate_pink_noise(
    sample_count: int,
    level_dbfs: float = -30.0,
    seed: int | None = None,
) -> np.ndarray:
    """Create a normalized mono pink-noise buffer suitable for safe playback."""
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    level = float(level_dbfs)
    if not -80.0 <= level <= -12.0:
        raise ValueError("level_dbfs must be between -80 and -12")
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(sample_count)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(sample_count)
    shaping = np.ones_like(frequencies)
    shaping[1:] = 1.0 / np.sqrt(frequencies[1:])
    shaping[0] = 0.0
    pink = np.fft.irfft(spectrum * shaping, n=sample_count)
    pink /= max(float(np.sqrt(np.mean(np.square(pink)))), np.finfo(float).eps)
    peak_safe_scale = min(10.0 ** (level / 20.0), 0.9 / max(float(np.max(np.abs(pink))), 1.0))
    return np.asarray(np.clip(pink * peak_safe_scale * FULL_SCALE_INT16, -32768, 32767), dtype=np.int16)
