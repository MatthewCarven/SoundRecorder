"""Test signals and the measurements the converter tests make on them."""

import numpy as np


def sine(freq, rate, seconds, amplitude=0.5, phase=0.0, channels=1):
    n = int(round(rate * seconds))
    x = amplitude * np.sin(2 * np.pi * freq * np.arange(n) / rate + phase)
    return np.repeat(x.astype(np.float32)[:, None], channels, axis=1)


def fit(y, freq, rate, start=0):
    """Least-squares fit of a sine at exactly `freq` to y (1-D), with sample 0
    of y at time start/rate. Returns (amplitude, phase, worst residual)."""
    t = 2 * np.pi * freq * (start + np.arange(len(y))) / rate
    basis = np.stack([np.sin(t), np.cos(t)], axis=1)
    (a, b), *_ = np.linalg.lstsq(basis, y.astype(np.float64), rcond=None)
    residual = y - basis @ np.array([a, b])
    return float(np.hypot(a, b)), float(np.arctan2(b, a)), float(np.max(np.abs(residual)))


def peak_frequency(y, rate):
    """The strongest frequency in y, to a small fraction of a bin (Hann window,
    parabola through the log magnitudes around the peak)."""
    window = np.hanning(len(y))
    spectrum = np.abs(np.fft.rfft(y * window))
    k = int(np.argmax(spectrum[1:-1])) + 1
    a, b, c = np.log(spectrum[k - 1:k + 2])
    offset = 0.5 * (a - c) / (a - 2 * b + c)
    return (k + offset) * rate / len(y)


def rms_db(y):
    return 20 * np.log10(np.sqrt(np.mean(np.square(y.astype(np.float64)))))
