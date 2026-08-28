import os
import json
import time
import atexit
import threading
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)


def get_log_filename():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return os.path.join(LOG_DIR, f'session_{timestamp}.json')


LOG_FILE = get_log_filename()
session_events = []
session_start = datetime.now().isoformat()
_last_save_time = 0
_session_lock = threading.RLock()


def log_event(status, danger_freq, danger_mag, suggestion=None):
    global _last_save_time
    if status == "CLEAN":
        return

    event = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "frequency_hz": round(danger_freq, 1),
        "magnitude_db": round(danger_mag, 1),
        "eq_suggestion": suggestion if suggestion else None
    }

    with _session_lock:
        session_events.append(event)
        now = time.time()
        if now - _last_save_time >= 5:
            save_session()
            _last_save_time = now
    print(f"\n[LOG] Event saved -- {status} at {danger_freq:.0f}Hz ({danger_mag:.1f}dB)")


def save_session():
    with _session_lock:
        session_data = {
            "session_start": session_start,
            "session_end": datetime.now().isoformat(),
            "total_events": len(session_events),
            "events": session_events
        }
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=4)


def print_session_summary():
    print("\n" + "=" * 50)
    print("   AMALYN TECH -- Session Summary")
    print("=" * 50)
    print(f"   Session Start : {session_start}")
    print(f"   Session End   : {datetime.now().isoformat()}")
    print(f"   Total Events  : {len(session_events)}")

    if session_events:
        warnings = [e for e in session_events if e['status'] == 'WARNING']
        criticals = [e for e in session_events if e['status'] == 'CRITICAL']
        print(f"   Warnings      : {len(warnings)}")
        print(f"   Criticals     : {len(criticals)}")
        freqs = [e['frequency_hz'] for e in session_events]
        if freqs:
            most_common = max(set(freqs), key=freqs.count)
            print(f"   Problem Freq  : {most_common}Hz (most repeated)")
    else:
        print("   No events recorded this session")

    print(f"\n   Log saved to  : {LOG_FILE}")
    print("=" * 50 + "\n")


atexit.register(save_session)
