"""Writing audio files: the format from the name, the bit depth, and dither.

Everything libsndfile offers is open to us. Blocks arrive as float32; on the
way down to 16 or 8 bits each sample gets TPDF dither (two uniform random
numbers' difference, +-1 step) before rounding, which turns the rounding error
into a steady, quiet hiss instead of distortion that follows the signal.
Blocks already exactly on the target's grid (16-bit audio captured and saved
unchanged) are written untouched. 24 and 32 bits are only rounded: float32
from the working copy carries 24 bits, so there is nothing to hide.

AAC (.m4a) isn't libsndfile's: it goes through ffmpeg (ffmpeg.py), behind the
same Writer. Each codec's Quality list is labelled by what was measured here,
2026-11-04: libsndfile's one "compression level" means something else to each.

PCM is quantised here, not by libsndfile: its own float conversion scales by
32767, where capture (PortAudio) and reading (libsndfile) use 32768, so a
16-bit take would not come back bit for bit.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# Extensions soundfile doesn't know by itself.
ALIASES = {
    ".wave": ("WAV", None), ".aif": ("AIFF", None), ".aifc": ("AIFF", None),
    ".snd": ("AU", None), ".oga": ("OGG", None), ".opus": ("OGG", "OPUS"),
    ".m4a": ("M4A", "AAC"),
}

# Codecs with no bit depth to choose: they take float.
LOSSY = {"VORBIS", "OPUS", "MPEG_LAYER_I", "MPEG_LAYER_II", "MPEG_LAYER_III", "AAC"}

BIT_CHOICES = ("8", "16", "24", "32", "float")

# Subtypes quantised here: (bits, dithered). 8 and 16 bits go to libsndfile as
# int16 on the grid of the target; 24 and 32 as int32.
PCM = {"PCM_U8": (8, True), "PCM_S8": (8, True), "PCM_16": (16, True),
       "PCM_24": (24, False), "PCM_32": (32, False)}
FLOATS = {"FLOAT", "DOUBLE"}


@dataclass(frozen=True)
class Quality:
    """One line of a codec's Quality list."""
    label: str
    level: float | None = None  # libsndfile's compression level: 0 is the most data, 1 the least
    mode: str | None = None     # libsndfile's bitrate mode
    kbps: int | None = None     # MP3's constant rate (see mp3_level), or AAC's


def _mp3() -> tuple[Quality, ...]:
    constant = tuple(Quality(f"Constant {k} kbit/s", mode="CONSTANT", kbps=k)
                     for k in (320, 256, 192, 160, 128, 96, 64))
    variable = tuple(Quality(f"Variable, LAME's V{v}", level=v / 10, mode="VARIABLE")
                     for v in (0, 2, 4, 6))
    return constant + variable


# Level 1 fails on MP3 (it would be 32 kbit/s) and Opus's top end is 6 kbit/s a
# channel, so neither goes that far. The default of each list comes first in
# DEFAULT_QUALITY, by label.
QUALITIES: dict[str, tuple[Quality, ...]] = {
    "MPEG_LAYER_III": _mp3(),
    "VORBIS": tuple(Quality(f"Quality {q}", level=1 - q / 10) for q in range(10, -1, -1)),
    "OPUS": tuple(Quality(f"{k} kbit/s a channel", level=(256 - k) / 250)
                  for k in (256, 192, 128, 96, 64, 48, 32)),
    "AAC": tuple(Quality(f"{k} kbit/s", kbps=k) for k in (320, 256, 192, 160, 128, 96, 64)),
}
FLAC_QUALITIES = tuple(
    Quality(f"Level {n}" + {0: " (fastest)", 8: " (smallest)"}.get(n, ""), level=n / 8)
    for n in range(9))
DEFAULT_QUALITY = {"MPEG_LAYER_III": "Constant 192 kbit/s", "VORBIS": "Quality 4",
                   "OPUS": "64 kbit/s a channel", "AAC": "192 kbit/s", "FLAC": "Level 5"}
AAC_DEFAULT_KBPS = 192


@dataclass(frozen=True)
class OutputSpec:
    format: str    # soundfile's name: "WAV", "FLAC", "MP3", ..., or our "M4A"
    subtype: str   # "PCM_16", "VORBIS", "MPEG_LAYER_III", ..., or our "AAC"
    quality: Quality | None = None  # None: the codec's own default

    def describe(self) -> str:
        text = {"PCM_U8": "8-bit", "PCM_S8": "8-bit", "PCM_16": "16-bit", "PCM_24": "24-bit",
                "PCM_32": "32-bit", "FLOAT": "32-bit float", "DOUBLE": "64-bit float",
                "VORBIS": "Vorbis", "OPUS": "Opus", "MPEG_LAYER_III": "layer III"}
        name = f"{self.format} {text.get(self.subtype, self.subtype)}"
        return f"{name}, {self.quality.label}" if self.quality else name

    @property
    def dithered(self) -> bool:
        return PCM.get(self.subtype, (0, False))[1]


@dataclass(frozen=True)
class Target:
    """What Device > Output Format asks of Save As. None: leave it to the
    sound (its rate, its channels) or to the file's name (its format)."""
    spec: OutputSpec | None = None
    rate: int | None = None
    channels: int | None = None


def qualities(spec: OutputSpec) -> tuple[Quality, ...]:
    """What the Quality list offers for this format and encoding: often nothing."""
    return FLAC_QUALITIES if spec.format == "FLAC" else QUALITIES.get(spec.subtype, ())


def default_quality(spec: OutputSpec) -> Quality | None:
    """The line a Quality list starts on."""
    wanted = DEFAULT_QUALITY.get("FLAC" if spec.format == "FLAC" else spec.subtype)
    return next((q for q in qualities(spec) if q.label == wanted), None)


def mp3_level(kbps: int, rate: int) -> float:
    """The compression level for a constant MP3 rate. libsndfile reads the level
    against the top and bottom rates of the MPEG version the sample rate falls
    in, so one level means a different kbit/s at each. Past the top: the top."""
    top, bottom = (320, 32) if rate >= 32000 else (160, 8) if rate >= 16000 else (64, 8)
    return min(max((top - kbps) / (top - bottom), 0.0), 0.95)


# Rates a codec can't go beyond, and channels likewise, measured 2026-11-04.
ONLY_RATES = {"OPUS": (8000, 12000, 16000, 24000, 48000),
              "MPEG_LAYER_III": (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)}
MOST_CHANNELS = {"MP3": 2, "FLAC": 8, "M4A": 8}


def rate_for(spec: OutputSpec, rate: int) -> int:
    """`rate` if the codec takes it, else the next one up, else its highest."""
    allowed = ONLY_RATES.get(spec.subtype)
    if allowed is None or rate in allowed:
        return rate
    return next((r for r in allowed if r >= rate), allowed[-1])


def channels_for(spec: OutputSpec, channels: int) -> int:
    return min(channels, MOST_CHANNELS.get(spec.format, channels))


def extension(spec: OutputSpec) -> str:
    """The extension a file in this format gets."""
    if spec.subtype == "OPUS":
        return ".opus"
    return {"WAVEX": ".wav", "M4A": ".m4a"}.get(spec.format, "." + spec.format.lower())


def format_names() -> dict[str, str]:
    """Every format there is, by name, with its description: libsndfile's, as
    it reports them at run time, and ours."""
    return {**sf.available_formats(), "M4A": "M4A (AAC, through ffmpeg)"}


def subtype_names(fmt: str) -> dict[str, str]:
    """The encodings of a format that really write. libsndfile also lists ones
    it can't: MPEG layers I and II, MP3 in a WAV, AIFF's DWVW_12."""
    if fmt == "M4A":
        return {"AAC": "AAC"}
    return {name: text for name, text in sf.available_subtypes(fmt).items()
            if _writes(OutputSpec(fmt, name))}


def _writes(spec: OutputSpec) -> bool:
    try:
        preflight(spec, rate_for(spec, 44100), 1)
    except ValueError:
        return False
    return True


def spec_for(path, bits: str | None = None) -> OutputSpec:
    """The file format a name asks for, at `bits` ("8" ... "32", "float") or
    the format's usual depth. ValueError if neither libsndfile nor ffmpeg's
    encoder can write it."""
    ext = Path(path).suffix.lower()
    fmt, subtype = ALIASES.get(ext, (ext[1:].upper(), None))
    if fmt == "M4A":
        if bits is not None:
            raise ValueError("M4A (AAC) has no bit depth to choose")
        return OutputSpec(fmt, subtype)
    if fmt not in sf.available_formats():
        raise ValueError(f"don't know how to write {ext or 'a file with no extension'} files")
    subtype = subtype or sf.default_subtype(fmt) or "PCM_16"  # RAW has no default
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
        quality = spec.quality or Quality("")
        if spec.format == "M4A":
            from .ffmpeg import Encoder

            self._file = Encoder(path, rate, channels, quality.kbps or AAC_DEFAULT_KBPS)
        else:
            level = quality.level
            if quality.kbps is not None:
                level = mp3_level(quality.kbps, rate)
            self._file = sf.SoundFile(str(path), "w", rate, channels, spec.subtype,
                                      format=spec.format, compression_level=level,
                                      bitrate_mode=quality.mode)
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


@contextmanager
def replacing(paths):
    """Temporary names beside `paths`, to write to inside the `with`. They take
    the real names only if the block finishes, so a failed save can't wreck the
    files already there, and a set of files arrives all together or not at all."""
    paths = [Path(p) for p in paths]
    temporaries = [p.with_name(p.name + ".saving") for p in paths]
    try:
        yield temporaries
        for temporary, path in zip(temporaries, paths):
            os.replace(temporary, path)
    except BaseException:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
        raise


def preflight(spec: OutputSpec, rate: int, channels: int) -> None:
    """Raise now, not after a three-hour take, if `spec` can't be written at
    this rate and channel count (MP3 stops at 48 kHz and two channels; Opus
    takes only 8, 12, 16, 24 and 48 kHz)."""
    with tempfile.TemporaryDirectory(prefix="soundrec-") as folder:
        path = os.path.join(folder, "check." + spec.format.lower())
        try:
            with Writer(path, spec, rate, channels) as w:
                w.write(np.zeros((rate // 10, channels), np.float32))
        except (RuntimeError, OSError, sf.LibsndfileError) as e:
            raise ValueError(f"can't write {spec.describe()} at {rate:,} Hz, {channels} ch: {e}") from e
