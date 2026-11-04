"""Edit and Effects: 3.1's ten commands, on the working copy.

Each one reads the sound's take and writes a new one, block by block, so an
hour-long sound costs no memory, and a failure part way leaves the sound as it
was: the Document swaps the new take in only once it's finished. Undo is 3.1's:
Revert reloads the saved file.

The working copy is float, so nothing clips here. Increase Volume then
Decrease Volume gives the sound back (to float32's rounding), and overs are
clipped only when saved to a format that can't hold them (output.Quantiser).

Files inserted or mixed in are converted to the sound's rate and channels on
the way: fit_channels, then soxr.
"""

from __future__ import annotations

from itertools import chain

import numpy as np
import soundfile as sf

from .convert import Resampler, fit_channels
from .ffmpeg import readable
from .takes import Take

BLOCK = 1 << 16
VOLUME_STEP = 1.25    # Increase Volume (by 25%); Decrease divides by it, so each undoes the other
SPEED_STEP = 2        # Increase Speed (by 100%) halves the length; Decrease doubles it
ECHO_DELAYS_MS = tuple(range(50, 501, 50))  # Add Echo's choices: one repeat, this much later,
ECHO_LEVEL = 0.5      # at half the level (-6 dB). 3.1's own figures aren't known; at 250 ms,
                      # Matthew calls it a close match from memory (2026-11-04)


def _build(rate: int, channels: int, blocks, edit: str) -> Take:
    """A finished take of `blocks`, or nothing at all if making it fails."""
    out = Take.create(rate, channels, edit=edit)
    try:
        for block in blocks:
            if len(block):
                out.write(block)
        out.finish()
    except BaseException:
        out.discard()
        raise
    return out


def _range(take: Take, start: int, stop: int):
    for at in range(start, stop, BLOCK):
        yield take.read(at, min(BLOCK, stop - at))


def file_blocks(path, rate: int, channels: int):
    """A sound file's blocks at the sound's rate and channels."""
    with readable(path) as source, sf.SoundFile(str(source)) as f:
        resampler = Resampler(f.samplerate, rate, channels)
        for block in f.blocks(BLOCK, dtype="float32", always_2d=True):
            yield resampler.process(fit_channels(block, channels))
        yield resampler.flush()


# -- Edit -------------------------------------------------------------------------

def convert(take: Take, rate: int, channels: int) -> Take:
    """The sound at another rate or channel layout: channels first, by the one
    rule (fit_channels), so a down-mix resamples fewer of them; then soxr."""
    resampler = Resampler(take.rate, rate, channels)

    def converted():
        for block in _range(take, 0, take.frames):
            yield resampler.process(fit_channels(block, channels))
        yield resampler.flush()

    return _build(rate, channels, converted(), "convert")


def insert(take: Take, at: int, blocks) -> Take:
    """`blocks` (in the take's format) put in at frame `at`; what was there moves along."""
    return _build(take.rate, take.channels,
                  chain(_range(take, 0, at), blocks, _range(take, at, take.frames)), "insert")


def mix(take: Take, at: int, blocks) -> Take:
    """`blocks` added to the sound from frame `at`, making it longer if they run past the end."""
    def mixed():
        yield from _range(take, 0, at)
        p = at
        for block in blocks:
            if not len(block):
                continue
            mine = take.read(p, len(block))
            if len(mine) < len(block):
                mine = np.vstack((mine, np.zeros((len(block) - len(mine), take.channels), np.float32)))
            yield mine + block
            p += len(block)
        yield from _range(take, p, take.frames)

    return _build(take.rate, take.channels, mixed(), "mix")


def delete_before(take: Take, at: int) -> Take:
    return _build(take.rate, take.channels, _range(take, at, take.frames), "delete before")


def delete_after(take: Take, at: int) -> Take:
    return _build(take.rate, take.channels, _range(take, 0, at), "delete after")


# -- Effects ----------------------------------------------------------------------

def volume(take: Take, factor: float) -> Take:
    blocks = (block * np.float32(factor) for block in _range(take, 0, take.frames))
    return _build(take.rate, take.channels, blocks, "volume")


def speed(take: Take, factor: float) -> Take:
    """Played `factor` times as fast, pitch and all, as 3.1 did: 2 halves the
    length, 0.5 doubles it. A resample to rate / factor, heard at the old rate,
    so soxr's filter keeps a faster sound from aliasing."""
    if factor >= 1:
        resampler = Resampler(round(take.rate * factor), take.rate, take.channels)
    else:
        resampler = Resampler(take.rate, round(take.rate / factor), take.channels)

    def resampled():
        for block in _range(take, 0, take.frames):
            yield resampler.process(block)
        yield resampler.flush()

    return _build(take.rate, take.channels, resampled(), "speed")


def echo(take: Take, seconds: float, level: float = ECHO_LEVEL) -> Take:
    """One repeat of the sound, `seconds` later at `level`; the length stays."""
    delay = max(round(seconds * take.rate), 1)

    def echoed():
        for at in range(0, take.frames, BLOCK):
            block = take.read(at, BLOCK)
            source = at - delay
            skip = max(-source, 0)  # the start of the block has nothing to repeat yet
            if skip < len(block):
                back = take.read(source + skip, len(block) - skip)
                block = block.copy()
                block[skip:skip + len(back)] += np.float32(level) * back
            yield block

    return _build(take.rate, take.channels, echoed(), "echo")


def reverse(take: Take) -> Take:
    def backwards():
        end = take.frames
        while end > 0:
            start = max(end - BLOCK, 0)
            yield take.read(start, end - start)[::-1]
            end = start

    return _build(take.rate, take.channels, backwards(), "reverse")
