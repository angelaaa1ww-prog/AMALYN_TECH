# database.py — AMALYN MongoDB Connection

import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from datetime import datetime

# ── Connection String ──────────────────────────────────────────────────
# Put your MongoDB connection string in a .env file:
# MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/amalyn
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://YOUR_USERNAME:YOUR_PASSWORD@YOUR_CLUSTER.mongodb.net/amalyn"
)

DB_NAME = "amalyn"

# Async client — used by FastAPI endpoints
async_client = AsyncIOMotorClient(MONGO_URI)
async_db = async_client[DB_NAME]

# Sync client — used by background audio engine thread
sync_client = MongoClient(MONGO_URI)
sync_db = sync_client[DB_NAME]

# ── Collections ────────────────────────────────────────────────────────
# Async
users_col       = async_db["users"]
sessions_col    = async_db["sessions"]
presets_col     = async_db["presets"]
show_files_col  = async_db["show_files"]
events_col      = async_db["events"]
venues_col      = async_db["venues"]

# Sync (for audio engine thread)
sync_events_col  = sync_db["events"]
sync_sessions_col = sync_db["sessions"]


async def init_indexes():
    """
    Create database indexes on startup.
    Ensures fast queries and unique constraints.
    """
    # Users — unique email
    await users_col.create_index("email", unique=True)

    # Sessions — query by user and date
    await sessions_col.create_index([("user_id", 1), ("created_at", -1)])

    # Events — query by session
    await events_col.create_index([("session_id", 1), ("timestamp", -1)])

    # Presets — query by user and venue
    await presets_col.create_index([("user_id", 1), ("venue_key", 1)])

    # Show files — query by user
    await show_files_col.create_index([("user_id", 1), ("created_at", -1)])

    print("[DB] MongoDB indexes created")


def get_timestamp():
    return datetime.utcnow().isoformat()