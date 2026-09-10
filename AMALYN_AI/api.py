import os
from dotenv import load_dotenv
load_dotenv()

import pyaudio
import numpy as np
import asyncio
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge
from library import (
    get_perfect_state, list_all_speakers,
    list_all_microphones, list_all_mixers, list_all_venues
)
from ml_inference import ml_check
from sentinel import AmalynSentinel
from database import init_indexes
from auth_db import (
    create_user, authenticate_user,
    get_user_by_id, get_all_users, decode_token
)
from session_db import (
    create_session, end_session, get_user_sessions,
    get_session, log_event_db, get_session_events,
    save_channel_preset, get_user_presets, delete_preset,
    save_show_file, get_show_files, get_show_file,
    delete_show_file, get_user_stats
)
from discovery import scan_network, get_analog_options, get_audio_interfaces

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="AMALYN TECH API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

@app.on_event("startup")
async def startup():
    await init_indexes()
    print("[DB] MongoDB connected and ready")

@app.get("/"); def serve_login(): return FileResponse(os.path.join(BASE_DIR,"login.html"))
@app.get("/dashboard"); def serve_dashboard(): return FileResponse(os.path.join(BASE_DIR,"dashboard.html"))
@app.get("/musician"); def serve_musician(): return FileResponse(os.path.join(BASE_DIR,"musician.html"))
@app.get("/producer"); def serve_producer(): return FileResponse(os.path.join(BASE_DIR,"producer.html"))
@app.get("/mixer-setup"); def serve_mixer_setup(): return FileResponse(os.path.join(BASE_DIR,"mixer_setup.html"))
@app.get("/config.js"); def serve_config(): return FileResponse(os.path.join(BASE_DIR,"config.js"))

# ── Shared Audio State ─────────────────────────────────────────────────
latest_frame = {
    "status":"CLEAN","dominant_freq":0.0,"dominant_mag":-80.0,
    "danger_freq":0.0,"danger_mag":-80.0,
    "frequencies":[],"magnitudes":[],"suggestion":None,
    "mixer_corrections":{"total_corrections":0,"corrections":[]},
    "perfect_state":None,"ml_status":None,"ml_confidence":None,
    "sentinel":{"health_score":100,"alerts":[],"signal_stats":{}}
}
frame_lock = threading.Lock()

p = pyaudio.PyAudio()
stream = p.open(format=FORMAT,channels=CHANNELS,rate=RATE,input=True,frames_per_buffer=CHUNK)
mixer = AmalynMixerBridge(mixer_type="simulator",channel=1)
mixer.connect()
sentinel = AmalynSentinel()

last_status = "CLEAN"
last_correction_freq = 0
current_perfect_state = None
current_session_id = None
current_user_id = None

musician_channels = [
    {"id":1,"name":"Vocals","level":75,"mute":False},
    {"id":2,"name":"Guitar","level":60,"mute":False},
    {"id":3,"name":"Bass","level":55,"mute":False},
    {"id":4,"name":"Keys","level":50,"mute":False},
    {"id":5,"name":"Drums","level":65,"mute":False},
    {"id":6,"name":"Click","level":40,"mute":False},
]

discovery_results = {"status":"idle","mixers":[],"progress":0,"total":0}
discovery_lock = threading.Lock()


# ── Auth Helper ────────────────────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Models ─────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "engineer"

class SetupRequest(BaseModel):
    venue: str
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer_type: Optional[str] = None
    user_id: Optional[str] = None

class MixUpdate(BaseModel):
    channel_id: int
    level: Optional[int] = None
    mute: Optional[bool] = None

class PresetSave(BaseModel):
    user_id: str
    name: str
    venue_key: Optional[str] = None
    channels: list

class ShowFileSave(BaseModel):
    user_id: str
    name: str
    venue: Optional[str] = None
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer: Optional[str] = None
    notes: Optional[str] = None

class ConnectRequest(BaseModel):
    mixer_key: str
    ip: Optional[str] = None
    port: Optional[int] = None
    interface_index: Optional[int] = None


# ── Audio Engine ───────────────────────────────────────────────────────
def audio_engine():
    global last_status, last_correction_freq
    print("[ENGINE] Audio engine started")
    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            frequencies, magnitudes_db = get_frequency_map(audio_data)
            dominant_freq, dominant_mag = get_dominant_frequency(frequencies, magnitudes_db)
            status, danger_freq, danger_mag = check_for_feedback(frequencies, magnitudes_db)
            ml_status, ml_confidence = ml_check(magnitudes_db)
            if ml_status and ml_status != "CLEAN" and status == "CLEAN":
                status = ml_status
            sentinel_alerts, health_score = sentinel.analyze(audio_data, magnitudes_db)
            signal_stats = sentinel.get_signal_stats()
            suggestion = suggest_eq(danger_freq, danger_mag, status)

            if status in ("WARNING","CRITICAL") and suggestion:
                if danger_freq != last_correction_freq:
                    mixer.send_eq_correction(suggestion)
                    last_correction_freq = danger_freq

            if status == "CRITICAL" and last_status != "CRITICAL":
                mixer.send_safe_profile()

            if status != "CLEAN" and status != last_status:
                log_event(status, danger_freq, danger_mag, suggestion)
                # Save to MongoDB if session is active
                if current_session_id and current_user_id:
                    log_event_db(
                        current_session_id, current_user_id,
                        status, danger_freq, danger_mag, suggestion
                    )

            last_status = status
            frame = {
                "status": status,
                "dominant_freq": round(float(dominant_freq),1),
                "dominant_mag": round(float(dominant_mag),1),
                "danger_freq": round(float(danger_freq),1),
                "danger_mag": round(float(danger_mag),1),
                "frequencies": [round(f,1) for f in frequencies.tolist()[::2]],
                "magnitudes": [round(m,1) for m in magnitudes_db.tolist()[::2]],
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

threading.Thread(target=audio_engine, daemon=True).start()


# ── WebSocket ──────────────────────────────────────────────────────────
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


# ── Auth ───────────────────────────────────────────────────────────────
@app.post("/auth/register")
async def register(req: RegisterRequest):
    user, error = await create_user(req.name, req.email, req.password, req.role)
    if error:
        return {"status": "error", "message": error}
    token = __import__("auth_db").create_token(user["id"])
    return {"status": "ok", "user": user, "token": token}

@app.post("/auth/login")
async def login(req: LoginRequest):
    result, error = await authenticate_user(req.email, req.password)
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "user": result["user"], "token": result["token"]}

@app.get("/auth/me")
async def me(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    return {"status": "ok", "user": user}

@app.get("/auth/users")
async def list_users_endpoint():
    return {"users": await get_all_users()}


# ── User Progress ──────────────────────────────────────────────────────
@app.get("/user/{user_id}/stats")
async def user_stats(user_id: str):
    stats = await get_user_stats(user_id)
    return stats

@app.get("/user/{user_id}/sessions")
async def user_sessions(user_id: str):
    sessions = await get_user_sessions(user_id)
    return {"sessions": sessions}

@app.get("/session/{session_id}/events")
async def session_events(session_id: str):
    events = await get_session_events(session_id)
    return {"events": events}


# ── Setup / Perfect State ──────────────────────────────────────────────
@app.post("/setup")
async def setup(req: SetupRequest):
    global current_perfect_state, current_session_id, current_user_id
    current_perfect_state = get_perfect_state(
        venue_type=req.venue,
        speaker_key=req.speaker,
        mic_key=req.mic,
        mixer_key=req.mixer_type,
    )
    # Create session in MongoDB
    if req.user_id:
        current_user_id = req.user_id
        current_session_id = await create_session(req.user_id, {
            "venue": current_perfect_state.get("venue"),
            "speaker": current_perfect_state.get("speaker"),
            "mic": current_perfect_state.get("microphone"),
            "mixer": current_perfect_state.get("mixer"),
        })
        print(f"[DB] Session created: {current_session_id}")
    print(f"[SETUP] Perfect State: {current_perfect_state['venue']}")
    return {**current_perfect_state, "session_id": current_session_id}


# ── Library ────────────────────────────────────────────────────────────
@app.get("/library")
def get_library():
    return {
        "speakers": list_all_speakers(),
        "microphones": list_all_microphones(),
        "mixers": list_all_mixers(),
        "venues": list_all_venues(),
    }


# ── Sentinel ───────────────────────────────────────────────────────────
@app.get("/sentinel/status")
def sentinel_status():
    return sentinel.get_status()


# ── Musician ───────────────────────────────────────────────────────────
@app.get("/musician/channels")
def get_channels():
    return {"channels": musician_channels}

@app.post("/musician/mix")
def update_mix(update: MixUpdate):
    ch = next((c for c in musician_channels if c["id"]==update.channel_id), None)
    if not ch:
        return {"status":"error","message":"Channel not found"}
    if update.level is not None:
        ch["level"] = max(0, min(100, update.level))
    if update.mute is not None:
        ch["mute"] = update.mute
    return {"status":"ok","channel":ch}

@app.post("/musician/preset/save")
async def save_preset(req: PresetSave):
    pid = await save_channel_preset(req.user_id, req.name, req.channels, req.venue_key)
    return {"status":"ok","preset_id": pid}

@app.get("/musician/presets/{user_id}")
async def get_presets(user_id: str):
    presets = await get_user_presets(user_id)
    return {"presets": presets}

@app.delete("/musician/preset/{preset_id}")
async def del_preset(preset_id: str, user_id: str):
    await delete_preset(preset_id, user_id)
    return {"status":"ok"}


# ── Show Files ─────────────────────────────────────────────────────────
@app.post("/shows/save")
async def save_show(req: ShowFileSave):
    show_id = await save_show_file(req.user_id, req.name, req.dict())
    return {"status":"ok","show_id": show_id}

@app.get("/shows/{user_id}")
async def get_shows(user_id: str):
    shows = await get_show_files(user_id)
    return {"shows": shows}

@app.get("/shows/{user_id}/{show_id}")
async def get_show(user_id: str, show_id: str):
    show = await get_show_file(show_id, user_id)
    return {"show": show}

@app.delete("/shows/{user_id}/{show_id}")
async def del_show(user_id: str, show_id: str):
    await delete_show_file(show_id, user_id)
    return {"status":"ok"}


# ── Mixer Discovery ────────────────────────────────────────────────────
@app.get("/mixer/scan")
def start_scan():
    def run():
        with discovery_lock:
            discovery_results.update({"status":"scanning","mixers":[],"progress":0})
        def prog(sc,tot,found):
            with discovery_lock:
                discovery_results.update({"progress":sc,"total":tot,"mixers":found})
        found = scan_network(progress_callback=prog)
        with discovery_lock:
            discovery_results.update({"status":"complete","mixers":found})
    threading.Thread(target=run, daemon=True).start()
    return {"status":"scanning_started"}

@app.get("/mixer/scan/status")
def scan_status():
    with discovery_lock:
        return dict(discovery_results)

@app.get("/mixer/analog")
def get_analog():
    return {"mixers": get_analog_options()}

@app.get("/mixer/interfaces")
def get_interfaces():
    return {"interfaces": get_audio_interfaces()}

@app.post("/mixer/connect")
def connect_mixer(req: ConnectRequest):
    global mixer
    try:
        new_mixer = AmalynMixerBridge(mixer_type=req.mixer_key, channel=1)
        if req.ip:
            new_mixer.profile['ip'] = req.ip
        if req.port:
            new_mixer.profile['port'] = req.port
        success = new_mixer.connect()
        if success or req.mixer_key != "simulator":
            mixer = new_mixer
            return {"status":"connected","mixer":req.mixer_key,"ip":req.ip}
        return {"status":"error","message":"Could not connect"}
    except Exception as e:
        return {"status":"error","message":str(e)}

@app.get("/mixer/safe")
def trigger_safe():
    mixer.send_safe_profile()
    return {"status":"Safe profile applied"}


# ── Health ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "AMALYN API Running",
        "version": "1.0.0",
        "session": current_session_id,
        "engine": "active",
        "ml": "active",
        "sentinel": "active",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")