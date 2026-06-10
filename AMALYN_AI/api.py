import pyaudio
import numpy as np
import asyncio
import copy
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from config import FORMAT, CHANNELS, RATE, CHUNK
from audio_utils import get_frequency_map, get_dominant_frequency
from alerts import check_for_feedback
from eq_engine import suggest_eq
from logger import log_event
from mixer import AmalynMixerBridge

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

latest_frame = {
    "status": "CLEAN",
    "dominant_freq": 0.0,
    "dominant_mag": -80.0,
    "danger_freq": 0.0,
    "danger_mag": -80.0,
    "frequencies": [],
    "magnitudes": [],
    "suggestion": None,
    "mixer_corrections": {"total_corrections": 0, "corrections": []}
}
frame_lock = threading.Lock()

active_queues = set()
main_loop = None

def push_to_queue(q, frame):
    try:
        if q.full():
            q.get_nowait()
        q.put_nowait(frame)
    except Exception:
        pass

try:
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
except Exception as e:
    print(f"[ENGINE] WARNING: Audio device init failed: {e}")
    stream = None

mixer = AmalynMixerBridge(mixer_type="simulator", channel=1)
mixer.connect()

last_status = "CLEAN"
last_correction_freq = 0


def audio_engine():
    global last_status, last_correction_freq, main_loop

    if stream is None:
        print("[ENGINE] No audio stream available — engine not started")
        return
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
                "mixer_corrections": {
                    "total_corrections": mixer.get_corrections_summary()["total_corrections"],
                    "corrections": mixer.get_corrections_summary()["corrections"][-20:]
                }
            }

            with frame_lock:
                latest_frame.update(frame)

            if main_loop and active_queues:
                for q in list(active_queues):
                    main_loop.call_soon_threadsafe(push_to_queue, q, frame)

        except OSError:
            continue
        except Exception as e:
            print(f"[ENGINE] Error: {e}")
            continue


audio_thread = threading.Thread(target=audio_engine, daemon=True)
audio_thread.start()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global main_loop
    if main_loop is None:
        main_loop = asyncio.get_running_loop()

    await websocket.accept()
    print("[WS] Client connected")

    # Send current snapshot immediately on connect
    with frame_lock:
        init_frame = copy.deepcopy(latest_frame)
    await websocket.send_text(json.dumps(init_frame))

    queue = asyncio.Queue(maxsize=1)
    active_queues.add(queue)
    try:
        while True:
            frame = await queue.get()
            await websocket.send_text(json.dumps(frame))
    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")
    finally:
        active_queues.remove(queue)



@app.get("/health")
def health():
    return {"status": "AMALYN API Running"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")