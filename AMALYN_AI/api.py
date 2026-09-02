"""FastAPI service for AMALYN's dashboard, producer, and musician portals."""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from alerts import available_sensitivity_profiles
from engine import AudioEngine
from library import (
    get_perfect_state,
    list_all_microphones,
    list_all_mixers,
    list_all_speakers,
    list_all_venues,
)


logger = logging.getLogger(__name__)
Sensitivity = Literal["early", "balanced", "strict"]


def get_engine(app: FastAPI) -> AudioEngine:
    """Create the audio engine lazily so importing the API never opens a device."""
    engine = getattr(app.state, "engine", None)
    if engine is None:
        engine = AudioEngine(enable_ml=True)
        app.state.engine = engine
    return engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine(app)
    try:
        engine.start()
    except Exception as error:
        # The portals and setup API remain useful while an interface is absent.
        # Health exposes this state so an operator can reconnect it safely.
        logger.warning("Audio capture did not start: %s", error)
    try:
        yield
    finally:
        engine.stop()


app = FastAPI(title="AMALYN TECH API", version="1.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


musician_channels = [
    {"id": 1, "name": "Vocals", "level": 75, "mute": False},
    {"id": 2, "name": "Guitar", "level": 60, "mute": False},
    {"id": 3, "name": "Bass", "level": 55, "mute": False},
    {"id": 4, "name": "Keys", "level": 50, "mute": False},
    {"id": 5, "name": "Drums", "level": 65, "mute": False},
    {"id": 6, "name": "Click", "level": 40, "mute": False},
]
_channels_lock = threading.RLock()


class SetupRequest(BaseModel):
    venue: str
    speaker: str | None = None
    mic: str | None = None
    mixer_type: str | None = None
    sensitivity: Sensitivity | None = None


class AnalysisSettingsUpdate(BaseModel):
    sensitivity: Sensitivity


class MixUpdate(BaseModel):
    channel_id: int
    level: int | None = Field(default=None, ge=0, le=100)
    mute: bool | None = None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    engine = get_engine(app)
    try:
        while True:
            await websocket.send_json(engine.snapshot())
            # 25 fps is smooth in the portals without needlessly saturating the
            # event loop or serialising the same frame dozens of times.
            await asyncio.sleep(0.04)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as error:
        logger.debug("WebSocket closed: %s", error)


@app.post("/setup")
def setup(request: SetupRequest):
    engine = get_engine(app)
    if request.sensitivity is not None:
        engine.set_sensitivity(request.sensitivity)
    return engine.configure(
        venue=request.venue,
        speaker=request.speaker,
        mic=request.mic,
        mixer_type=request.mixer_type,
    )


@app.get("/analysis/settings")
def analysis_settings():
    engine = get_engine(app)
    return {
        "sensitivity": engine.sensitivity,
        "available_sensitivities": available_sensitivity_profiles(),
    }


@app.put("/analysis/settings")
def update_analysis_settings(settings: AnalysisSettingsUpdate):
    engine = get_engine(app)
    engine.set_sensitivity(settings.sensitivity)
    return {"status": "ok", "sensitivity": engine.sensitivity}


@app.get("/library")
def get_library():
    return {
        "speakers": list_all_speakers(),
        "microphones": list_all_microphones(),
        "mixers": list_all_mixers(),
        "venues": list_all_venues(),
    }


@app.get("/sentinel/status")
def sentinel_status():
    return get_engine(app).snapshot()["sentinel"]


@app.get("/musician/channels")
def get_channels():
    with _channels_lock:
        return {"channels": deepcopy(musician_channels)}


@app.post("/musician/mix")
def update_mix(update: MixUpdate):
    with _channels_lock:
        channel = next((item for item in musician_channels if item["id"] == update.channel_id), None)
        if channel is None:
            raise HTTPException(status_code=404, detail=f"Channel {update.channel_id} not found")
        if update.level is not None:
            channel["level"] = update.level
        if update.mute is not None:
            channel["mute"] = update.mute
        return {"status": "ok", "channel_id": update.channel_id, "channel": deepcopy(channel)}


@app.post("/mixer/safe")
def trigger_safe():
    if not get_engine(app).apply_safe_profile():
        raise HTTPException(status_code=503, detail="Mixer control is not connected")
    return {"status": "Safe profile applied"}


@app.get("/health")
def health():
    engine = get_engine(app)
    return {
        "status": "ok" if engine.is_running else "degraded",
        "audio_running": engine.is_running,
        "audio_error": engine.last_error,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
