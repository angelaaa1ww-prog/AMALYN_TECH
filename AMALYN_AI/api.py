import logging
import io
import wave
from discovery import scan_network, get_analog_options, get_audio_interfaces
import numpy as np
import asyncio
import json
import threading
import os
import smtplib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn
from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from calibration import SPLMeter, RTAMeasurement, calculate_delay, generate_pink_noise
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge
from library import get_perfect_state, list_all_speakers, list_all_microphones, list_all_mixers, list_all_venues
from ml_inference import ml_check
from sentinel import AmalynSentinel
from analog_advisor import generate_analog_advice
from analog_manager import analog_manager
from auth import (
    authenticate_with_status,
    get_all_users,
    add_user,
    resend_verification_code,
    send_verification_code,
    verify_user,
    start_oauth_verification,
    resend_oauth_verification_code,
    verify_oauth_user,
    password_errors,
    validate_email,
    PASSWORD_REQUIREMENTS,
)

BASE_DIR = os.path.dirname(__file__)

def load_env_file():
    for env_path in [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), ".env"),
    ]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'").strip('"')
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

load_env_file()

logger = logging.getLogger(__name__)

app = FastAPI(title="AMALYN TECH API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

# --- CALIBRATION STATE ---
# These objects are intentionally session-scoped. An SPL reference is valid only
# for the active interface, microphone, gain and measurement position.
spl_meter = SPLMeter(sample_rate=RATE)
rta_measurement = RTAMeasurement()

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
    },
    "spl": spl_meter.snapshot(),
    "rta": rta_measurement.snapshot(),
    "analog_advice": generate_analog_advice("CLEAN", 0.0, -80.0, mixer_profile=analog_manager.get_active_mixer())
}
frame_lock = threading.Lock()

# --- AUDIO ---
# Capture is opened only when this module is run as the server entrypoint.
# Importing the API must remain safe for tests, tooling, and non-audio clients.
p = None
stream = None
audio_instance = None
audio_thread = None
analog_monitor = {"active": False, "interface_index": None, "interface_name": None}

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
    confirm_password: str
    role: str


class VerifyRequest(BaseModel):
    email: str
    code: str


class ResendVerificationRequest(BaseModel):
    email: str


class OAuthVerificationRequest(BaseModel):
    name: str
    email: str
    role: str = "musician"


class DelayRequest(BaseModel):
    distance_m: float
    temperature_c: float = 20.0


class SPLCalibrationRequest(BaseModel):
    reference_dbfs: float
    reference_db_spl: float
    limit_db_spl: Optional[float] = None


class RTAMeasurementRequest(BaseModel):
    duration_seconds: float = 15.0


# --- AUDIO ENGINE ---
def audio_engine():
    global last_status, last_correction_freq

    if stream is None:
        print("[ENGINE] Audio capture is unavailable")
        return

    print("[ENGINE] Audio engine started")

    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            frequencies, magnitudes_db = get_frequency_map(audio_data)
            dominant_freq, dominant_mag = get_dominant_frequency(frequencies, magnitudes_db)
            spl = spl_meter.update(audio_data)
            rta = rta_measurement.update(frequencies, magnitudes_db)

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

            # Only log CRITICAL alerts to avoid console spam
            for alert in sentinel_alerts:
                if alert["severity"] == "CRITICAL":
                    logger.warning("[SENTINEL] %s: %s", alert['type'], alert['message'])

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

            analog_advice = generate_analog_advice(
                status=status,
                danger_freq=danger_freq,
                danger_mag=danger_mag,
                frequencies=frequencies,
                magnitudes_db=magnitudes_db,
                sentinel_stats=signal_stats,
                sentinel_alerts=sentinel_alerts,
                mixer_profile=analog_manager.get_active_mixer()
            )

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
                },
                "spl": spl,
                "rta": rta,
                "analog_advice": analog_advice
            }

            with frame_lock:
                latest_frame.update(frame)

        except OSError:
            continue
        except Exception as e:
            print(f"[ENGINE] Error: {e}")
            continue


audio_thread = None


# --- WEBSOCKET ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            with frame_lock:
                frame = dict(latest_frame)
            await websocket.send_text(json.dumps(frame))
            await asyncio.sleep(0.05)   # max 20fps — smooth spectrum, minimal CPU
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("[WS] Error: %s", e)


# --- AUTH ENDPOINTS ---
@app.post("/auth/login")
def login(request: LoginRequest):
    user, status = authenticate_with_status(request.email, request.password)
    if user:
        return {"status": "ok", "user": user}
    if status == "verification_required":
        return {
            "status": "verification_required",
            "message": "Verify your email before signing in.",
        }
    return {"status": "error", "message": "Invalid email or password"}


@app.get("/auth/users")
def list_users():
    return {"users": get_all_users()}


@app.get("/auth/password-policy")
def password_policy():
    return {"requirements": PASSWORD_REQUIREMENTS}


@app.post("/auth/register")
def register(request: RegisterRequest):
    if not validate_email(request.email):
        return {"status": "error", "message": "Enter a valid email address"}
    password_validation_errors = password_errors(
        request.password, request.confirm_password
    )
    if password_validation_errors:
        return {"status": "error", "message": password_validation_errors[0]}
    user, error = add_user(
        request.name, request.email,
        request.password, request.role
    )
    if error:
        return {"status": "error", "message": error}
    try:
        delivered = send_verification_code(user)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        logger.error("[AUTH] Verification email failed: %s", error)
        return {"status": "error", "message": "Could not send verification code"}
    if not delivered:
        return {
            "status": "error",
            "message": "Email delivery is not configured. Ask the AMALYN administrator to configure SMTP, then sign in and request a code.",
        }
    return {
        "status": "verification_required",
        "message": "Enter the verification code sent to your email."
    }


@app.post("/auth/verify")
def verify(request: VerifyRequest):
    user, error = verify_user(request.email, request.code)
    if error:
        return {"status": "error", "message": error}
    return {
        "status": "ok",
        "user": user,
    }


@app.post("/auth/verify/resend")
def resend_verification(request: ResendVerificationRequest):
    user, error = resend_verification_code(request.email)
    if error:
        return {"status": "error", "message": error}
    try:
        delivered = send_verification_code(user)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        logger.error("[AUTH] Verification resend failed: %s", error)
        return {"status": "error", "message": "Could not send verification code"}
    if not delivered:
        return {
            "status": "error",
            "message": "Email delivery is not configured. Ask the AMALYN administrator to configure SMTP.",
        }
    return {"status": "ok", "message": "A new verification code has been sent."}


@app.post("/auth/oauth/verify/start")
def start_oauth_verify(request: OAuthVerificationRequest):
    user, error = start_oauth_verification(
        request.name, request.email, request.role
    )
    if error:
        return {"status": "error", "message": error}
    try:
        delivered = send_verification_code(user, oauth=True)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        logger.error("[AUTH] OAuth verification email failed: %s", error)
        return {"status": "error", "message": "Could not send verification code"}
    if not delivered:
        return {
            "status": "error",
            "message": "Email delivery is not configured. Ask the AMALYN administrator to configure SMTP.",
        }
    return {
        "status": "verification_required",
        "message": "Enter the verification code sent to your Google email address.",
    }


@app.post("/auth/oauth/verify")
def verify_oauth(request: VerifyRequest):
    user, error = verify_oauth_user(request.email, request.code)
    if error:
        return {"status": "error", "message": error}
    return {"status": "ok", "user": user}


@app.post("/auth/oauth/verify/resend")
def resend_oauth_verify(request: ResendVerificationRequest):
    user, error = resend_oauth_verification_code(request.email)
    if error:
        return {"status": "error", "message": error}
    try:
        delivered = send_verification_code(user, oauth=True)
    except (OSError, ValueError, smtplib.SMTPException) as error:
        logger.error("[AUTH] OAuth verification resend failed: %s", error)
        return {"status": "error", "message": "Could not send verification code"}
    if not delivered:
        return {
            "status": "error",
            "message": "Email delivery is not configured. Ask the AMALYN administrator to configure SMTP.",
        }
    return {"status": "ok", "message": "A new verification code has been sent."}


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


# --- CALIBRATION ENDPOINTS ---
@app.post("/calibration/delay")
def delay_calculation(request: DelayRequest):
    """Calculate loudspeaker time-of-flight from a measured physical distance."""
    try:
        return calculate_delay(request.distance_m, request.temperature_c)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/calibration/spl")
def spl_status():
    """Return the current SPL meter state (dBFS until physically calibrated)."""
    return spl_meter.snapshot()


@app.post("/calibration/spl")
def set_spl_calibration(request: SPLCalibrationRequest):
    """Set a microphone/interface SPL reference and optional venue limit."""
    try:
        return spl_meter.set_calibration(
            request.reference_dbfs,
            request.reference_db_spl,
            request.limit_db_spl,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/calibration/spl")
def clear_spl_calibration():
    """Return to uncalibrated dBFS display for the active session."""
    return spl_meter.clear_calibration()


@app.post("/calibration/spl/reset")
def reset_spl_meter():
    spl_meter.reset()
    return spl_meter.snapshot()


@app.get("/calibration/rta")
def rta_status():
    """Return the one-third-octave room measurement status and latest trace."""
    return rta_measurement.snapshot()


@app.post("/calibration/rta/start")
def start_rta_measurement(request: RTAMeasurementRequest):
    """Start a bounded room capture after pink noise is safely routed to the PA."""
    try:
        return rta_measurement.start(request.duration_seconds)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/calibration/rta/cancel")
def cancel_rta_measurement():
    return rta_measurement.cancel()


@app.get("/calibration/pink-noise")
def pink_noise_track(
    duration_seconds: float = Query(default=15.0, ge=5.0, le=90.0),
    level_dbfs: float = Query(default=-30.0, ge=-80.0, le=-12.0),
):
    """Stream a bounded pink-noise WAV for an explicitly armed browser playback.

    The browser's output device remains under the engineer's control.  The
    dashboard requires a safety acknowledgement before requesting this route.
    """
    samples = generate_pink_noise(
        sample_count=round(RATE * duration_seconds), level_dbfs=level_dbfs
    )
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

@app.get("/config.js")
def serve_config():
    return FileResponse(os.path.join(os.path.dirname(__file__), "config.js"))

# ─── Mixer Discovery ───────────────────────────────────────────────────
discovery_results = {"status": "idle", "mixers": [], "progress": 0, "total": 0}
discovery_lock = threading.Lock()


@app.get("/mixer/scan")
def start_scan(network: Optional[str] = Query(default=None)):
    """Start a network scan for mixers in background."""
    with discovery_lock:
        if discovery_results["status"] == "scanning":
            return {"status": "already_scanning"}

    def run_scan():
        with discovery_lock:
            discovery_results["status"] = "scanning"
            discovery_results["mixers"] = []
            discovery_results["progress"] = 0
            discovery_results["total"] = 0
            discovery_results.pop("error", None)

        def progress(scanned, total, found):
            with discovery_lock:
                discovery_results["progress"] = scanned
                discovery_results["total"] = total
                discovery_results["mixers"] = found

        try:
            found = scan_network(progress_callback=progress, cidr=network)
        except (RuntimeError, ValueError) as error:
            logger.error("[DISCOVERY] Scan failed: %s", error)
            with discovery_lock:
                discovery_results["status"] = "error"
                discovery_results["error"] = str(error)
            return

        with discovery_lock:
            discovery_results["status"] = "complete"
            discovery_results["mixers"] = found
            discovery_results["progress"] = discovery_results["total"]

    threading.Thread(target=run_scan, daemon=True).start()
    return {"status": "scanning_started"}


@app.get("/mixer/scan/status")
def scan_status():
    with discovery_lock:
        return dict(discovery_results)


@app.get("/mixer/analog")
def get_analog():
    return {"mixers": get_analog_options()}


@app.get("/mixer/interfaces")
def get_interfaces():
    try:
        return {"interfaces": get_audio_interfaces()}
    except (ImportError, OSError) as error:
        logger.warning("[AUDIO] Could not list audio interfaces: %s", error)
        return {"interfaces": [], "message": "Audio capture is unavailable on this server"}


class ConnectRequest(BaseModel):
    mixer_key: str
    ip: Optional[str] = None
    port: Optional[int] = None
    interface_index: Optional[int] = None


@app.post("/mixer/connect")
def connect_mixer(req: ConnectRequest):
    global mixer, stream, audio_instance, audio_thread, analog_monitor
    try:
        if req.ip:
            import ipaddress
            try:
                ipaddress.ip_address(req.ip)
            except ValueError:
                return {"status": "error", "message": "Invalid mixer IP address"}
            if req.port is not None and not 1 <= req.port <= 65535:
                return {"status": "error", "message": "Invalid mixer port"}
            # Digital mixer with known IP
            mixer_type = {
                "yamaha_cl5": "yamaha_cl",
                "yamaha_ql": "yamaha_cl",
            }.get(req.mixer_key, req.mixer_key)
            if mixer_type not in {
                "simulator", "behringer_x32", "yamaha_cl", "allen_heath_sq"
            }:
                return {
                    "status": "error",
                    "message": f"{req.mixer_key} was detected, but its OSC profile is not implemented yet"
                }
            new_mixer = AmalynMixerBridge(
                mixer_type=mixer_type,
                channel=1,
                ip_override=req.ip
            )
            if req.port:
                new_mixer.profile['port'] = req.port
            success = new_mixer.connect()
            if success:
                mixer = new_mixer
                return {"status": "connected", "mixer": req.mixer_key, "ip": req.ip}
            return {"status": "error", "message": "Could not connect to mixer"}
        else:
            if req.interface_index is None:
                return {"status": "error", "message": "Select an audio interface first"}
            try:
                import pyaudio
            except ImportError:
                return {"status": "error", "message": "PyAudio is not installed on this machine"}
            if stream is not None:
                stream.stop_stream()
                stream.close()
            if audio_instance is not None:
                audio_instance.terminate()
            audio_instance = pyaudio.PyAudio()
            try:
                stream = audio_instance.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    input=True,
                    input_device_index=req.interface_index,
                    frames_per_buffer=CHUNK
                )
            except (OSError, ValueError):
                audio_instance.terminate()
                audio_instance = None
                raise
            if audio_thread is None or not audio_thread.is_alive():
                audio_thread = threading.Thread(target=audio_engine, daemon=True)
                audio_thread.start()
            analog_monitor = {
                "active": True,
                "interface_index": req.interface_index,
                "interface_name": None
            }
            return {
                "status": "connected",
                "mixer": req.mixer_key,
                "type": "analog",
                "message": "Analog mode active — AMALYN is listening and advising"
            }
    except (OSError, ValueError) as error:
        logger.error("[MIXER] Connection failed: %s", error)
        return {"status": "error", "message": f"Could not start mixer connection: {error}"}


@app.get("/mixer/status")
def mixer_status():
    return {
        "connected": mixer.connected,
        "mixer_type": mixer.mixer_type,
        "ip": mixer.profile["ip"],
        "port": mixer.profile["port"],
        "analog_monitor": dict(analog_monitor)
    }


@app.post("/mixer/disconnect")
def disconnect_mixer():
    global stream, audio_instance, analog_monitor
    mixer.disconnect()
    if stream is not None:
        stream.stop_stream()
        stream.close()
        stream = None
    if audio_instance is not None:
        audio_instance.terminate()
        audio_instance = None
    analog_monitor = {"active": False, "interface_index": None, "interface_name": None}
    return {"status": "disconnected"}


@app.get("/analog/advice")
def get_analog_advice():
    """Return the latest live physical gear advice for analog mixers and outboard racks."""
    with frame_lock:
        advice = latest_frame.get("analog_advice")
        if advice:
            return advice
    return generate_analog_advice("CLEAN", 0.0, -80.0, mixer_profile=analog_manager.get_active_mixer())


# --- ANALOG MIXER USB & CUSTOM MODEL ENDPOINTS ---

class CustomMixerRequest(BaseModel):
    brand: str
    model: str
    key: Optional[str] = None
    category: Optional[str] = "ANALOG_MIXER"
    connection_type: Optional[str] = "USB_AUDIO"
    usb_keywords: Optional[List[str]] = []
    specs: Optional[Dict[str, Any]] = {}
    description: Optional[str] = ""


class MapDeviceRequest(BaseModel):
    device_name: str
    mixer_key: str


class SelectMixerRequest(BaseModel):
    mixer_key: str
    device_name: Optional[str] = None


@app.get("/analog/usb/scan")
def scan_analog_usb():
    """Scan connected USB audio input devices and auto-identify matching analog mixers."""
    return analog_manager.scan_usb_mixers()


@app.get("/analog/mixers")
def list_analog_mixers():
    """List all available built-in and user-added custom analog mixer models."""
    return {
        "mixers": analog_manager.get_all_mixers(),
        "active": analog_manager.get_active_mixer(),
        "device_mappings": analog_manager.device_mappings
    }


@app.post("/analog/mixers/custom")
def create_custom_mixer(req: CustomMixerRequest):
    """Add or update a custom analog mixer model with specific channel strip specs."""
    success, msg, data = analog_manager.add_custom_mixer(req.dict())
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg, "mixer": data}


@app.delete("/analog/mixers/custom/{mixer_key}")
def delete_custom_mixer(mixer_key: str):
    """Delete a user-defined custom analog mixer model."""
    success, msg = analog_manager.delete_custom_mixer(mixer_key)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/analog/device/map")
def map_analog_device(req: MapDeviceRequest):
    """Permanently map a USB audio hardware descriptor to an analog mixer model."""
    success, msg = analog_manager.map_device_to_mixer(req.device_name, req.mixer_key)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg, "active_mixer": analog_manager.get_active_mixer()}


@app.post("/analog/mixer/select")
def select_analog_mixer(req: SelectMixerRequest):
    """Select or switch the active analog mixer model."""
    success = analog_manager.set_active_mixer(req.mixer_key, device_name=req.device_name, manual=True)
    if not success:
        raise HTTPException(status_code=404, detail=f"Mixer profile '{req.mixer_key}' not found")
    return {"status": "success", "active_mixer": analog_manager.get_active_mixer()}


@app.get("/analog/mixer/active")
def get_active_analog_mixer():
    """Get the currently active analog mixer model and its hardware specs."""
    return analog_manager.get_active_mixer()


@app.get("/capabilities")
def capabilities():
    return {
        "mode": "local",
        "digital_mixers": ["behringer_x32", "yamaha_cl", "allen_heath_sq"],
        "analog_monitoring": True,
        "network_discovery": True,
        "cloud_audio_capture": False,
        "notes": [
            "Mixer discovery runs on the machine hosting this API.",
            "Cloud deployments cannot access a user's private LAN or microphone."
        ]
    }

# --- HEALTH ENDPOINT ---
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AMALYN API",
        "audio_capture": stream is not None,
    }


@app.get("/config")
def public_config():
    """Expose only browser-safe configuration needed by Supabase Auth."""
    load_env_file()
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    return {
        "supabase_url": url,
        "supabase_anon_key": key,
    }


@app.get("/")
def login_page():
    return FileResponse(os.path.join(BASE_DIR, "login.html"))


@app.get("/{file_name:path}")
def static_file(file_name: str):
    """Serve portal HTML and static PWA assets from the same Render service."""
    allowed_extensions = {".html", ".json", ".js", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".webp"}
    _, ext = os.path.splitext(file_name)
    if ext.lower() not in allowed_extensions:
        return {"status": "error", "message": "File not found"}
    requested = os.path.join(BASE_DIR, file_name)
    if not os.path.isfile(requested):
        return {"status": "error", "message": "File not found"}
    # Set correct content types for PWA-critical files
    media_types = {
        ".json": "application/json",
        ".js": "application/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".ico": "image/x-icon",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext.lower())
    return FileResponse(requested, media_type=media_type)


if __name__ == "__main__":
    import pyaudio

    p = pyaudio.PyAudio()
    try:
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
    except Exception as error:
        p.terminate()
        raise RuntimeError(f"Unable to open an audio input device: {error}") from error

    audio_thread = threading.Thread(target=audio_engine, daemon=True)
    audio_thread.start()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
