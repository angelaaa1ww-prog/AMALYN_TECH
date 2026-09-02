EQ_BANDS = [
    {"name": "Sub Bass",  "min": 20,   "max": 60,    "problem": "Rumble / Mud"},
    {"name": "Bass",      "min": 60,   "max": 250,   "problem": "Boominess"},
    {"name": "Low Mid",   "min": 250,  "max": 500,   "problem": "Muddiness"},
    {"name": "Mid",       "min": 500,  "max": 2000,  "problem": "Honk / Nasality"},
    {"name": "High Mid",  "min": 2000, "max": 4000,  "problem": "Harshness / Feedback"},
    {"name": "Presence",  "min": 4000, "max": 8000,  "problem": "Sibilance / Feedback"},
    {"name": "Air",       "min": 8000, "max": 20000, "problem": "Hiss"},
]


def get_eq_band(frequency):
    for band in EQ_BANDS:
        if band["min"] <= frequency <= band["max"]:
            return band
    return {"name": "Unknown", "problem": "Unknown"}


def calculate_cut(magnitude_db, threshold_db=-25):
    excess = magnitude_db - threshold_db
    if excess <= 3:
        return -3
    elif excess <= 6:
        return -6
    elif excess <= 10:
        return -9
    else:
        return -12


def suggest_eq(danger_freq, danger_mag, status):
    # A status can be supplied by an advisory subsystem (for example ML) that
    # does not identify one defensible spectral peak.  Never generate or send a
    # meaningless EQ command at 0 Hz in that case.
    if status == "CLEAN" or danger_freq is None or danger_mag is None or danger_freq <= 0:
        return None

    band = get_eq_band(danger_freq)
    cut = calculate_cut(danger_mag)
    q_value = 1.4 if danger_freq > 1000 else 0.8
    filter_type = "Notch" if danger_freq > 1000 else "Bell"

    return {
        "frequency": round(danger_freq, 1),
        "band_name": band["name"],
        "problem": band["problem"],
        "cut_db": cut,
        "q_value": q_value,
        "filter_type": filter_type,
        "status": status
    }


def print_eq_suggestion(suggestion):
    if not suggestion:
        return
    print(f"\n{'='*50}")
    print(f"[EQ SUGGESTION]")
    print(f"{'='*50}")
    print(f"   Frequency   : {suggestion['frequency']}Hz")
    print(f"   EQ Band     : {suggestion['band_name']}")
    print(f"   Problem     : {suggestion['problem']}")
    print(f"   Cut         : {suggestion['cut_db']}dB")
    print(f"   Q Value     : {suggestion['q_value']}")
    print(f"   Filter Type : {suggestion['filter_type']}")
    print(f"{'='*50}\n")
