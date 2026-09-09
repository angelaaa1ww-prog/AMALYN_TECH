"""analog_manager.py — AMALYN Universal Analog Mixer & USB Device Manager.

Handles:
1. Enumeration of connected USB audio input devices.
2. Pattern-matching against built-in and custom analog mixer profiles.
3. User persistence for custom mixer brands/models (custom_mixers.json).
4. Permanent mapping of generic USB audio descriptors to specific mixers (device_mappings.json).
5. Dynamic distribution of mixer hardware specs (HPF frequency, sweepable mid range) to the advisor engine.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
PROFILES_PATH = os.path.join(BASE_DIR, "analog_profiles.json")
CUSTOM_MIXERS_PATH = os.path.join(BASE_DIR, "custom_mixers.json")
DEVICE_MAPPINGS_PATH = os.path.join(BASE_DIR, "device_mappings.json")


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[ANALOG_MGR] Failed to read %s: %e", path, e)
        return default


def _write_json(path: str, data: Any) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error("[ANALOG_MGR] Failed to write %s: %s", path, e)
        return False


class AnalogMixerManager:
    """Manages analog mixer discovery, profiles, custom user models, and active device state."""

    def __init__(self) -> None:
        self.builtin_mixers: Dict[str, Any] = {}
        self.custom_mixers: Dict[str, Any] = {}
        self.device_mappings: Dict[str, str] = {}
        self.active_mixer_key: str = "generic_analog"
        self.active_device_name: Optional[str] = None
        self.is_manual_selection: bool = False
        self.reload_profiles()

    def reload_profiles(self) -> None:
        """Reload built-in profiles, custom models, and device mappings."""
        raw_profiles = _read_json(PROFILES_PATH, {"builtin_mixers": {}})
        self.builtin_mixers = raw_profiles.get("builtin_mixers", {})
        self.custom_mixers = _read_json(CUSTOM_MIXERS_PATH, {})
        self.device_mappings = _read_json(DEVICE_MAPPINGS_PATH, {})

    def get_all_mixers(self) -> Dict[str, Any]:
        """Return combined dict of all built-in and user-defined custom mixers."""
        combined = dict(self.builtin_mixers)
        for key, custom in self.custom_mixers.items():
            custom_entry = dict(custom)
            custom_entry["is_custom"] = True
            combined[key] = custom_entry
        return combined

    def get_mixer(self, mixer_key: str) -> Optional[Dict[str, Any]]:
        """Look up a mixer by key from custom or built-in databases."""
        if mixer_key in self.custom_mixers:
            mixer = dict(self.custom_mixers[mixer_key])
            mixer["is_custom"] = True
            return mixer
        if mixer_key in self.builtin_mixers:
            mixer = dict(self.builtin_mixers[mixer_key])
            mixer["is_custom"] = False
            return mixer
        return None

    def get_active_mixer(self) -> Dict[str, Any]:
        """Return the currently selected or auto-detected mixer with full specs."""
        mixer = self.get_mixer(self.active_mixer_key)
        if not mixer:
            mixer = self.builtin_mixers.get("generic_analog", {
                "key": "generic_analog",
                "brand": "Universal Analog",
                "model": "Standard Analog Mixing Console",
                "specs": {
                    "hpf_freq": 80,
                    "hpf_label": "80 Hz",
                    "has_sweep_mid": True,
                    "mid_sweep_min": 100,
                    "mid_sweep_max": 8000
                }
            })
        result = dict(mixer)
        result["active_device_name"] = self.active_device_name
        result["is_manual_selection"] = self.is_manual_selection
        return result

    def set_active_mixer(self, mixer_key: str, device_name: Optional[str] = None, manual: bool = True) -> bool:
        """Manually or automatically set the active mixer profile."""
        if mixer_key not in self.get_all_mixers():
            return False
        self.active_mixer_key = mixer_key
        if device_name is not None:
            self.active_device_name = device_name
        self.is_manual_selection = manual
        logger.info("[ANALOG_MGR] Active analog mixer set to %s (Device: %s, Manual: %s)",
                    mixer_key, self.active_device_name, manual)
        return True

    def get_connected_audio_devices(self) -> List[Dict[str, Any]]:
        """List all audio input devices detected by the operating system."""
        devices = []
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        devices.append({
                            "index": i,
                            "name": info.get("name", f"Audio Device {i}"),
                            "channels": info.get("maxInputChannels", 1),
                            "sample_rate": int(info.get("defaultSampleRate", 44100)),
                            "is_usb": self._is_likely_usb(info.get("name", ""))
                        })
                except Exception:
                    continue
            p.terminate()
        except (ImportError, Exception) as err:
            logger.warning("[ANALOG_MGR] PyAudio enumeration unavailable: %s", err)
        return devices

    def _is_likely_usb(self, name: str) -> bool:
        """Heuristic check whether an audio device descriptor refers to a USB/external unit."""
        lower = name.lower()
        # Common USB terms
        indicators = ["usb", "codec", "mg-xu", "profx", "xenyx", "zed", "scarlett",
                      "u-phoria", "umc", "audiobox", "line (", "external", "capture"]
        # Internal sound card markers
        internal_markers = ["realtek", "intel® smart sound", "internal", "stereo mix"]
        if any(marker in lower for marker in internal_markers):
            return False
        return any(ind in lower for marker in indicators if ind in lower)

    def match_device_to_mixer(self, device_name: str) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """
        Pattern-match a USB device descriptor against known mixer profiles.
        Returns (matched_mixer_dict, confidence_pct, match_reason).
        """
        if not device_name:
            return None, 0.0, "Empty device name"

        name_lower = device_name.lower().strip()

        # 1. User custom mapping check (100% confidence)
        if device_name in self.device_mappings:
            mapped_key = self.device_mappings[device_name]
            mixer = self.get_mixer(mapped_key)
            if mixer:
                return mixer, 100.0, f"User-mapped device '{device_name}'"

        all_mixers = self.get_all_mixers()

        # 2. Check exact keyword matches in custom and built-in profiles
        best_match = None
        highest_score = 0.0
        match_reason = "No match"

        for key, mixer in all_mixers.items():
            keywords = mixer.get("usb_keywords", [])
            for kw in keywords:
                kw_lower = kw.lower().strip()
                if not kw_lower:
                    continue

                # Exact or substring match
                if kw_lower in name_lower:
                    # Longer keyword matches are generally more specific
                    score = 75.0 + min(20.0, len(kw_lower) * 2.0)
                    # Boost for high-specificity keywords
                    if kw_lower in ("mg-xu", "mg10xu", "mg12xu", "mg16xu", "profx", "xenyx", "zedi", "signature", "scarlett"):
                        score = max(score, 95.0)

                    if score > highest_score:
                        highest_score = score
                        best_match = mixer
                        match_reason = f"Matched keyword '{kw}' in device name"

        if best_match:
            return best_match, round(highest_score, 1), match_reason

        # 3. Fallback: Generic USB CODEC detection
        if "usb audio codec" in name_lower or "usb audio" in name_lower or "codec" in name_lower:
            generic = self.builtin_mixers.get("generic_analog")
            return generic, 65.0, "Generic USB Audio CODEC identified"

        return None, 0.0, "Unrecognized device"

    def scan_usb_mixers(self) -> Dict[str, Any]:
        """
        Scans all connected audio input devices, identifies matching mixers,
        and optionally auto-engages high-confidence matches.
        """
        self.reload_profiles()
        devices = self.get_connected_audio_devices()
        scanned_results = []
        auto_selected = None

        for dev in devices:
            matched_mixer, confidence, reason = self.match_device_to_mixer(dev["name"])
            dev_entry = {
                "device_index": dev["index"],
                "device_name": dev["name"],
                "is_usb": dev["is_usb"],
                "channels": dev["channels"],
                "sample_rate": dev["sample_rate"],
                "matched_mixer": matched_mixer,
                "confidence": confidence,
                "match_reason": reason
            }
            scanned_results.append(dev_entry)

            # Auto-assign if confidence >= 80% and not manually overridden
            if not self.is_manual_selection and confidence >= 80.0 and auto_selected is None:
                auto_selected = matched_mixer
                self.active_mixer_key = matched_mixer["key"]
                self.active_device_name = dev["name"]

        return {
            "devices": scanned_results,
            "total_detected": len(devices),
            "active_mixer": self.get_active_mixer(),
            "auto_detected": auto_selected is not None
        }

    def add_custom_mixer(self, mixer_data: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Add or update a custom user-defined analog mixer model.
        Persisted to custom_mixers.json.
        """
        brand = str(mixer_data.get("brand", "")).strip()
        model = str(mixer_data.get("model", "")).strip()
        if not brand or not model:
            return False, "Brand and Model name are required", None

        # Generate a clean key
        key = mixer_data.get("key")
        if not key:
            raw_key = f"custom_{brand}_{model}".lower()
            key = re.sub(r"[^a-z0-9_]+", "_", raw_key).strip("_")

        # Normalize specs
        raw_specs = mixer_data.get("specs", {})
        hpf_freq = int(raw_specs.get("hpf_freq", 80))
        specs = {
            "hpf_freq": hpf_freq,
            "hpf_label": f"{hpf_freq} Hz",
            "has_sweep_mid": bool(raw_specs.get("has_sweep_mid", True)),
            "mid_sweep_min": int(raw_specs.get("mid_sweep_min", 100)),
            "mid_sweep_max": int(raw_specs.get("mid_sweep_max", 8000)),
            "high_shelf_freq": int(raw_specs.get("high_shelf_freq", 12000)),
            "low_shelf_freq": int(raw_specs.get("low_shelf_freq", 80)),
            "compressor": str(raw_specs.get("compressor", "Analog Outboard")),
            "preamp_headroom_db": int(raw_specs.get("preamp_headroom_db", 22)),
            "nominal_output_dbu": int(raw_specs.get("nominal_output_dbu", 4))
        }

        # Gather keywords
        keywords = mixer_data.get("usb_keywords", [])
        if not keywords:
            keywords = [brand.lower(), model.lower()]
        else:
            keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]

        entry = {
            "key": key,
            "brand": brand,
            "model": model,
            "category": mixer_data.get("category", "ANALOG_MIXER"),
            "connection_type": mixer_data.get("connection_type", "USB_AUDIO"),
            "usb_keywords": keywords,
            "specs": specs,
            "description": mixer_data.get("description", f"User-added {brand} {model} analog console."),
            "is_custom": True
        }

        self.custom_mixers[key] = entry
        success = _write_json(CUSTOM_MIXERS_PATH, self.custom_mixers)
        if not success:
            return False, "Failed to save custom mixer to disk", None

        logger.info("[ANALOG_MGR] Saved custom mixer %s (%s %s)", key, brand, model)
        return True, "Custom mixer saved successfully", entry

    def delete_custom_mixer(self, mixer_key: str) -> Tuple[bool, str]:
        """Delete a custom user-defined analog mixer model."""
        if mixer_key not in self.custom_mixers:
            return False, f"Custom mixer '{mixer_key}' not found"

        del self.custom_mixers[mixer_key]
        _write_json(CUSTOM_MIXERS_PATH, self.custom_mixers)

        # Reset active mixer if deleted
        if self.active_mixer_key == mixer_key:
            self.active_mixer_key = "generic_analog"
            self.is_manual_selection = False

        return True, f"Custom mixer '{mixer_key}' deleted"

    def map_device_to_mixer(self, device_name: str, mixer_key: str) -> Tuple[bool, str]:
        """
        Permanently map a USB device name to a specific mixer profile.
        Saved in device_mappings.json.
        """
        if not device_name:
            return False, "Device name cannot be empty"
        if mixer_key not in self.get_all_mixers():
            return False, f"Mixer profile '{mixer_key}' not found"

        self.device_mappings[device_name] = mixer_key
        _write_json(DEVICE_MAPPINGS_PATH, self.device_mappings)

        # Set as active mixer immediately
        self.set_active_mixer(mixer_key, device_name=device_name, manual=True)
        return True, f"Device '{device_name}' permanently mapped to '{mixer_key}'"


# Global singleton instance
analog_manager = AnalogMixerManager()
