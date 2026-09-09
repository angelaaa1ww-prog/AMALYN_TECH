"""test_analog_manager.py — Unit tests for USB Analog Mixer Auto-Identification and Custom Model Management."""

import unittest
import os
import json
from analog_manager import AnalogMixerManager


class TestAnalogMixerManager(unittest.TestCase):
    def setUp(self):
        self.mgr = AnalogMixerManager()

    def test_builtin_mixers_loaded(self):
        all_mixers = self.mgr.get_all_mixers()
        self.assertIn("yamaha_mg", all_mixers)
        self.assertIn("mackie_profx", all_mixers)
        self.assertIn("behringer_xenyx", all_mixers)
        self.assertIn("allen_heath_zed", all_mixers)
        self.assertIn("soundcraft_signature", all_mixers)
        self.assertIn("focusrite_scarlett", all_mixers)
        self.assertIn("generic_analog", all_mixers)

    def test_usb_device_pattern_matching(self):
        # Yamaha MG
        mixer, conf, reason = self.mgr.match_device_to_mixer("Line (MG-XU)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "yamaha_mg")
        self.assertGreaterEqual(conf, 90.0)

        # Mackie ProFX
        mixer, conf, reason = self.mgr.match_device_to_mixer("Line (PROFX)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "mackie_profx")
        self.assertGreaterEqual(conf, 90.0)

        # Behringer Xenyx
        mixer, conf, reason = self.mgr.match_device_to_mixer("Microphone (XENYX 302USB)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "behringer_xenyx")
        self.assertGreaterEqual(conf, 90.0)

        # Focusrite Scarlett
        mixer, conf, reason = self.mgr.match_device_to_mixer("Focusrite USB Audio (Scarlett 2i2 USB)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "focusrite_scarlett")
        self.assertGreaterEqual(conf, 90.0)

        # Generic USB Audio CODEC fallback
        mixer, conf, reason = self.mgr.match_device_to_mixer("Microphone (USB Audio CODEC)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "generic_analog")

    def test_custom_mixer_lifecycle(self):
        custom_data = {
            "key": "test_midas_venice",
            "brand": "Midas",
            "model": "Venice F32",
            "usb_keywords": ["venice", "midas f32"],
            "specs": {
                "hpf_freq": 80,
                "has_sweep_mid": True,
                "mid_sweep_min": 100,
                "mid_sweep_max": 8000
            }
        }
        success, msg, entry = self.mgr.add_custom_mixer(custom_data)
        self.assertTrue(success)
        self.assertIsNotNone(entry)
        self.assertIn("test_midas_venice", self.mgr.get_all_mixers())

        # Test matching against custom keyword
        mixer, conf, reason = self.mgr.match_device_to_mixer("Line Out (Midas Venice F32 USB)")
        self.assertIsNotNone(mixer)
        self.assertEqual(mixer["key"], "test_midas_venice")

        # Cleanup
        del_success, del_msg = self.mgr.delete_custom_mixer("test_midas_venice")
        self.assertTrue(del_success)
        self.assertNotIn("test_midas_venice", self.mgr.get_all_mixers())

    def test_device_mapping_override(self):
        # Suppose Windows calls an analog desk generic "USB Audio CODEC"
        # User maps it to Soundcraft Signature
        generic_name = "Microphone (USB Audio CODEC)"
        success, msg = self.mgr.map_device_to_mixer(generic_name, "soundcraft_signature")
        self.assertTrue(success)

        # Matching should now return soundcraft_signature with 100% confidence
        mixer, conf, reason = self.mgr.match_device_to_mixer(generic_name)
        self.assertEqual(mixer["key"], "soundcraft_signature")
        self.assertEqual(conf, 100.0)

        # Cleanup mapping
        if generic_name in self.mgr.device_mappings:
            del self.mgr.device_mappings[generic_name]
            from analog_manager import _write_json, DEVICE_MAPPINGS_PATH
            _write_json(DEVICE_MAPPINGS_PATH, self.mgr.device_mappings)


if __name__ == "__main__":
    unittest.main()
