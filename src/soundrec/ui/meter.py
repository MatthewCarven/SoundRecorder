"""The level meter's behaviour: a digital peak meter for two channels.

Peaks come in a few times a second (each the loudest sample since the last);
the bar jumps up to a louder peak at once and falls back at FALL_DB_PER_SECOND,
and a hold mark stays at the loudest peak for HOLD_SECONDS before following
the bar down. Levels are dBFS, floored at FLOOR_DB.

A mono sound shows on both bars; with more than two channels, the odd ones
(1, 3...) feed the top bar and the even ones the bottom, as left and right.
"""

from __future__ import annotations

import math

import numpy as np

FLOOR_DB = -60.0
FALL_DB_PER_SECOND = 20.0
HOLD_SECONDS = 1.5


def pair(peaks) -> tuple[float, float]:
    """Per-channel peaks (0 to 1, or over) as (left, right)."""
    peaks = np.asarray(peaks, np.float64).ravel()
    if not len(peaks):
        return 0.0, 0.0
    if len(peaks) == 1:
        return float(peaks[0]), float(peaks[0])
    return float(peaks[0::2].max()), float(peaks[1::2].max())


def decibels(peak: float) -> float:
    return max(20 * math.log10(peak), FLOOR_DB) if peak > 0 else FLOOR_DB


class Meter:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.levels = [FLOOR_DB, FLOOR_DB]
        self.holds = [FLOOR_DB, FLOOR_DB]
        self._held_at = [0.0, 0.0]
        self._last: float | None = None

    def update(self, peaks, now: float) -> None:
        """New peaks (per channel, since the last update) at time `now`, seconds."""
        fall = 0.0 if self._last is None else (now - self._last) * FALL_DB_PER_SECOND
        self._last = now
        for i, peak in enumerate(pair(peaks)):
            db = decibels(peak)
            self.levels[i] = max(db, self.levels[i] - fall)
            if db >= self.holds[i]:
                self.holds[i], self._held_at[i] = db, now
            elif now - self._held_at[i] > HOLD_SECONDS:
                self.holds[i] = max(self.levels[i], FLOOR_DB)

    @property
    def reading(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """((left, right) levels, (left, right) holds) in dBFS."""
        return (self.levels[0], self.levels[1]), (self.holds[0], self.holds[1])
