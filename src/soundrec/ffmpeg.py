"""What libsndfile can't do, through ffmpeg: AAC, and reading everything else.

imageio-ffmpeg carries an ffmpeg binary, so nothing needs installing; one on
the PATH does if that package is missing. Raw float samples go into ffmpeg's
stdin as they come, so an encoder takes blocks like any other Writer, and a
take can be encoded live as it's recorded. ffmpeg runs with no console window
(pythonw has none to share) and is gone by the time the Encoder is closed.

Reading goes the other way, through a temporary float WAV (RF64 past 4 GB),
which then opens like any other file: libsndfile says how many channels at
what rate, so nothing has to pick that out of ffmpeg's messages.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import soundfile as sf

NO_WINDOW = subprocess.CREATE_NO_WINDOW


class FfmpegMissing(RuntimeError):
    pass


def find() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        pass
    found = shutil.which("ffmpeg")
    if found is None:
        raise FfmpegMissing("ffmpeg isn't installed (pip install imageio-ffmpeg)")
    return found


class Encoder:
    """An .m4a file taking float32 blocks, written by ffmpeg's AAC encoder."""

    def __init__(self, path, rate: int, channels: int, kbps: int):
        self.path = Path(path)
        self._errors = tempfile.TemporaryFile()  # a pipe could fill up and stall ffmpeg
        self._process = subprocess.Popen(
            [find(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "f32le", "-ar", str(rate), "-ac", str(channels), "-i", "pipe:0",
             "-c:a", "aac", "-b:a", f"{kbps}k", "-f", "ipod", str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._errors,
            creationflags=NO_WINDOW)

    def write(self, block: np.ndarray) -> None:
        data = np.ascontiguousarray(block, dtype="<f4").tobytes()
        try:
            self._process.stdin.write(data)
        except OSError:  # ffmpeg stopped: it says why
            self._finish()

    def close(self) -> None:
        self._finish()

    def _finish(self) -> None:
        process = self._process
        if process is None:
            return
        self._process = None
        try:
            process.stdin.close()
        except OSError:
            pass
        code = process.wait()
        self._errors.seek(0)
        said = self._errors.read().decode("utf-8", "replace").strip()
        self._errors.close()
        if code:
            raise RuntimeError(said.splitlines()[-1] if said else f"ffmpeg stopped with code {code}")


def decode(path, out) -> None:
    """Any sound ffmpeg can read, as a float WAV at its own rate and channels."""
    done = subprocess.run([find(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                           "-vn", "-c:a", "pcm_f32le", "-rf64", "auto", "-f", "wav", str(out)],
                          stdin=subprocess.DEVNULL, capture_output=True, creationflags=NO_WINDOW)
    if done.returncode:
        said = done.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(said.splitlines()[-1] if said else "ffmpeg couldn't read it")


def readable_by_libsndfile(path) -> bool:
    try:
        sf.info(str(path))
    except sf.LibsndfileError:
        return False
    return True


@contextmanager
def readable(path):
    """A path libsndfile can open: `path` itself, or, for anything only ffmpeg
    reads, a temporary float WAV of it that lasts as long as the `with`. A file
    neither can read raises libsndfile's own complaint, or ffmpeg's if it ran."""
    if readable_by_libsndfile(path):
        yield Path(path)
        return
    try:
        find()
    except FfmpegMissing:
        sf.info(str(path))  # raises: it's libsndfile's answer that counts
        raise
    with tempfile.TemporaryDirectory(prefix="soundrec-") as folder:
        out = Path(folder) / "decoded.wav"
        decode(path, out)
        yield out
