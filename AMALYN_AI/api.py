import pyaudio
import numpy as np
import asyncio
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge
from library import get_perfect_state, list_all_speakers, list_all_microphones, list_all_mixers, list_all_venues
from ml_inference import ml_check
from sentinel import AmalynSentinel
from auth import authenticate, get_all_users, add_user

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- SHARED STATE ---
latest_frame = {
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
    "sentinel": {
        "health_score": 100,
        "alerts": [],
        "signal_stats": {}
    }
}
frame_lock = threading.Lock()

# --- AUDIO ---
p = pyaudio.PyAudio()
stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

# --- MIXER ---
mixer = AmalynMixerBridge(mixer_type="simulator", channel=1)
mixer.connect()

# --- SENTINEL ---
sentinel = AmalynSentinel()

# --- SESSION STATE ---
last_status = "CLEAN"
last_correction_freq = 0
current_perfect_state = None

# --- MUSICIAN CHANNELS ---
musician_channels = [
    {"id": 1, "name": "Vocals", "level": 75, "mute": False},
    {"id": 2, "name": "Guitar", "level": 60, "mute": False},
    {"id": 3, "name": "Bass",   "level": 55, "mute": False},
    {"id": 4, "name": "Keys",   "level": 50, "mute": False},
    {"id": 5, "name": "Drums",  "level": 65, "mute": False},
    {"id": 6, "name": "Click",  "level": 40, "mute": False}
]


# --- PYDANTIC MODELS ---
class SetupRequest(BaseModel):
    venue: str
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer_type: Optional[str] = None


class MixUpdate(BaseModel):
    channel_id: int
    level: Optional[int] = None
    mute: Optional[bool] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str


# --- AUDIO ENGINE ---
def audio_engine():
    global last_status, last_correction_freq

    print("[ENGINE] Audio engine started")

    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            frequencies, magnitudes_db = get_frequency_map(audio_data)
            dominant_freq, dominant_mag = get_dominant_frequency(frequencies, magnitudes_db)

            # Threshold detection
            status, danger_freq, danger_mag = check_for_feedback(frequencies, magnitudes_db)

            # ML detection
            ml_status, ml_confidence = ml_check(magnitudes_db)
            if ml_status and ml_status != "CLEAN" and status == "CLEAN":
                status = ml_status
                print(f"[ML] Caught early: {ml_status} ({ml_confidence}% confidence)")

            # Sentinel analysis
            sentinel_alerts, health_score = sentinel.analyze(audio_data, magnitudes_db)
            signal_stats = sentinel.get_signal_stats()

            for alert in sentinel_alerts:
                if alert["severity"] == "CRITICAL":
                    print(f"[SENTINEL] {alert['type']}: {alert['message']}")

            suggestion = suggest_eq(danger_freq, danger_mag, status)

            if status in ("WARNING", "CRITICAL") and suggestion:
                if danger_freq != last_correction_freq:
                    mixer.send_eq_correction(suggestion)
                    last_correction_freq = danger_freq

            if status == "CRITICAL" and last_status != "CRITICAL":
                mixer.send_safe_profile()

            if status != "CLEAN" and status != last_status:
                log_event(status, danger_freq, danger_mag, suggestion)

            last_status = status

            frame = {
                "status": status,
                "dominant_freq": round(float(dominant_freq), 1),
                "dominant_mag": round(float(dominant_mag), 1),
                "danger_freq": round(float(danger_freq), 1),
                "danger_mag": round(float(danger_mag), 1),
                "frequencies": [round(f, 1) for f in frequencies.tolist()[::2]],
                "magnitudes": [round(m, 1) for m in magnitudes_db.tolist()[::2]],
                "suggestion": suggestion,
                "mixer_corrections": mixer.get_corrections_summary(),
                "perfect_state": current_perfect_state,
                "ml_status": ml_status,
                "ml_confidence": ml_confidence,
                "sentinel": {
                    "health_score": health_score,
                    "alerts": sentinel_alerts[:3],
                    "signal_stats": signal_stats
                }
            }

            with frame_lock:
                latest_frame.update(frame)

        except OSError:
            continue
        except Exception as e:
            print(f"[ENGINE] Error: {e}")
            continue


audio_thread = threading.Thread(target=audio_engine, daemon=True)
audio_thread.start()


# --- WEBSOCKET ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Client connected")
    try:
        while True:
            with frame_lock:
                frame = dict(latest_frame)
            await websocket.send_text(json.dumps(frame))
            await asyncio.sleep(0.025)
    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")


# --- AUTH ENDPOINTS ---
@app.post("/auth/login")
def login(request: LoginRequest):
    user = authenticate(request.email, request.password)
    if user:
        return {"status": "ok", "user": user}
    return {"status": "error", "message": "Invalid email or password"}


@app.get("/auth/users")
def list_users():
    return {"users": get_all_users()}


@app.post("/auth/register")
def register(request: RegisterRequest):
    user, error = add_user(
        request.name, request.email,
        request.password, request.role
    )
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "user": user}


# --- SETUP ENDPOINT ---
@app.post("/setup")
def setup(request: SetupRequest):
    global current_perfect_state
    current_perfect_state = get_perfect_state(
        venue_type=request.venue,
        speaker_key=request.speaker,
        mic_key=request.mic,
        mixer_key=request.mixer_type
    )
    print(f"\n[SETUP] Perfect State loaded: {current_perfect_state['venue']}")
    print(f"  Speaker : {current_perfect_state['speaker']}")
    print(f"  Mic     : {current_perfect_state['microphone']}")
    print(f"  Mixer   : {current_perfect_state['mixer']}")
    print(f"  EQ Bands: {len(current_perfect_state['combined_eq'])}")
    return current_perfect_state


# --- LIBRARY ENDPOINT ---
@app.get("/library")
def get_library():
    return {
        "speakers": list_all_speakers(),
        "microphones": list_all_microphones(),
        "mixers": list_all_mixers(),
        "venues": list_all_venues()
    }


# --- SENTINEL ENDPOINT ---
@app.get("/sentinel/status")
def sentinel_status():
    return sentinel.get_status()


# --- MUSICIAN ENDPOINTS ---
@app.get("/musician/channels")
def get_channels():
    return {"channels": musician_channels}


@app.post("/musician/mix")
def update_mix(update: MixUpdate):
    channel = next((c for c in musician_channels if c["id"] == update.channel_id), None)
    if not channel:
        return {"status": "error", "message": f"Channel {update.channel_id} not found"}
    if update.level is not None:
        channel["level"] = max(0, min(100, update.level))
        print(f"[MUSICIAN] Ch{update.channel_id} ({channel['name']}) level → {channel['level']}")
    if update.mute is not None:
        channel["mute"] = update.mute
        print(f"[MUSICIAN] Ch{update.channel_id} ({channel['name']}) mute → {channel['mute']}")
    return {"status": "ok", "channel_id": update.channel_id, "channel": channel}


# --- MIXER SAFE ENDPOINT ---
@app.get("/mixer/safe")
def trigger_safe():
    mixer.send_safe_profile()
    return {"status": "Safe profile applied"}


# --- HEALTH ENDPOINT ---
@app.get("/health")
def health():
    return {"status": "AMALYN API Running"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")