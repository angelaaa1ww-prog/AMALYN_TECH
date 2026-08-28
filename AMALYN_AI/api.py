from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine import AudioEngine
from library import (
    list_all_microphones,
    list_all_mixers,
    list_all_speakers,
    list_all_venues,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
engine = AudioEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Keep metadata endpoints available even when an audio device is missing."""
    try:
        engine.start()
    except RuntimeError as error:
        logger.warning("Audio engine unavailable: %s", error)
    except Exception:
        logger.exception("Audio engine failed to start")
    try:
        yield
    finally:
        engine.stop()


app = FastAPI(title="AMALYN TECH API", lifespan=lifespan)
app.state.engine = engine
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


class SetupRequest(BaseModel):
    venue: str
    speaker: str | None = None
    mic: str | None = None
    mixer_type: str | None = None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(engine.snapshot())
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("WebSocket client error")


@app.post("/setup")
def setup(request: SetupRequest):
    return engine.configure(
        venue=request.venue,
        speaker=request.speaker,
        mic=request.mic,
        mixer_type=request.mixer_type,
    )


@app.get("/library")
def get_library():
    return {
        "speakers": list_all_speakers(),
        "microphones": list_all_microphones(),
        "mixers": list_all_mixers(),
        "venues": list_all_venues(),
    }


@app.get("/health")
def health():
    return {
        "status": "ok" if engine.is_running else "degraded",
        "audio_engine": "running" if engine.is_running else "unavailable",
        "detail": engine.last_error,
    }


if __name__ == "__main__":
    # The dashboard is designed for local control of a local audio system.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
