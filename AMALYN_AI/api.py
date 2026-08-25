import pyaudio
import numpy as np
import asyncio
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge
from library import get_perfect_state, list_all_speakers, list_all_microphones, list_all_mixers, list_all_venues

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
    "perfect_state": None
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

last_status = "CLEAN"
last_correction_freq = 0
current_perfect_state = None


class SetupRequest(BaseModel):
    venue: str
    speaker: str = None
    mic: str = None
    mixer_type: str = None


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
                "perfect_state": current_perfect_state
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


@app.post("/setup")
def setup(request: SetupRequest):
    global current_perfect_state
    current_perfect_state = get_perfect_state(
        venue_type=request.venue,
        speaker_key=request.speaker,
        mic_key=request.mic,
        mixer_key=request.mixer_type
    )
    print(f"\n[SETUP] Perfect State loaded:")
    print(f"  Venue   : {current_perfect_state['venue']}")
    print(f"  Speaker : {current_perfect_state['speaker']}")
    print(f"  Mic     : {current_perfect_state['microphone']}")
    print(f"  Mixer   : {current_perfect_state['mixer']}")
    print(f"  EQ Bands: {len(current_perfect_state['combined_eq'])}")
    return current_perfect_state


@app.get("/library")
def get_library():
    return {
        "speakers": list_all_speakers(),
        "microphones": list_all_microphones(),
        "mixers": list_all_mixers(),
        "venues": list_all_venues()
    }


@app.get("/health")
def health():
    return {"status": "AMALYN API Running"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")