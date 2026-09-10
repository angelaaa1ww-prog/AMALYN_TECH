# models.py — AMALYN Database Models

from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime


# ── Auth ───────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "engineer"


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar: str
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── Session ────────────────────────────────────────────────────────────
class SessionCreate(BaseModel):
    user_id: str
    venue: Optional[str] = None
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer: Optional[str] = None
    mixer_ip: Optional[str] = None


class SessionEvent(BaseModel):
    session_id: str
    user_id: str
    status: str          # WARNING / CRITICAL / SENTINEL
    frequency_hz: float
    magnitude_db: float
    suggestion: Optional[Dict] = None
    message: Optional[str] = None


# ── Presets ────────────────────────────────────────────────────────────
class ChannelPreset(BaseModel):
    user_id: str
    name: str            # "My Sunday Mix" / "Drums Mix"
    venue_key: Optional[str] = None
    channels: List[Dict]  # [{id, name, level, mute}]


class ShowFile(BaseModel):
    user_id: str
    name: str            # "Sunday Service March 2026"
    venue: Optional[str] = None
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer: Optional[str] = None
    perfect_state_eq: Optional[List] = None
    channel_presets: Optional[List] = None
    notes: Optional[str] = None


# ── Setup Request ──────────────────────────────────────────────────────
class SetupRequest(BaseModel):
    venue: str
    speaker: Optional[str] = None
    mic: Optional[str] = None
    mixer_type: Optional[str] = None


class MixUpdate(BaseModel):
    channel_id: int
    level: Optional[int] = None
    mute: Optional[bool] = None


class ConnectRequest(BaseModel):
    mixer_key: str
    ip: Optional[str] = None
    port: Optional[int] = None
    interface_index: Optional[int] = None
    