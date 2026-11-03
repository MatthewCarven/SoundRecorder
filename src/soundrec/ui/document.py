"""The sound the window holds: a working copy, and the file it belongs to.

The sound lives in a Take (float32 on disk, crash-proof), never in memory,
so an hour-long recording costs the window nothing. Its rate and channel
count are fixed by the first recording or by the file opened; later
recordings are converted to them as they come in.

Recording in 3.1 starts at the current position and records over whatever
follows, making the sound longer if it runs past the end. splice() does
that with the finished recording.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import soundfile as sf

from ..output import OutputSpec, spec_for
from ..takes import Take

READ_BLOCK = 1 << 16


class Document:
    def __init__(self):
        self.take: Take | None = None
        self.path: Path | None = None
        self.spec: OutputSpec | None = None  # how to write it back
        self.dirty = False

    @property
    def rate(self) -> int | None:
        return self.take.rate if self.take else None

    @property
    def channels(self) -> int | None:
        return self.take.channels if self.take else None

    @property
    def frames(self) -> int:
        return self.take.frames if self.take else 0

    @property
    def seconds(self) -> float:
        return self.frames / self.rate if self.take else 0.0

    @property
    def name(self) -> str:
        return self.path.name if self.path else "(Untitled)"

    def read(self, start: int, count: int) -> np.ndarray:
        if self.take is None:
            return np.zeros((0, 1), np.float32)
        return self.take.read(max(start, 0), count)

    # -- in and out -----------------------------------------------------------

    @classmethod
    def open(cls, path) -> Document:
        """Read a file into a new working copy. Anything libsndfile reads:
        WAV, FLAC, MP3, Ogg, AIFF..."""
        path = Path(path)
        with sf.SoundFile(str(path)) as f:
            take = Take.create(f.samplerate, f.channels, source=str(path))
            try:
                for block in f.blocks(READ_BLOCK, dtype="float32", always_2d=True):
                    take.write(block)
                take.finish()
            except BaseException:
                take.discard()
                raise
            spec = OutputSpec(f.format, f.subtype)
        doc = cls()
        doc.take, doc.path = take, path
        # Save writes the file's own format back, if libsndfile can write it.
        doc.spec = spec if sf.check_format(spec.format, spec.subtype) else spec_for(path)
        return doc

    def save(self, path, spec: OutputSpec) -> None:
        """Write the sound to `path`: to a temporary file beside it first, so a
        failed save can't wreck the file already there."""
        if self.take is None:
            raise ValueError("there's no sound to save")
        path = Path(path)
        temporary = path.with_name(path.name + ".saving")
        try:
            self.take.save(temporary, spec)
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self.path, self.spec, self.dirty = path, spec, False

    def splice(self, position: int, recording: Take) -> None:
        """Put a finished recording into the sound at `position`, over what was
        there. The recording's take is used up either way."""
        if recording.frames == 0:
            recording.discard()
            return
        if self.take is None or (position == 0 and recording.frames >= self.frames):
            if self.take is not None:
                self.take.discard()
            self.take = recording  # it covers everything: it becomes the sound
        else:
            if (recording.rate, recording.channels) != (self.rate, self.channels):
                raise ValueError("the recording's format isn't the sound's")
            self.take.write_at(position, recording.blocks())
            recording.discard()
        self.dirty = True

    def apply(self, edited: Take) -> None:
        """Swap in the take an Edit or Effects command made; the old one goes."""
        old, self.take = self.take, edited
        if old is not None:
            old.discard()
        self.dirty = True

    def close(self) -> None:
        """Throw the working copy away."""
        if self.take is not None:
            self.take.discard()
            self.take = None
