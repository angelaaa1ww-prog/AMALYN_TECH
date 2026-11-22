import os
import io
import wave
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

try:
    import pyaudio
except ImportError:
    pyaudio = None
import numpy as np
import asyncio
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge, MIXER_PROFILES
from library import (
    get_perfect_state, list_all_speakers,
    list_all_microphones, list_all_mixers, list_all_venues
)
from ml_inference import ml_check, ml_engine
from sentinel import AmalynSentinel
from database import init_indexes
from auth_db import (
    create_user, authenticate_user,
    get_user_by_id, get_all_users, decode_token,
    create_token, start_oauth_verification, verify_oauth_user,
    resend_oauth_verification_code, verify_user, resend_verification_code,
)
from session_db import (
    create_session, end_session, get_user_sessions,
    get_session, log_event_db, get_session_events,
    save_channel_preset, get_user_presets, delete_preset,
    save_show_file, get_show_files, get_show_file,
    delete_show_file, get_user_stats
)
from discovery import scan_network, get_analog_options, get_audio_interfaces
from analog_manager import analog_manager
from calibration import (
    RTAMeasurement,
    SPLMeter,
    calculate_delay,
    generate_pink_noise,
)

app = FastAPI(title="AMALYN TECH API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files

# ── Request timing middleware ─────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
import time

class ProcessTimeHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        process_time = time.time() - start
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response

app.add_middleware(ProcessTimeHeaderMiddleware)
# ── End of request timing middleware ───────────────────────────────────

# Static files
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

@app.on_event("startup")
async def startup():
    async def initialize_database():
        try:
            await init_indexes()
        except Exception as error:
            print(f"[DB] Startup check failed: {error}")
        else:
            print("[DB] MongoDB connected and ready")

    # Do not block HTTP readiness on an optional/unreachable MongoDB service.
    asyncio.create_task(initialize_database())

@app.get("/")
def serve_login():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

@app.get("/login.html")
def serve_login_file():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))

@app.get("/dashboard")
def serve_dashboard():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/dashboard.html")
def serve_dashboard_file():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))

@app.get("/musician")
def serve_musician():
    return FileResponse(os.path.join(BASE_DIR, "musician.html"))

@app.get("/musician.html")
def serve_musician_file():
    return FileResponse(os.path.join(BASE_DIR, "musician.html"))

@app.get("/producer")
def serve_producer():
    return FileResponse(os.path.join(BASE_DIR, "producer.html"))

@app.get("/producer.html")
def serve_producer_file():
    return FileResponse(os.path.join(BASE_DIR, "producer.html"))

@app.get("/analog")
def serve_analog():
    return FileResponse(os.path.join(BASE_DIR, "analog.html"))

@app.get("/analog.html")
def serve_analog_file():
    return FileResponse(os.path.join(BASE_DIR, "analog.html"))

@app.get("/mixer-setup")
def serve_mixer_setup():
    return FileResponse(os.path.join(BASE_DIR, "mixer_setup.html"))

@app.get("/mixer_setup.html")
def serve_mixer_setup_file():
    return FileResponse(os.path.join(BASE_DIR, "mixer_setup.html"))

@app.get("/config.js")
def serve_config():
    return FileResponse(
        os.path.join(BASE_DIR, "config.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

@app.get("/sw.js")
def serve_service_worker():
    return FileResponse(
        os.path.join(BASE_DIR, "sw.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(
        os.path.join(BASE_DIR, "manifest.json"),
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/favicon.ico")
def serve_favicon():
    return FileResponse(
        os.path.join(BASE_DIR, "icon-192.png"),
        media_type="image/png",
    )

@app.get("/config")
def public_config():
    return {
        "supabase_url": os.getenv("SUPABASE_URL", "").strip(),
        "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", "").strip(),
    }

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

if pyaudio is None:
    p = None
    stream = None
    print("[AUDIO] PyAudio is unavailable; running in cloud/API-only mode")
else:
    try:
        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            input=True, frames_per_buffer=CHUNK
        )
    except (OSError, ValueError) as error:
        p = None
        stream = None
        print(f"[AUDIO] Microphone unavailable; running in cloud/API-only mode: {error}")
mixer = AmalynMixerBridge(mixer_type="simulator",channel=1)
mixer.connect()
sentinel = AmalynSentinel()
spl_meter = SPLMeter(sample_rate=RATE)
rta_measurement = RTAMeasurement()

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

class OAuthVerificationRequest(BaseModel):
    name: str = ""
    email: str
    role: str = "musician"
    code: Optional[str] = None

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: Optional[str] = None
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

class DelayRequest(BaseModel):
    distance_m: float
    temperature_c: float = 20.0

class SPLCalibrationRequest(BaseModel):
    reference_dbfs: float
    reference_db_spl: float
    limit_db_spl: Optional[float] = None

class RTAStartRequest(BaseModel):
    duration_seconds: float = 15.0

class PinkNoiseRequest(BaseModel):
    sample_count: int = 44_100 * 10
    level_dbfs: float = -30.0
    seed: Optional[int] = None

class AnalogMixerSelectRequest(BaseModel):
    profile_key: str
    device_name: Optional[str] = None

class AnalogMixerMapRequest(BaseModel):
    device_name: str
    profile_key: str

class AnalogMixerCreateRequest(BaseModel):
    brand_name: str
    model_name: str
    channels: int = 0
    hpf_freq: int = 80
    mid_sweep_min: int = 100
    mid_sweep_max: int = 8000
    has_compressor: bool = False
    usb_keywords: list[str] = []
    notes: str = ""


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
            spl_reading = spl_meter.update(audio_data)
            rta_reading = rta_measurement.update(frequencies, magnitudes_db)
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
                },
                "spl": spl_reading,
                "rta": rta_reading,
            }
            with frame_lock:
                latest_frame.update(frame)
        except OSError:
            continue
        except Exception as e:
            print(f"[ENGINE] Error: {e}")

if stream is not None:
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
    try:
        user, error = await create_user(
            req.name, req.email, req.password, req.role, req.confirm_password
        )
    except Exception as error:
        return {"status": "error", "message": f"Registration service error: {error}"}
    if error == "verification_required":
        return {"status": "verification_required", "email": user["email"]}
    if error:
        return {"status": "error", "message": error}
    token = __import__("auth_db").create_token(user["id"])
    return {"status": "ok", "user": user, "token": token}

@app.post("/auth/login")
async def login(req: LoginRequest):
    result, error = await authenticate_user(req.email, req.password)
    if error == "verification_required":
        return {
            "status": "verification_required",
            "message": "Verify your email before signing in.",
        }
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

@app.post("/auth/verify")
async def verify_email(req: OAuthVerificationRequest):
    if not req.code:
        return {"status": "error", "message": "Verification code is required"}
    user, error = await verify_user(req.email, req.code)
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "user": user, "token": create_token(user["id"])}

@app.post("/auth/verify/resend")
async def resend_email(req: OAuthVerificationRequest):
    user, error = await resend_verification_code(req.email)
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "email": user["email"]}

@app.post("/auth/oauth/verify/start")
async def start_oauth_verification_endpoint(req: OAuthVerificationRequest):
    try:
        user, error = await start_oauth_verification(req.name, req.email, req.role)
    except (OSError, ValueError) as error:
        return {"status": "error", "message": str(error)}
    if error:
        return {"status": "error", "message": error}
    return {
        "status": "ok",
        "user": user,
        "token": create_token(user["id"]),
    }

@app.post("/auth/oauth/verify")
async def verify_oauth_endpoint(req: OAuthVerificationRequest):
    if not req.code:
        return {"status": "error", "message": "Verification code is required"}
    user, error = await verify_oauth_user(req.email, req.code)
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "user": user, "token": create_token(user["id"])}

@app.post("/auth/oauth/verify/resend")
async def resend_oauth_endpoint(req: OAuthVerificationRequest):
    try:
        user, error = await resend_oauth_verification_code(req.email)
    except (OSError, ValueError) as error:
        return {"status": "error", "message": str(error)}
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "email": user["email"]}


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
        try:
            found = scan_network(progress_callback=prog)
            with discovery_lock:
                discovery_results.update({"status":"complete","mixers":found,"progress":100,"total":254})
        except Exception as error:
            with discovery_lock:
                discovery_results.update({"status":"error","error":str(error),"mixers":[]})
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
    scan = analog_manager.scan_usb_mixers()
    matches = {
        device["device_index"]: device
        for device in scan["devices"]
    }
    interfaces = []
    for interface in get_audio_interfaces():
        match = matches.get(interface["index"], {})
        profile = match.get("matched_mixer") or {}
        interfaces.append({
            **interface,
            "matched_profile": (
                f'{profile.get("brand", "")} {profile.get("model", "")}'.strip()
                if profile else None
            ),
            "profile_key": profile.get("key"),
            "confidence": match.get("confidence", 0),
            "match_reason": match.get("match_reason", "No USB profile match"),
            "is_usb": interface["name"].lower().find("usb") >= 0
            or bool(match.get("is_usb")),
        })
    return {
        "interfaces": interfaces,
        "message": "No USB or audio input interfaces found." if not interfaces else None,
        "auto_detected": scan["auto_detected"],
    }

@app.post("/mixer/connect")
def connect_mixer(req: ConnectRequest):
    global mixer, p, stream
    try:
        if req.mixer_key != "simulator" and req.mixer_key not in MIXER_PROFILES:
            profile_key = {
                "yamaha_mg": "yamaha_mg",
                "mackie_vlz": "mackie_profx",
                "behringer_xenyx": "behringer_xenyx",
                "allen_heath_zed": "allen_heath_zed",
                "soundcraft_efx": "soundcraft_signature",
            }.get(req.mixer_key, "generic_analog")
            device_name = None
            if req.interface_index is not None:
                for interface in get_audio_interfaces():
                    if interface["index"] == req.interface_index:
                        device_name = interface["name"]
                        break
            analog_manager.set_active_mixer(
                profile_key,
                device_name=device_name,
                manual=True,
            )

            if req.interface_index is not None:
                valid_indexes = {
                    interface["index"]
                    for interface in get_audio_interfaces()
                }
                if req.interface_index not in valid_indexes:
                    return {
                        "status":"error",
                        "message":"Selected USB interface is no longer available.",
                    }
            return {
                "status":"connected",
                "mixer":req.mixer_key,
                "analog_profile":analog_manager.active_mixer_key,
                "interface_index":req.interface_index,
            }

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


# ── Analog mixer and calibration ──────────────────────────────────────
@app.get("/analog/usb/scan")
def scan_analog_usb():
    result = analog_manager.scan_usb_mixers()
    devices = []
    for device in result["devices"]:
        profile = device.get("matched_mixer") or {}
        devices.append({
            "name": device["device_name"],
            "device_index": device["device_index"],
            "channels": device["channels"],
            "sample_rate": device["sample_rate"],
            "matched_profile": (
                f'{profile.get("brand", "")} {profile.get("model", "")}'.strip()
                if profile else None
            ),
            "profile_key": profile.get("key"),
            "confidence": device["confidence"],
            "match_reason": device["match_reason"],
        })
    return {
        "devices": devices,
        "total_detected": result["total_detected"],
        "active_mixer": result["active_mixer"],
        "auto_detected": result["auto_detected"],
    }


@app.get("/analog/mixers")
def list_analog_mixers():
    mixers = []
    for key, profile in analog_manager.get_all_mixers().items():
        specs = profile.get("specs", {})
        mixers.append({
            "key": key,
            "brand_name": profile.get("brand", ""),
            "model_name": profile.get("model", ""),
            "channels": profile.get("channels", 0),
            "hpf_freq": specs.get("hpf_freq"),
            "has_sweep_mid": specs.get("has_sweep_mid", False),
            "source": "custom" if profile.get("is_custom") else "builtin",
        })
    return {"mixers": mixers}


@app.get("/analog/mixer/active")
def active_analog_mixer():
    profile = analog_manager.get_active_mixer()
    return {"active_mixer": {"profile_key": analog_manager.active_mixer_key, **profile}}


@app.post("/analog/mixer/select")
def select_analog_mixer(req: AnalogMixerSelectRequest):
    if not analog_manager.set_active_mixer(
        req.profile_key, device_name=req.device_name, manual=True
    ):
        raise HTTPException(status_code=404, detail="Analog mixer profile not found")
    return {"status": "ok", "active_mixer": analog_manager.get_active_mixer()}


@app.post("/analog/mixers/custom")
def create_analog_mixer(req: AnalogMixerCreateRequest):
    success, message, entry = analog_manager.add_custom_mixer({
        "brand": req.brand_name,
        "model": req.model_name,
        "usb_keywords": req.usb_keywords,
        "specs": {
            "hpf_freq": req.hpf_freq,
            "mid_sweep_min": req.mid_sweep_min,
            "mid_sweep_max": req.mid_sweep_max,
            "compressor": "Analog Compressor" if req.has_compressor else "None",
        },
        "description": req.notes,
    })
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "ok", "message": message, "key": entry["key"], "mixer": entry}


@app.delete("/analog/mixers/custom/{mixer_key}")
def delete_analog_mixer(mixer_key: str):
    success, message = analog_manager.delete_custom_mixer(mixer_key)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "ok", "message": message}


@app.post("/analog/device/map")
def map_analog_device(req: AnalogMixerMapRequest):
    success, message = analog_manager.map_device_to_mixer(
        req.device_name, req.profile_key
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "ok", "message": message}


@app.post("/calibration/delay")
def calibration_delay(req: DelayRequest):
    try:
        return calculate_delay(req.distance_m, req.temperature_c)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/calibration/spl")
def calibration_spl():
    return spl_meter.snapshot()


@app.post("/calibration/spl")
def set_calibration_spl(req: SPLCalibrationRequest):
    try:
        return spl_meter.set_calibration(
            req.reference_dbfs, req.reference_db_spl, req.limit_db_spl
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/calibration/spl")
def clear_calibration_spl():
    return spl_meter.clear_calibration()


@app.get("/calibration/rta")
def calibration_rta():
    return rta_measurement.snapshot()


@app.post("/calibration/rta/start")
def start_calibration_rta(req: RTAStartRequest):
    try:
        return rta_measurement.start(req.duration_seconds)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/calibration/rta/cancel")
def cancel_calibration_rta():
    return rta_measurement.cancel()


@app.get("/calibration/pink-noise")
def calibration_pink_noise(
    sample_count: int = 44_100 * 10,
    level_dbfs: float = -30.0,
    seed: Optional[int] = None,
):
    try:
        samples = generate_pink_noise(sample_count, level_dbfs, seed)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.tobytes())
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=amalyn-pink-noise.wav"},
    )


# ── Health ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "AMALYN API Running",
        "version": "1.0.0",
        "session": current_session_id,
        "engine": "active" if stream is not None else "unavailable",
        "ml": "active" if ml_engine.is_ready() else "unavailable",
        "sentinel": "active",
    }


@app.get("/capabilities")
def capabilities():
    """Report capabilities available on this host without probing external services."""
    return {
        "audio_capture": {
            "available": stream is not None,
            "backend": "PyAudio" if pyaudio is not None else None,
            "sample_rate": RATE if stream is not None else None,
            "channels": CHANNELS if stream is not None else None,
        },
        "ml": {
            "available": ml_engine.is_ready(),
            "model": "amalyn_detector" if ml_engine.is_ready() else None,
        },
        "mixer": {
            "simulator": True,
            "connected": mixer.connected,
            "supported_profiles": sorted(MIXER_PROFILES),
        },
        "cloud": {
            "mongodb_configured": bool(os.getenv("MONGODB_URI", "").strip()),
            "supabase_configured": bool(
                os.getenv("SUPABASE_URL", "").strip()
                and os.getenv("SUPABASE_ANON_KEY", "").strip()
            ),
        },
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")