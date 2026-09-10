# session_db.py — AMALYN Session & Progress Persistence

from datetime import datetime
from bson import ObjectId
from database import (
    sessions_col, events_col, presets_col,
    show_files_col, sync_events_col, sync_sessions_col,
    get_timestamp
)


# ── Sessions ───────────────────────────────────────────────────────────
async def create_session(user_id: str, setup: dict) -> str:
    """Create a new recording session. Called when engineer loads Perfect State."""
    session = {
        "user_id": user_id,
        "venue": setup.get("venue"),
        "speaker": setup.get("speaker"),
        "mic": setup.get("mic"),
        "mixer": setup.get("mixer"),
        "mixer_ip": setup.get("mixer_ip"),
        "created_at": get_timestamp(),
        "ended_at": None,
        "total_events": 0,
        "warnings": 0,
        "criticals": 0,
        "corrections": 0,
        "health_score_avg": 100,
        "status": "active"
    }
    result = await sessions_col.insert_one(session)
    return str(result.inserted_id)


async def end_session(session_id: str, stats: dict):
    """Mark session as ended with final stats."""
    await sessions_col.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {
            "ended_at": get_timestamp(),
            "status": "complete",
            **stats
        }}
    )


async def get_user_sessions(user_id: str, limit: int = 20):
    """Get recent sessions for a user."""
    sessions = []
    cursor = sessions_col.find(
        {"user_id": user_id},
        sort=[("created_at", -1)],
        limit=limit
    )
    async for s in cursor:
        s["id"] = str(s["_id"])
        del s["_id"]
        sessions.append(s)
    return sessions


async def get_session(session_id: str):
    """Get a single session by ID."""
    s = await sessions_col.find_one({"_id": ObjectId(session_id)})
    if s:
        s["id"] = str(s["_id"])
        del s["_id"]
    return s


# ── Events (sync — called from audio engine thread) ────────────────────
def log_event_db(session_id: str, user_id: str, status: str,
                 danger_freq: float, danger_mag: float,
                 suggestion: dict = None, message: str = None):
    """
    Save a WARNING/CRITICAL event to MongoDB.
    Uses sync client because audio engine runs in a thread.
    """
    try:
        event = {
            "session_id": session_id,
            "user_id": user_id,
            "status": status,
            "frequency_hz": round(danger_freq, 1),
            "magnitude_db": round(danger_mag, 1),
            "suggestion": suggestion,
            "message": message,
            "timestamp": get_timestamp()
        }
        sync_events_col.insert_one(event)

        # Update session counters
        update = {"$inc": {"total_events": 1}}
        if status == "WARNING":
            update["$inc"]["warnings"] = 1
        elif status == "CRITICAL":
            update["$inc"]["criticals"] = 1

        sync_sessions_col.update_one(
            {"_id": ObjectId(session_id)},
            update
        )
    except Exception as e:
        print(f"[DB] Event log error: {e}")


async def get_session_events(session_id: str):
    """Get all events for a session."""
    events = []
    cursor = events_col.find(
        {"session_id": session_id},
        sort=[("timestamp", -1)]
    )
    async for e in cursor:
        e["id"] = str(e["_id"])
        del e["_id"]
        events.append(e)
    return events


# ── Channel Presets ────────────────────────────────────────────────────
async def save_channel_preset(user_id: str, name: str,
                               channels: list, venue_key: str = None):
    """Save a musician's IEM mix preset."""
    existing = await presets_col.find_one({
        "user_id": user_id,
        "name": name
    })
    preset = {
        "user_id": user_id,
        "name": name,
        "venue_key": venue_key,
        "channels": channels,
        "updated_at": get_timestamp()
    }
    if existing:
        await presets_col.update_one(
            {"_id": existing["_id"]},
            {"$set": preset}
        )
        return str(existing["_id"])
    else:
        preset["created_at"] = get_timestamp()
        result = await presets_col.insert_one(preset)
        return str(result.inserted_id)


async def get_user_presets(user_id: str, venue_key: str = None):
    """Get saved presets for a user."""
    query = {"user_id": user_id}
    if venue_key:
        query["venue_key"] = venue_key
    presets = []
    async for p in presets_col.find(query, sort=[("updated_at", -1)]):
        p["id"] = str(p["_id"])
        del p["_id"]
        presets.append(p)
    return presets


async def delete_preset(preset_id: str, user_id: str):
    """Delete a preset (only if owned by user)."""
    await presets_col.delete_one({
        "_id": ObjectId(preset_id),
        "user_id": user_id
    })


# ── Show Files ─────────────────────────────────────────────────────────
async def save_show_file(user_id: str, name: str, data: dict):
    """Save a complete show configuration."""
    show = {
        "user_id": user_id,
        "name": name,
        "created_at": get_timestamp(),
        "updated_at": get_timestamp(),
        **data
    }
    result = await show_files_col.insert_one(show)
    return str(result.inserted_id)


async def get_show_files(user_id: str):
    """Get all saved show files for a user."""
    shows = []
    async for s in show_files_col.find(
        {"user_id": user_id},
        sort=[("updated_at", -1)]
    ):
        s["id"] = str(s["_id"])
        del s["_id"]
        shows.append(s)
    return shows


async def get_show_file(show_id: str, user_id: str):
    """Get a single show file."""
    s = await show_files_col.find_one({
        "_id": ObjectId(show_id),
        "user_id": user_id
    })
    if s:
        s["id"] = str(s["_id"])
        del s["_id"]
    return s


async def delete_show_file(show_id: str, user_id: str):
    """Delete a show file."""
    await show_files_col.delete_one({
        "_id": ObjectId(show_id),
        "user_id": user_id
    })


# ── User Progress / Dashboard ──────────────────────────────────────────
async def get_user_stats(user_id: str):
    """
    Get lifetime stats for a user.
    Shown on their dashboard when they log in.
    """
    total_sessions = await sessions_col.count_documents({"user_id": user_id})
    total_events = await events_col.count_documents({"user_id": user_id})
    total_criticals = await events_col.count_documents({
        "user_id": user_id, "status": "CRITICAL"
    })
    total_presets = await presets_col.count_documents({"user_id": user_id})
    total_shows = await show_files_col.count_documents({"user_id": user_id})

    # Most common problem frequency
    pipeline = [
        {"$match": {"user_id": user_id, "status": {"$in": ["WARNING","CRITICAL"]}}},
        {"$group": {
            "_id": {"$round": ["$frequency_hz", -2]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 1}
    ]
    freq_result = []
    async for doc in events_col.aggregate(pipeline):
        freq_result.append(doc)

    top_freq = freq_result[0]["_id"] if freq_result else None

    # Recent sessions
    recent = await get_user_sessions(user_id, limit=5)

    return {
        "total_sessions": total_sessions,
        "total_events": total_events,
        "total_criticals": total_criticals,
        "total_presets": total_presets,
        "total_shows": total_shows,
        "top_problem_frequency": top_freq,
        "recent_sessions": recent
    }