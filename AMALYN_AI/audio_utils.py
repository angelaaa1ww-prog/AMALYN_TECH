import numpy as np

from config import RATE


FULL_SCALE_INT16 = float(np.iinfo(np.int16).max)
MIN_DBFS = -120.0

def get_frequency_map(audio_data, rate=RATE):
    """
    Takes raw audio data from the microphone,
    runs FFT on it, and returns the frequency
    map with magnitudes in decibels.
    
    Returns:
        frequencies (array): frequency bins in Hz
        magnitudes_db (array): magnitude of each frequency in dB
    """
    samples = np.asarray(audio_data, dtype=np.float64)
    if samples.ndim != 1 or samples.size == 0:
        raise ValueError("audio_data must be a non-empty one-dimensional array")
    if rate <= 0:
        raise ValueError("rate must be positive")

    # Compensate for the Hann window so a full-scale, bin-centred sine is 0 dBFS.
    window = np.hanning(samples.size)
    window_sum = window.sum()
    if window_sum == 0:
        window = np.ones(samples.size)
        window_sum = float(samples.size)

    magnitudes = np.abs(np.fft.rfft(samples * window)) / window_sum
    if magnitudes.size > 1:
        # rFFT contains only positive-frequency energy. Restore the omitted half,
        # excluding DC and Nyquist bins.
        positive_bins = slice(1, -1) if samples.size % 2 == 0 else slice(1, None)
        magnitudes[positive_bins] *= 2

    magnitudes_db = 20 * np.log10(
        np.maximum(magnitudes / FULL_SCALE_INT16, 10 ** (MIN_DBFS / 20))
    )
    frequencies = np.fft.rfftfreq(samples.size, d=1.0 / rate)

    return frequencies, magnitudes_db


def get_dominant_frequency(frequencies, magnitudes_db):
    """
    Finds the single loudest frequency in the current audio frame.
    
    Returns:
        dominant_freq (float): the loudest frequency in Hz
        dominant_mag (float): its magnitude in dB
    """
    if len(frequencies) != len(magnitudes_db) or not len(frequencies):
        raise ValueError("frequencies and magnitudes_db must be non-empty and aligned")

    # Ignore DC offset: it is not an audible feedback frequency.
    start_index = 1 if len(frequencies) > 1 else 0
    peak_index = start_index + np.argmax(magnitudes_db[start_index:])
    dominant_freq = frequencies[peak_index]
    dominant_mag = magnitudes_db[peak_index]

    return dominant_freq, dominant_mag
