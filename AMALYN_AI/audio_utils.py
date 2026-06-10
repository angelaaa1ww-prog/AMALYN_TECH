import numpy as np
from config import RATE, CHUNK

def get_frequency_map(audio_data):
    """
    Takes raw audio data from the microphone,
    runs FFT on it, and returns the frequency
    map with magnitudes in decibels.
    
    Returns:
        frequencies (array): frequency bins in Hz
        magnitudes_db (array): magnitude of each frequency in dB
    """
    # Run Fast Fourier Transform on the audio data
    window = np.hanning(len(audio_data))
    fft_result = np.fft.rfft(audio_data * window)

    # Get the magnitude of each frequency component
    magnitudes = np.abs(fft_result)

    # Convert magnitude to decibels (dB scale)
    # Adding small value (1e-10) to avoid log(0) error
    magnitudes_db = 20 * np.log10(magnitudes + 1e-10)

    # Normalize so 0dB = maximum possible value for 16-bit audio
    magnitudes_db -= 20 * np.log10(32768)

    # Generate the corresponding frequency values for each bin
    frequencies = np.fft.rfftfreq(CHUNK, d=1.0 / RATE)

    return frequencies, magnitudes_db


def get_dominant_frequency(frequencies, magnitudes_db):
    """
    Finds the single loudest frequency in the current audio frame.
    
    Returns:
        dominant_freq (float): the loudest frequency in Hz
        dominant_mag (float): its magnitude in dB
    """
    peak_index = np.argmax(magnitudes_db)
    dominant_freq = frequencies[peak_index]
    dominant_mag = magnitudes_db[peak_index]

    return dominant_freq, dominant_mag