import numpy as np
from config import RATE, CHUNK


def get_frequency_map(audio_data):
    fft_result = np.fft.rfft(audio_data)
    magnitudes = np.abs(fft_result)
    magnitudes_db = 20 * np.log10(magnitudes + 1e-10)
    magnitudes_db -= 20 * np.log10(32768)
    frequencies = np.fft.rfftfreq(CHUNK, d=1.0 / RATE)
    return frequencies, magnitudes_db


def get_dominant_frequency(frequencies, magnitudes_db):
    peak_index = np.argmax(magnitudes_db)
    dominant_freq = frequencies[peak_index]
    dominant_mag = magnitudes_db[peak_index]
    return dominant_freq, dominant_mag