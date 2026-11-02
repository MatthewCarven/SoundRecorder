r"""The working copy: every take, as recorded, in a temp file of its own.

A take is two files side by side in the takes folder: raw float32 samples,
interleaved, at the document's rate and channels (`.f32`), and what they are
(`.json`). Raw samples have no header to finish, so whatever reached the disk
before a crash is good, and a recovered take is simply cut to whole frames.

Whoever owns a take holds a lock on its `.json` (a byte well past its end,
so reading it still works) for as long as the take is in use, not just while
recording. Windows drops the lock when the owning process dies, however it
dies, so a take nobody holds is one a crash left behind: `orphans()` finds
those, to be saved or thrown away.

The folder is %LOCALAPPDATA%\SoundRecorder\takes, or $SOUNDREC_TAKES.
"""

from __future__ import annotations

import datetime
import json
import msvcrt
import os
from pathlib import Path

import numpy as np

from .output import OutputSpec, Writer

DATA = ".f32"
INFO = ".json"
LOCK_AT = 1 << 20  # past the end of any .json
SYNC_EVERY = 5.0   # seconds of audio between fsyncs: a power cut loses at most this


def default_dir() -> Path:
    override = os.environ.get("SOUNDREC_TAKES")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    return Path(base) / "SoundRecorder" / "takes"


def _lock(path: Path):
    """The open, locked .json, or None if someone else holds it."""
    f = open(path, "r+b")
    try:
        f.seek(LOCK_AT)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


class Take:
    def __init__(self, data: Path, info: dict, lock):
        self.path = data
        self.info_path = data.with_suffix(INFO)
        self.info = info
        self.rate: int = info["rate"]
        self.channels: int = info["channels"]
        self._lock = lock
        self._out = None
        self._unsynced = 0

    # -- making one ---------------------------------------------------------

    @classmethod
    def create(cls, rate: int, channels: int, folder=None, **meta) -> Take:
        """A new, empty take, locked and open for writing. meta (the device,
        the file it's meant for...) goes into its .json for whoever recovers it."""
        folder = Path(folder) if folder is not None else default_dir()
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        stem = f"take-{now:%Y%m%d-%H%M%S}-{os.getpid()}"
        n = 0
        while (folder / (stem + DATA)).exists() or (folder / (stem + INFO)).exists():
            n += 1
            stem = f"take-{now:%Y%m%d-%H%M%S}-{os.getpid()}-{n}"
        data = folder / (stem + DATA)
        info = {"version": 1, "rate": rate, "channels": channels,
                "started": now.isoformat(timespec="seconds"), "finished": None, **meta}
        out = open(data, "xb")  # the samples first: a .json always has its .f32
        try:
            data.with_suffix(INFO).write_text(json.dumps(info, indent=1), encoding="utf-8")
            lock = _lock(data.with_suffix(INFO))
        except BaseException:
            out.close()
            data.unlink()
            raise
        take = cls(data, info, lock)
        take._out = out
        return take

    def write(self, block: np.ndarray) -> None:
        """Append float32 frames x channels; the owner calls this while recording."""
        block = np.ascontiguousarray(block, dtype=np.float32)
        if block.ndim != 2 or block.shape[1] != self.channels:
            raise ValueError(f"expected frames x {self.channels} channels, got {block.shape}")
        self._out.write(block.tobytes())
        self._out.flush()  # into Windows' hands: survives this process dying
        self._unsynced += len(block)
        if self._unsynced >= SYNC_EVERY * self.rate:
            os.fsync(self._out.fileno())  # onto the disk: survives Windows dying
            self._unsynced = 0

    def finish(self) -> None:
        """Recording is over: close the samples, note the end, keep the lock."""
        if self._out is not None:
            self._out.flush()
            os.fsync(self._out.fileno())
            self._out.close()
            self._out = None
        self.info["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.info["frames"] = self.frames
        self._rewrite_info()

    def write_at(self, start: int, blocks) -> None:
        """Write frames over a finished take from frame `start` on, extending
        it past the end if need be: a recording dropped into a sound."""
        if self._out is not None:
            raise RuntimeError("the take is still being recorded")
        if not 0 <= start <= self.frames:
            raise ValueError(f"frame {start} is outside the take ({self.frames} frames)")
        with open(self.path, "r+b") as f:
            f.seek(start * self.channels * 4)
            for block in blocks:
                block = np.ascontiguousarray(block, dtype=np.float32)
                if block.ndim != 2 or block.shape[1] != self.channels:
                    raise ValueError(f"expected frames x {self.channels} channels, got {block.shape}")
                f.write(block.tobytes())
            f.flush()
            os.fsync(f.fileno())
        self.info["frames"] = self.frames
        self._rewrite_info()

    def _rewrite_info(self) -> None:
        text = json.dumps(self.info, indent=1).encode("utf-8")
        self._lock.seek(0)
        self._lock.write(text)
        self._lock.truncate()
        self._lock.flush()

    # -- reading it ---------------------------------------------------------

    @property
    def frames(self) -> int:
        """Whole frames on disk (a crash can leave half of one at the end)."""
        if self._out is not None:
            self._out.flush()
        return os.path.getsize(self.path) // (4 * self.channels)

    @property
    def seconds(self) -> float:
        return self.frames / self.rate

    def read(self, start: int = 0, count: int | None = None) -> np.ndarray:
        frames = self.frames
        count = frames - start if count is None else min(count, frames - start)
        if count <= 0:
            return np.zeros((0, self.channels), np.float32)
        data = np.fromfile(self.path, np.float32, count * self.channels,
                           offset=start * self.channels * 4)
        return data.reshape(-1, self.channels)

    def blocks(self, frames: int = 1 << 16):
        for start in range(0, self.frames, frames):
            yield self.read(start, frames)

    def save(self, path, spec: OutputSpec, seed=None) -> int:
        """Write the take to `path`; returns the frames written."""
        with Writer(path, spec, self.rate, self.channels, seed) as w:
            for block in self.blocks():
                w.write(block)
            return w.frames

    # -- letting go ---------------------------------------------------------

    def discard(self) -> None:
        """Delete the take."""
        self._close()
        self.path.unlink(missing_ok=True)
        self.info_path.unlink(missing_ok=True)

    def release(self) -> None:
        """Let go but keep the files: anyone may now recover the take."""
        self._close()

    def _close(self) -> None:
        if self._out is not None:
            self._out.close()
            self._out = None
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def __repr__(self) -> str:
        return f"<Take {self.path.name}: {self.seconds:.1f} s, {self.rate} Hz, {self.channels} ch>"


def orphans(folder=None) -> list[Take]:
    """Takes nobody holds: left behind by a crash, oldest first. Each comes
    back locked to this process; save or discard it, or release() it."""
    folder = Path(folder) if folder is not None else default_dir()
    found = []
    for info_path in sorted(folder.glob("take-*" + INFO)):
        data = info_path.with_suffix(DATA)
        if not data.exists():
            continue
        lock = _lock(info_path)
        if lock is None:
            continue  # its owner is alive
        try:
            lock.seek(0)
            info = json.loads(lock.read().decode("utf-8"))
            int(info["rate"]), int(info["channels"])
        except (ValueError, KeyError, TypeError):
            lock.close()
            continue
        found.append(Take(data, info, lock))
    return found
