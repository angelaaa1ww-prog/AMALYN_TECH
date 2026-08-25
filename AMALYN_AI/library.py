import json
import os

LIBRARY_PATH = os.path.join(os.path.dirname(__file__), 'library.json')

with open(LIBRARY_PATH, 'r') as f:
    LIBRARY = json.load(f)


def get_speaker(model_key):
    return LIBRARY['speakers'].get(model_key, None)


def get_microphone(model_key):
    return LIBRARY['microphones'].get(model_key, None)


def get_mixer(model_key):
    return LIBRARY['mixers'].get(model_key, None)


def get_venue(venue_type):
    return LIBRARY['venues'].get(venue_type, None)


def get_perfect_state(venue_type, speaker_key=None, mic_key=None, mixer_key=None):
    perfect_state = {
        "venue": None,
        "speaker": None,
        "microphone": None,
        "mixer": None,
        "combined_eq": [],
        "gain_staging": None,
        "max_spl": None,
        "warnings": []
    }

    venue = get_venue(venue_type)
    if venue:
        perfect_state['venue'] = venue['name']
        perfect_state['combined_eq'].extend(venue['recommended_eq'])
        perfect_state['max_spl'] = venue.get('max_spl_db')
    else:
        perfect_state['warnings'].append(f"Unknown venue: {venue_type}")

    if speaker_key:
        speaker = get_speaker(speaker_key)
        if speaker:
            perfect_state['speaker'] = f"{speaker['brand']} {speaker['model']}"
            perfect_state['combined_eq'].extend(speaker['recommended_eq'])
        else:
            perfect_state['warnings'].append(f"Unknown speaker: {speaker_key}")

    if mic_key:
        mic = get_microphone(mic_key)
        if mic:
            perfect_state['microphone'] = f"{mic['brand']} {mic['model']}"
            perfect_state['combined_eq'].extend(mic['recommended_eq'])
        else:
            perfect_state['warnings'].append(f"Unknown mic: {mic_key}")

    if mixer_key:
        mixer = get_mixer(mixer_key)
        if mixer:
            perfect_state['mixer'] = f"{mixer['brand']} {mixer['model']}"
            perfect_state['gain_staging'] = mixer['recommended_gain_staging']
        else:
            perfect_state['warnings'].append(f"Unknown mixer: {mixer_key}")

    # Merge EQ — take deepest cut when same frequency appears twice
    merged = {}
    for eq in perfect_state['combined_eq']:
        freq = eq['frequency']
        if freq not in merged:
            merged[freq] = eq
        else:
            if eq['cut_db'] < merged[freq]['cut_db']:
                merged[freq] = eq

    perfect_state['combined_eq'] = sorted(merged.values(), key=lambda x: x['frequency'])
    return perfect_state


def list_all_speakers():
    return list(LIBRARY['speakers'].keys())


def list_all_microphones():
    return list(LIBRARY['microphones'].keys())


def list_all_mixers():
    return list(LIBRARY['mixers'].keys())


def list_all_venues():
    return list(LIBRARY['venues'].keys())