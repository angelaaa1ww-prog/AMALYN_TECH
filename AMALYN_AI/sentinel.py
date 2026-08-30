# sentinel.py — AMALYN Sentinel: Predictive Healing & Hardware Monitor

import numpy as np
from collections import deque
from datetime import datetime


class AmalynSentinel:
    """
    AMALYN Sentinel monitors signal health in real time.
    Predicts hardware failures before they cause audio blackouts.
    """

    def __init__(self, history_size=100):
        # Rolling history buffers
        self.rms_history = deque(maxlen=history_size)
        self.clip_history = deque(maxlen=history_size)
        self.noise_history = deque(maxlen=history_size)
        self.dropout_history = deque(maxlen=history_size)

        # Thresholds
        self.CLIP_THRESHOLD = 0.95        # 95% of max amplitude = clipping
        self.DROPOUT_THRESHOLD = 0.001    # RMS below this = signal dropout
        self.NOISE_FLOOR_BASELINE = None  # Set on first run
        self.NOISE_FLOOR_RISE_DB = 6      # 6dB rise = interference detected
        self.VARIANCE_THRESHOLD = 15.0    # High variance = unstable signal

        # Event tracking
        self.events = []
        self.last_alert = None
        self.alert_cooldown = 50          # frames between same alert

        # Frame counter
        self.frame_count = 0

        print("[SENTINEL] Initialized — monitoring signal health")

    def analyze(self, audio_data, magnitudes_db):
        """
        Main analysis function — call every frame.
        Returns a list of health alerts.
        """
        self.frame_count += 1
        alerts = []

        # Normalize audio to float -1 to 1
        audio_float = audio_data / 32768.0

        # 1. Calculate RMS (volume level)
        rms = float(np.sqrt(np.mean(audio_float ** 2)))
        self.rms_history.append(rms)

        # 2. Check for clipping
        clip_ratio = float(np.mean(np.abs(audio_float) > self.CLIP_THRESHOLD))
        self.clip_history.append(clip_ratio)

        # 3. Check noise floor
        noise_floor = float(np.percentile(np.abs(magnitudes_db), 10))
        self.noise_history.append(noise_floor)

        # 4. Check for dropout
        is_dropout = rms < self.DROPOUT_THRESHOLD
        self.dropout_history.append(1 if is_dropout else 0)

        # Set baseline noise floor on first 50 frames
        if self.frame_count == 50:
            self.NOISE_FLOOR_BASELINE = float(np.mean(list(self.noise_history)))
            print(f"[SENTINEL] Noise floor baseline set: {self.NOISE_FLOOR_BASELINE:.1f}dB")

        # Only start alerting after baseline is set
        if len(self.rms_history) < 20:
            return alerts, self._get_health_score()

        # --- ALERT CHECKS ---

        # A. Clipping Alert
        recent_clips = list(self.clip_history)[-20:]
        avg_clip = float(np.mean(recent_clips))
        if avg_clip > 0.05:  # More than 5% of samples clipping
            alerts.append({
                "type": "CLIPPING",
                "severity": "CRITICAL" if avg_clip > 0.15 else "WARNING",
                "message": f"Clipping detected — {avg_clip*100:.0f}% of samples distorted",
                "action": "Reduce input gain immediately",
                "value": round(avg_clip * 100, 1)
            })

        # B. Signal Dropout Alert
        recent_dropouts = list(self.dropout_history)[-20:]
        dropout_rate = float(np.mean(recent_dropouts))
        if dropout_rate > 0.1:  # 10% dropout rate
            alerts.append({
                "type": "DROPOUT",
                "severity": "CRITICAL" if dropout_rate > 0.3 else "WARNING",
                "message": f"Signal dropout detected — {dropout_rate*100:.0f}% signal loss",
                "action": "Check cable connections and mic",
                "value": round(dropout_rate * 100, 1)
            })

        # C. Noise Floor Rise Alert
        if self.NOISE_FLOOR_BASELINE is not None:
            current_noise = float(np.mean(list(self.noise_history)[-10:]))
            noise_rise = current_noise - self.NOISE_FLOOR_BASELINE
            if noise_rise > self.NOISE_FLOOR_RISE_DB:
                alerts.append({
                    "type": "INTERFERENCE",
                    "severity": "WARNING",
                    "message": f"Noise floor risen {noise_rise:.1f}dB — interference detected",
                    "action": "Check for ground loop or RF interference",
                    "value": round(noise_rise, 1)
                })

        # D. Signal Instability Alert
        if len(self.rms_history) >= 30:
            recent_rms = list(self.rms_history)[-30:]
            variance = float(np.var(recent_rms) * 10000)
            if variance > self.VARIANCE_THRESHOLD and float(np.mean(recent_rms)) > 0.01:
                alerts.append({
                    "type": "INSTABILITY",
                    "severity": "WARNING",
                    "message": f"Signal instability detected — variance: {variance:.1f}",
                    "action": "Check cable integrity and connector joints",
                    "value": round(variance, 1)
                })

        # E. Predictive Cable Failure
        # Pattern: signal drops repeatedly over short time = failing cable
        if len(self.rms_history) >= 50:
            rms_list = list(self.rms_history)[-50:]
            dips = sum(1 for i in range(1, len(rms_list))
                      if rms_list[i] < rms_list[i-1] * 0.3 and rms_list[i-1] > 0.01)
            if dips > 8:
                alerts.append({
                    "type": "CABLE_FAILURE",
                    "severity": "CRITICAL",
                    "message": f"Predicted cable failure — {dips} signal dips in last 50 frames",
                    "action": "Replace cable immediately before full failure",
                    "value": dips
                })

        # Log new events
        for alert in alerts:
            self.events.append({
                "timestamp": datetime.now().isoformat(),
                "frame": self.frame_count,
                **alert
            })

        return alerts, self._get_health_score()

    def _get_health_score(self):
        """
        Returns a 0-100 health score for the signal.
        100 = perfect, 0 = complete failure.
        """
        if len(self.rms_history) < 10:
            return 100

        score = 100

        # Penalize clipping
        if self.clip_history:
            avg_clip = float(np.mean(list(self.clip_history)[-20:]))
            score -= min(40, avg_clip * 200)

        # Penalize dropouts
        if self.dropout_history:
            dropout_rate = float(np.mean(list(self.dropout_history)[-20:]))
            score -= min(40, dropout_rate * 150)

        # Penalize instability
        if len(self.rms_history) >= 20:
            variance = float(np.var(list(self.rms_history)[-20:]) * 10000)
            score -= min(20, variance * 0.5)

        return max(0, round(score))

    def get_status(self):
        """Returns current sentinel status summary."""
        return {
            "frame_count": self.frame_count,
            "health_score": self._get_health_score(),
            "total_events": len(self.events),
            "recent_events": self.events[-5:] if self.events else []
        }

    def get_signal_stats(self):
        """Returns current signal statistics."""
        if not self.rms_history:
            return {}
        return {
            "rms": round(float(np.mean(list(self.rms_history)[-10:])), 4),
            "clip_rate": round(float(np.mean(list(self.clip_history)[-10:])) * 100, 1) if self.clip_history else 0,
            "noise_floor": round(float(np.mean(list(self.noise_history)[-10:])), 1) if self.noise_history else -80,
            "dropout_rate": round(float(np.mean(list(self.dropout_history)[-10:])) * 100, 1) if self.dropout_history else 0
        }