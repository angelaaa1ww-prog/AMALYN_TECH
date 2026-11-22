# database.py - AMALYN MongoDB connection

import os
from datetime import datetime

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"), override=True)
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

MONGO_URI = os.getenv("MONGODB_URI", os.getenv("MONGO_URI", "")).strip()
if not MONGO_URI:
    raise RuntimeError("MONGODB_URI must be configured in .env before starting the API")

DB_NAME = os.getenv("MONGODB_DATABASE", "amalyn").strip() or "amalyn"
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
    os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "3000")
)

async_client = AsyncIOMotorClient(
    MONGO_URI,
    serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
)
async_db = async_client[DB_NAME]

sync_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
)
sync_db = sync_client[DB_NAME]

users_col = async_db["users"]
sessions_col = async_db["sessions"]
presets_col = async_db["presets"]
show_files_col = async_db["show_files"]
events_col = async_db["events"]
venues_col = async_db["venues"]

sync_events_col = sync_db["events"]
sync_sessions_col = sync_db["sessions"]


async def init_indexes():
    await users_col.create_index("email", unique=True)
    await sessions_col.create_index([("user_id", 1), ("created_at", -1)])
    await events_col.create_index([("session_id", 1), ("timestamp", -1)])
    await presets_col.create_index([("user_id", 1), ("venue_key", 1)])
    await show_files_col.create_index([("user_id", 1), ("created_at", -1)])


def get_timestamp():
    return datetime.utcnow().isoformat()
