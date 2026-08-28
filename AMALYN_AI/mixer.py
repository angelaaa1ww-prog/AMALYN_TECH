# mixer.py — AMALYN Mixer Integration via OSC

import threading

try:
    from pythonosc import udp_client
except ImportError:
    udp_client = None

# --- MIXER PROFILES ---
# Each mixer brand uses different OSC address patterns
MIXER_PROFILES = {
    "behringer_x32": {
        "name": "Behringer X32/M32",
        "ip": "192.168.1.100",
        "port": 10023,
        "eq_address": "/ch/{channel:02d}/eq/{band}/g",
        "eq_freq_address": "/ch/{channel:02d}/eq/{band}/f",
        "eq_q_address": "/ch/{channel:02d}/eq/{band}/q",
        "gain_address": "/ch/{channel:02d}/mix/fader",
        "bands": {
            "low": 1, "low_mid": 2, "high_mid": 3, "high": 4
        }
    },
    "yamaha_cl": {
        "name": "Yamaha CL/QL Series",
        "ip": "192.168.1.101",
        "port": 10300,
        "eq_address": "/Node/MIXER:Current/InCh/Fader/{channel}/EQ/Band/{band}/Gain",
        "eq_freq_address": "/Node/MIXER:Current/InCh/Fader/{channel}/EQ/Band/{band}/Freq",
        "eq_q_address": "/Node/MIXER:Current/InCh/Fader/{channel}/EQ/Band/{band}/Q",
        "gain_address": "/Node/MIXER:Current/InCh/Fader/{channel}/Fader/Level",
        "bands": {
            "low": 1, "low_mid": 2, "high_mid": 3, "high": 4
        }
    },
    "allen_heath_sq": {
        "name": "Allen & Heath SQ/dLive",
        "ip": "192.168.1.102",
        "port": 51325,
        "eq_address": "/amxd@{channel}/eq/{band}/gain",
        "eq_freq_address": "/amxd@{channel}/eq/{band}/freq",
        "eq_q_address": "/amxd@{channel}/eq/{band}/q",
        "gain_address": "/amxd@{channel}/fader",
        "bands": {
            "low": 1, "low_mid": 2, "high_mid": 3, "high": 4
        }
    },
    "simulator": {
        "name": "AMALYN Simulator",
        "ip": "127.0.0.1",
        "port": 9000,
        "eq_address": "/ch/{channel:02d}/eq/{band}/g",
        "eq_freq_address": "/ch/{channel:02d}/eq/{band}/f",
        "eq_q_address": "/ch/{channel:02d}/eq/{band}/q",
        "gain_address": "/ch/{channel:02d}/mix/fader",
        "bands": {
            "low": 1, "low_mid": 2, "high_mid": 3, "high": 4
        }
    }
}


def get_eq_band_index(band_name, profile):
    """Map AMALYN band names to mixer band numbers."""
    mapping = {
        "Sub Bass": "low",
        "Bass": "low",
        "Low Mid": "low_mid",
        "Mid": "low_mid",
        "High Mid": "high_mid",
        "Presence": "high",
        "Air": "high"
    }
    key = mapping.get(band_name, "high_mid")
    return profile["bands"][key]


class AmalynMixerBridge:
    """
    Bridges AMALYN AI engine to a real mixer via OSC.
    Supports Behringer X32, Yamaha CL/QL, Allen & Heath SQ,
    and a built-in simulator for testing.
    """

    def __init__(self, mixer_type="simulator", channel=1):
        if mixer_type not in MIXER_PROFILES:
            supported = ", ".join(sorted(MIXER_PROFILES))
            raise ValueError(f"Unknown mixer type '{mixer_type}'. Supported: {supported}")
        if channel < 1:
            raise ValueError("channel must be at least 1")

        self.profile = MIXER_PROFILES[mixer_type]
        self.channel = channel
        self.mixer_type = mixer_type
        self.connected = False
        self.client = None
        self.corrections_sent = []
        self._corrections_lock = threading.Lock()

        print(f"\n[MIXER] Initializing: {self.profile['name']}")
        print(f"[MIXER] Target IP: {self.profile['ip']}:{self.profile['port']}")
        print(f"[MIXER] Channel: {self.channel}")

    def connect(self):
        """Connect to the mixer via OSC."""
        if udp_client is None:
            print("[MIXER] python-osc is not installed; mixer control is disabled")
            return False
        try:
            self.client = udp_client.SimpleUDPClient(
                self.profile["ip"],
                self.profile["port"]
            )
            self.connected = True
            print(f"[MIXER] Connected to {self.profile['name']}")
            return True
        except Exception as e:
            print(f"[MIXER] Connection failed: {e}")
            return False

    def send_eq_correction(self, suggestion):
        """
        Takes an EQ suggestion from AMALYN
        and sends OSC commands to the mixer.
        """
        if not self.connected or not self.client:
            print("[MIXER] Not connected — cannot send correction")
            return False

        if not suggestion:
            return False

        try:
            band_index = get_eq_band_index(
                suggestion["band_name"], self.profile
            )

            # Build OSC addresses
            gain_addr = self.profile["eq_address"].format(
                channel=self.channel, band=band_index
            )
            freq_addr = self.profile["eq_freq_address"].format(
                channel=self.channel, band=band_index
            )
            q_addr = self.profile["eq_q_address"].format(
                channel=self.channel, band=band_index
            )

            # Send frequency
            self.client.send_message(freq_addr, float(suggestion["frequency"]))

            # Send gain cut
            self.client.send_message(gain_addr, float(suggestion["cut_db"]))

            # Send Q value
            self.client.send_message(q_addr, float(suggestion["q_value"]))

            # Log the correction
            correction = {
                "frequency": suggestion["frequency"],
                "cut_db": suggestion["cut_db"],
                "band": suggestion["band_name"],
                "q": suggestion["q_value"],
                "channel": self.channel,
                "mixer": self.profile["name"]
            }
            with self._corrections_lock:
                self.corrections_sent.append(correction)
                if len(self.corrections_sent) > 100:
                    self.corrections_sent = self.corrections_sent[-100:]

            print(f"\n[MIXER] Correction sent to {self.profile['name']}")
            print(f"[MIXER] Channel {self.channel} | {suggestion['frequency']}Hz | {suggestion['cut_db']}dB | Q:{suggestion['q_value']}")

            return True

        except Exception as e:
            print(f"[MIXER] Send failed: {e}")
            return False

    def send_safe_profile(self):
        """
        Emergency safe state — flatten EQ on this channel
        if a critical failure is detected.
        """
        if not self.connected or not self.client:
            return False

        try:
            print(f"\n[MIXER] EMERGENCY — Applying Safe Profile to Channel {self.channel}")
            for band_index in range(1, 5):
                gain_addr = self.profile["eq_address"].format(
                    channel=self.channel, band=band_index
                )
                self.client.send_message(gain_addr, 0.0)
            print(f"[MIXER] Safe profile applied — all EQ bands reset to 0dB")
            return True
        except Exception as error:
            print(f"[MIXER] Safe profile failed: {error}")
            return False

    def get_corrections_summary(self):
        """Returns a summary of all corrections sent this session."""
        with self._corrections_lock:
            corrections = [correction.copy() for correction in self.corrections_sent]
        return {"total_corrections": len(corrections), "corrections": corrections}

    def disconnect(self):
        self.connected = False
        self.client = None
        print(f"[MIXER] Disconnected from {self.profile['name']}")
