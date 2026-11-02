"""Writing audio files: the format from the name, the bit depth, and dither.

Everything libsndfile offers is open to us. Blocks arrive as float32; on the
way down to 16 or 8 bits each sample gets TPDF dither (two uniform random
numbers' difference, +-1 step) before rounding, which turns the rounding error
into a steady, quiet hiss instead of distortion that follows the signal.
Blocks already exactly on the target's grid (16-bit audio captured and saved
unchanged) are written untouched. 24 and 32 bits are only rounded: float32
from the working copy carries 24 bits, so there is nothing to hide.

PCM is quantised here, not by libsndfile: its own float conversion scales by
32767, where capture (PortAudio) and reading (libsndfile) use 32768, so a
16-bit take would not come back bit for bit.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# Extensions soundfile doesn't know by itself.
ALIASES = {
    ".wave": ("WAV", None), ".aif": ("AIFF", None), ".aifc": ("AIFF", None),
    ".snd": ("AU", None), ".oga": ("OGG", None), ".opus": ("OGG", "OPUS"),
}

# Codecs with no bit depth to choose: they take float.
LOSSY = {"VORBIS", "OPUS", "MPEG_LAYER_I", "MPEG_LAYER_II", "MPEG_LAYER_III"}

BIT_CHOICES = ("8", "16", "24", "32", "float")

# Subtypes quantised here: (bits, dithered). 8 and 16 bits go to libsndfile as
# int16 on the grid of the target; 24 and 32 as int32.
PCM = {"PCM_U8": (8, True), "PCM_S8": (8, True), "PCM_16": (16, True),
       "PCM_24": (24, False), "PCM_32": (32, False)}
FLOATS = {"FLOAT", "DOUBLE"}


@dataclass(frozen=True)
class OutputSpec:
    format: str    # soundfile's name: "WAV", "FLAC", "MP3", ...
    subtype: str   # "PCM_16", "VORBIS", "MPEG_LAYER_III", ...

    def describe(self) -> str:
        text = {"PCM_U8": "8-bit", "PCM_S8": "8-bit", "PCM_16": "16-bit", "PCM_24": "24-bit",
                "PCM_32": "32-bit", "FLOAT": "32-bit float", "DOUBLE": "64-bit float",
                "VORBIS": "Vorbis", "OPUS": "Opus", "MPEG_LAYER_III": "layer III"}
        return f"{self.format} {text.get(self.subtype, self.subtype)}"

    @property
    def dithered(self) -> bool:
        return PCM.get(self.subtype, (0, False))[1]


def spec_for(path, bits: str | None = None) -> OutputSpec:
    """The file format a name asks for, at `bits` ("8" ... "32", "float") or
    the format's usual depth. ValueError if libsndfile can't write it."""
    ext = Path(path).suffix.lower()
    fmt, subtype = ALIASES.get(ext, (ext[1:].upper(), None))
    if fmt not in sf.available_formats():
        raise ValueError(f"don't know how to write {ext or 'a file with no extension'} files")
    subtype = subtype or sf.default_subtype(fmt)
    if bits is not None:
        if subtype in LOSSY:
            raise ValueError(f"{fmt} ({subtype}) has no bit depth to choose")
        subtype = _subtype_for_bits(fmt, bits)
    if not sf.check_format(fmt, subtype):
        raise ValueError(f"libsndfile can't write {subtype} in {fmt}")
    return OutputSpec(fmt, subtype)


def _subtype_for_bits(fmt: str, bits: str) -> str:
    # WAV's 8-bit is unsigned; most other containers' is signed.
    choices = {"8": ("PCM_U8", "PCM_S8") if fmt in ("WAV", "WAVEX", "W64", "RF64")
               else ("PCM_S8", "PCM_U8"),
               "16": ("PCM_16",), "24": ("PCM_24",), "32": ("PCM_32",), "float": ("FLOAT",)}
    if bits not in choices:
        raise ValueError(f"bits must be one of {', '.join(BIT_CHOICES)}")
    for subtype in choices[bits]:
        if sf.check_format(fmt, subtype):
            return subtype
    raise ValueError(f"{fmt} can't hold {bits}-bit samples" if bits != "float"
                     else f"{fmt} can't hold float samples")


class Quantiser:
    """float32 blocks to what libsndfile should be handed for `subtype`."""

    def __init__(self, subtype: str, seed=None):
        self.subtype = subtype
        self.bits, self.dither = PCM.get(subtype, (0, False))
        self._rng = np.random.default_rng(seed)
        # Grid step in the container's units: int16 for 8 and 16 bits, int32 above.
        container = 16 if self.bits <= 16 else 32
        self._scale = float(2 ** (container - 1))
        self._step = float(2 ** (container - self.bits))
        self._dtype = np.int16 if container == 16 else np.int32

    def __call__(self, block: np.ndarray) -> np.ndarray:
        if not self.bits:
            # Float formats keep overs; everything else would wrap or distort past full scale.
            return block if self.subtype in FLOATS else np.clip(block, -1.0, 1.0)
        # float64: 2**31 * a float32 is exact there, and leaves room above full scale.
        steps = block.astype(np.float64) * (self._scale / self._step)
        rounded = np.round(steps)
        if self.dither and not np.array_equal(steps, rounded):
            noise = self._rng.random(steps.shape) - self._rng.random(steps.shape)
            rounded = np.round(steps + noise)
        top = self._scale / self._step
        return (np.clip(rounded, -top, top - 1) * self._step).astype(self._dtype)


class Writer:
    """An open output file taking float32 blocks."""

    def __init__(self, path, spec: OutputSpec, rate: int, channels: int, seed=None):
        self.path, self.spec = Path(path), spec
        self._quantise = Quantiser(spec.subtype, seed)
        self._file = sf.SoundFile(str(path), "w", rate, channels, spec.subtype, format=spec.format)
        self.frames = 0

    def write(self, block: np.ndarray) -> None:
        if len(block):
            self._file.write(self._quantise(block))
            self.frames += len(block)

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def preflight(spec: OutputSpec, rate: int, channels: int) -> None:
    """Raise now, not after a three-hour take, if `spec` can't be written at
    this rate and channel count (MP3 stops at 48 kHz and two channels; Opus
    takes only 8, 12, 16, 24 and 48 kHz)."""
    with tempfile.TemporaryDirectory(prefix="soundrec-") as folder:
        path = os.path.join(folder, "check." + spec.format.lower())
        try:
            with Writer(path, spec, rate, channels) as w:
                w.write(np.zeros((rate // 10, channels), np.float32))
        except (RuntimeError, sf.LibsndfileError) as e:
            raise ValueError(f"can't write {spec.describe()} at {rate:,} Hz, {channels} ch: {e}") from e
