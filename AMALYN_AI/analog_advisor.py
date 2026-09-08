"""analog_advisor.py — AMALYN Analog Mixer & Outboard Rack Advisory Engine.

Translates real-time audio FFT telemetry, Sentinel health stats, and feedback alerts
into tactile, actionable instructions for physical analog gear:
1. Analog Channel Strip & Preamp (Mackie, Yamaha MG, Soundcraft, A&H ZED)
2. Outboard 31-Band Graphic EQ (dbx 231, Klark Teknik, Yamaha Q2031)
3. Active Crossover & Loudspeaker Processor (dbx DriveRack, Behringer Super-X)
4. Power Amplifiers (Crown, QSC, Behringer, Yamaha)
5. Power Sequencer & AC Grounding (Furman, SurgeX, DI ground lifts)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np

# Standard ISO 266 1/3-octave center frequencies for 31-band graphic EQs
ISO_31_BANDS: List[float] = [
    20.0, 25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0,
    200.0, 250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0,
    1600.0, 2000.0, 2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0,
    10000.0, 12500.0, 16000.0, 20000.0
]


def format_frequency(hz: float) -> str:
    """Format frequency for clear console/rack reading."""
    if hz >= 1000:
        val = hz / 1000.0
        return f"{val:.2f}".rstrip("0").rstrip(".") + " kHz"
    return f"{int(round(hz))} Hz"


def format_iso_label(hz: float) -> str:
    """Standard faceplate label on a 31-band EQ."""
    if hz >= 1000:
        val = hz / 1000.0
        return f"{val:g}k"
    if hz == 31.5:
        return "31.5"
    return f"{int(round(hz))}"


def find_closest_iso_band(freq_hz: float) -> float:
    """Find the closest standard ISO 31-band center frequency using logarithmic distance."""
    if freq_hz <= 0:
        return 1000.0
    safe_freq = max(15.0, min(22000.0, float(freq_hz)))
    return min(ISO_31_BANDS, key=lambda b: abs(math.log2(safe_freq / b)))


def detect_mains_hum(frequencies: np.ndarray, magnitudes_db: np.ndarray) -> Optional[Dict[str, Any]]:
    """Detect 50 Hz (European/African/Asian standard) or 60 Hz (US standard) AC ground loop hum."""
    if len(frequencies) < 10 or len(magnitudes_db) < 10:
        return None

    # Check 50Hz and 60Hz bins
    for target_hum in (50.0, 60.0):
        idx = int(np.argmin(np.abs(frequencies - target_hum)))
        if idx <= 0 or idx >= len(magnitudes_db) - 1:
            continue
        hum_mag = float(magnitudes_db[idx])
        # Compare with surrounding local baseline (e.g. +/- 3 bins excluding the peak)
        left = max(0, idx - 3)
        right = min(len(magnitudes_db), idx + 4)
        local_env = [magnitudes_db[i] for i in range(left, right) if i != idx]
        if not local_env:
            continue
        avg_env = float(np.mean(local_env))
        prominence = hum_mag - avg_env

        # A noticeable hum is at least 7 dB prominent and louder than -45 dBFS
        if prominence >= 7.0 and hum_mag > -45.0:
            harmonic_target = target_hum * 2
            h_idx = int(np.argmin(np.abs(frequencies - harmonic_target)))
            has_harmonic = False
            if 0 < h_idx < len(magnitudes_db):
                has_harmonic = float(magnitudes_db[h_idx]) > (avg_env + 3.0)

            return {
                "hum_freq": target_hum,
                "prominence": round(prominence, 1),
                "magnitude": round(hum_mag, 1),
                "has_harmonic": has_harmonic,
                "standard": "50 Hz (UK/EU/Africa/Asia)" if target_hum == 50.0 else "60 Hz (US/Americas)"
            }
    return None


def generate_analog_advice(
    status: str,
    danger_freq: float,
    danger_mag: float,
    frequencies: Optional[np.ndarray] = None,
    magnitudes_db: Optional[np.ndarray] = None,
    sentinel_stats: Optional[Dict[str, Any]] = None,
    sentinel_alerts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Analyzes live DSP state and produces an actionable, prioritized hardware checklist
    specifically designed for analog mixing consoles, outboard racks, crossovers, and amps.
    """
    advice_list: List[Dict[str, Any]] = []
    sentinel_stats = sentinel_stats or {}
    sentinel_alerts = sentinel_alerts or []

    clip_rate = float(sentinel_stats.get("clip_rate", 0.0))
    rms = float(sentinel_stats.get("rms", 0.0))
    dropout_rate = float(sentinel_stats.get("dropout_rate", 0.0))
    noise_floor = float(sentinel_stats.get("noise_floor", -80.0))

    # Determine 31-band fader cuts
    active_iso_band: Optional[float] = None
    suggested_geq_cut = 0.0

    if status in ("WARNING", "CRITICAL") and danger_freq and danger_freq > 20:
        active_iso_band = find_closest_iso_band(danger_freq)
        excess = danger_mag - (-25.0)
        if excess <= 3:
            suggested_geq_cut = -3.0
        elif excess <= 6:
            suggested_geq_cut = -6.0
        elif excess <= 10:
            suggested_geq_cut = -9.0
        else:
            suggested_geq_cut = -12.0

    # -------------------------------------------------------------
    # 1. OUTBOARD 31-BAND GRAPHIC EQ ADVICE
    # -------------------------------------------------------------
    if active_iso_band is not None and suggested_geq_cut < 0:
        fader_label = format_iso_label(active_iso_band)
        advice_list.append({
            "id": "geq_notch",
            "category": "GEQ",
            "target_gear": "31-Band Graphic EQ Rack",
            "urgency": "CRITICAL" if status == "CRITICAL" else "WARNING",
            "title": f"Pull Down {fader_label} Fader ({format_frequency(active_iso_band)})",
            "action": f"Pull the {fader_label} slider down by {suggested_geq_cut:.0f} dB on the 31-band rack EQ",
            "detail": f"Feedback resonance identified near {format_frequency(danger_freq)} ({danger_mag:.1f} dBFS). Snapped to standard 1/3-octave ISO fader.",
            "target_param": f"{fader_label} fader",
            "value": f"{suggested_geq_cut:.0f} dB",
            "iso_hz": active_iso_band
        })

    # -------------------------------------------------------------
    # 2. ANALOG CONSOLE CHANNEL STRIP ADVICE
    # -------------------------------------------------------------
    # Low Cut (HPF) Check
    need_hpf = False
    if danger_freq and danger_freq <= 95 and status in ("WARNING", "CRITICAL"):
        need_hpf = True
    elif magnitudes_db is not None and frequencies is not None and len(frequencies) > 5:
        # Check if sub rumble (< 80 Hz) is disproportionately high
        sub_indices = np.where((frequencies >= 20) & (frequencies <= 80))[0]
        if len(sub_indices) > 0:
            sub_max = float(np.max(magnitudes_db[sub_indices]))
            if sub_max > -30.0:
                need_hpf = True

    if need_hpf:
        advice_list.append({
            "id": "console_hpf",
            "category": "CONSOLE",
            "target_gear": "Analog Channel Strip",
            "urgency": "WARNING",
            "title": "Engage 80 Hz Low-Cut (HPF) Button",
            "action": "Press the [80 Hz HPF / Low Cut] push-button IN on the vocal/mic channel",
            "detail": "Eliminates stage floor rumble, mic handling thumps, and protects PA subwoofers from unnecessary low-frequency excursion.",
            "target_param": "80 Hz Low-Cut Switch",
            "value": "ENGAGED"
        })

    # Preamp Gain Trim Back-off
    if clip_rate > 3.0 or rms > 0.8:
        advice_list.append({
            "id": "console_gain",
            "category": "CONSOLE",
            "target_gear": "Analog Channel Strip",
            "urgency": "CRITICAL",
            "title": "Back Off Analog Preamp Gain / Trim Pot",
            "action": "Rotate the channel [GAIN / TRIM] knob counter-clockwise by 2–3 notches (-4 to -6 dB)",
            "detail": f"Analog input is clipping ({clip_rate:.1f}% clipped samples). Backing down gain prevents harsh analog/digital distortion.",
            "target_param": "Gain / Trim Knob",
            "value": "-4 to -6 dB"
        })

    # Sweepable Mid EQ on Console
    sweep_target_khz: Optional[str] = None
    sweep_cut_db = 0.0
    if danger_freq and 250 <= danger_freq <= 6000 and status in ("WARNING", "CRITICAL"):
        sweep_target_khz = format_frequency(danger_freq)
        sweep_cut_db = suggested_geq_cut or -6.0
        advice_list.append({
            "id": "console_mid_sweep",
            "category": "CONSOLE",
            "target_gear": "Analog Channel Strip",
            "urgency": "WARNING" if status == "WARNING" else "CRITICAL",
            "title": f"Sweep Mid EQ Knob to {sweep_target_khz}",
            "action": f"Turn Mid-Freq pot to ~{sweep_target_khz} and cut Mid-Gain knob by {sweep_cut_db:.0f} dB",
            "detail": "Carves out the acoustic feedback spike directly at the channel strip preamp before it hits the master mix bus.",
            "target_param": "Sweepable Mid EQ",
            "value": f"{sweep_target_khz} / {sweep_cut_db:.0f} dB"
        })

    # -------------------------------------------------------------
    # 3. ACTIVE CROSSOVER & SPEAKER PROCESSOR ADVICE
    # -------------------------------------------------------------
    # Check for acoustic mud / crossover phase cancellation (110 Hz - 180 Hz)
    if danger_freq and 110 <= danger_freq <= 180:
        advice_list.append({
            "id": "crossover_mud",
            "category": "CROSSOVER",
            "target_gear": "Active Crossover / Speaker Processor",
            "urgency": "ADVISORY",
            "title": "Sub / Top Crossover Overlap & Mud (120–160 Hz)",
            "action": "Lower Subwoofer Low-Pass to 90–100 Hz or increase High-Pass cutoff on top cabinets",
            "detail": f"Buildup at {format_frequency(danger_freq)} indicates subs and mid-high tops are both outputting overlapping energy around the crossover point.",
            "target_param": "Crossover Frequency",
            "value": "90–100 Hz"
        })

    # Infrasonic Protection (< 35 Hz)
    if danger_freq and 20 <= danger_freq < 38:
        advice_list.append({
            "id": "crossover_infrasonic",
            "category": "CROSSOVER",
            "target_gear": "Active Crossover / Speaker Processor",
            "urgency": "WARNING",
            "title": "Enable Infrasonic High-Pass Filter (35 Hz)",
            "action": "Engage 30–35 Hz High-Pass filter on the crossover/subwoofer processor",
            "detail": "Frequencies below 35 Hz waste huge amplifier wattage and cause speaker cone over-excursion without producing audible bass.",
            "target_param": "Sub Infrasonic Cut",
            "value": "35 Hz HPF"
        })

    # -------------------------------------------------------------
    # 4. POWER AMPLIFIERS ADVICE
    # -------------------------------------------------------------
    if clip_rate > 5.0 or (status == "CRITICAL" and danger_mag > -10.0):
        advice_list.append({
            "id": "amp_attenuator",
            "category": "AMP",
            "target_gear": "Power Amplifier Rack",
            "urgency": "CRITICAL",
            "title": "Turn Down Power Amp Attenuators by 3 dB",
            "action": "Back off the power amp front-panel attenuator knobs from 0 dB to -3 dB",
            "detail": "High-frequency feedback or clipping risks burning out horn compression driver voice coils. Protect power amp output stages.",
            "target_param": "Amp Attenuator Knobs",
            "value": "-3 dB"
        })

    # Sentinel Cable / Connection alert translated to amp patchbay
    for alert in sentinel_alerts:
        if alert.get("type") in ("CABLE_FAILURE", "DROPOUT") and alert.get("severity") == "CRITICAL":
            advice_list.append({
                "id": "amp_cabling",
                "category": "AMP",
                "target_gear": "Power Amp Rack / Speaker Cabling",
                "urgency": "CRITICAL",
                "title": "Check speakON Locking Connectors & Speaker Lines",
                "action": "Verify speakON twists on amp outputs and speaker cabinet jacks; check amplifier stereo/bridge mode switch",
                "detail": "Rapid signal dropouts detected. Indicates loose speakON collar, vibrating terminal, or pinched speaker cable.",
                "target_param": "Speaker Cabling & Jacks",
                "value": "Inspect Connections"
            })
            break

    # -------------------------------------------------------------
    # 5. POWER SEQUENCER & GROUNDING ADVICE (50/60 Hz Hum)
    # -------------------------------------------------------------
    if frequencies is not None and magnitudes_db is not None:
        hum_data = detect_mains_hum(frequencies, magnitudes_db)
        if hum_data:
            hum_freq = hum_data["hum_freq"]
            advice_list.append({
                "id": "power_ground_hum",
                "category": "POWER_RACK",
                "target_gear": "Power Sequencer / DI Ground Lifts",
                "urgency": "WARNING",
                "title": f"Mains AC Ground Loop Detected ({hum_freq:.0f} Hz)",
                "action": f"Flip the [GROUND LIFT] switch on stage direct boxes (DIs), or power all FOH & backline gear from the same power sequencer",
                "detail": f"Distinct {hum_freq:.0f} Hz AC cycle hum ({hum_data['prominence']:.1f} dB prominence) indicates ground potential difference between mixer and stage equipment.",
                "target_param": "DI Ground Lift & AC Power Phase",
                "value": "LIFT GROUND"
            })

    # -------------------------------------------------------------
    # 6. OUTBOARD DYNAMICS / COMPRESSOR RACK ADVICE
    # -------------------------------------------------------------
    if clip_rate > 2.0 and status != "CRITICAL":
        advice_list.append({
            "id": "dynamics_compression",
            "category": "DYNAMICS",
            "target_gear": "Outboard Compressor / Limiter Rack",
            "urgency": "ADVISORY",
            "title": "Insert Rack Compressor on Vocal / Main Bus",
            "action": "Set rack compressor to 3:1 Ratio, Medium Attack (20 ms), and adjust Threshold until 3–6 dB gain reduction shows on peaks",
            "detail": "Tames wild dynamic vocal swings or slap bass transients before they overdrive the analog mixing console summing bus.",
            "target_param": "Compressor Ratio & Threshold",
            "value": "3:1 Ratio / -4 dB"
        })

    # Sort advice by urgency: CRITICAL > WARNING > ADVISORY
    urgency_weights = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
    advice_list.sort(key=lambda item: urgency_weights.get(item.get("urgency", "ADVISORY"), 3))

    # Construct the 31-band faders representation
    geq_faders = []
    for band_hz in ISO_31_BANDS:
        is_active = (active_iso_band == band_hz)
        fader_cut = suggested_geq_cut if is_active else 0.0
        geq_faders.append({
            "freq": band_hz,
            "label": format_iso_label(band_hz),
            "formatted": format_frequency(band_hz),
            "cut_db": fader_cut,
            "is_active": is_active,
            "urgency": status if is_active else "CLEAN"
        })

    # Channel strip virtual knobs representation
    channel_strip = {
        "hpf_80hz": need_hpf,
        "gain_trim_cut_db": -5.0 if (clip_rate > 3.0 or rms > 0.8) else 0.0,
        "mid_freq_hz": round(danger_freq, 1) if (danger_freq and 250 <= danger_freq <= 6000) else None,
        "mid_freq_label": sweep_target_khz or "Flat (1 kHz)",
        "mid_cut_db": sweep_cut_db,
        "high_shelf_db": -3.0 if (danger_freq and danger_freq > 8000 and status in ("WARNING", "CRITICAL")) else 0.0,
        "low_shelf_db": -3.0 if (danger_freq and 80 < danger_freq < 250 and status in ("WARNING", "CRITICAL")) else 0.0,
        "fader_db": -10.0 if (status == "CRITICAL" and danger_mag > -10.0) else 0.0
    }

    # Outboard Rack Unit Summary
    rack_status = {
        "geq": {
            "status": "NOTCH_ACTIVE" if active_iso_band else "NOMINAL",
            "active_band": format_frequency(active_iso_band) if active_iso_band else None,
            "cut_db": suggested_geq_cut
        },
        "console": {
            "status": "ACTION_REQUIRED" if (need_hpf or sweep_cut_db < 0 or clip_rate > 3.0) else "NOMINAL",
            "hpf": "ENGAGE" if need_hpf else "BYPASS",
            "gain": "REDUCE" if clip_rate > 3.0 else "NOMINAL"
        },
        "crossover": {
            "status": "CHECK_POINT" if (danger_freq and 110 <= danger_freq <= 180) else "OPTIMAL",
            "sub_hpf": "ENGAGE_35HZ" if (danger_freq and 20 <= danger_freq < 38) else "NOMINAL"
        },
        "power_amps": {
            "status": "ATTENUATE" if (clip_rate > 5.0 or (status == "CRITICAL" and danger_mag > -10.0)) else "SAFE",
            "headroom": "LOW" if clip_rate > 2.0 else "GOOD"
        },
        "power_sequencer": {
            "status": "GROUND_HUM_DETECTED" if any(a["id"] == "power_ground_hum" for a in advice_list) else "CLEAN",
            "ground_lift": "ENGAGE" if any(a["id"] == "power_ground_hum" for a in advice_list) else "NORMAL"
        }
    }

    primary_advice = advice_list[0] if advice_list else None

    return {
        "summary": {
            "status": status,
            "total_actions": len(advice_list),
            "primary_action": primary_advice["action"] if primary_advice else "All analog hardware settings nominal",
            "primary_gear": primary_advice["target_gear"] if primary_advice else "System Clean",
            "urgency": primary_advice["urgency"] if primary_advice else "CLEAN"
        },
        "advice_list": advice_list,
        "geq_faders": geq_faders,
        "channel_strip": channel_strip,
        "rack_status": rack_status
    }
