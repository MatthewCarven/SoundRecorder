"""The recording engine: a capture source in, a working copy (and maybe a file) out.

The source hands over blocks on its own thread (PortAudio's callback, or
the loopback reader), and all that happens there is a copy into a queue.
A worker thread does everything else, converting, writing the working copy,
writing the output file, measuring, so a slow disk or a busy UI can't make
the device wait. Should the worker fall behind for a while, the queue holds
the audio until it catches up.

A source is anything with `rate`, `channels`, `start(deliver)` and `stop()`:
start opens the stream (raising if it can't) and then calls
deliver(block, flags) for every block, a float32 frames x channels array of
its own; after stop() returns it calls deliver no more. capture.py has the
real ones; ArraySource below plays an array, for tests.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .convert import QUALITY, Converter
from .output import OutputSpec, Writer
from .takes import Take

# Flags a source passes with a block.
OVERFLOW = 1       # the stream couldn't keep up with the device: audio was lost before this block
DISCONTINUITY = 2  # the API says what it delivered has a gap in it

BATCH_SECONDS = 0.5  # the most audio the worker converts in one go
GATHER_SECONDS = 0.01  # how long the worker lets blocks gather: ASIO's come every 1.3 ms
SCOPE_SECONDS = 0.25   # the latest output kept for a live display (Recorder.recent)


@dataclass
class Stats:
    """What a recording did, kept up to date by the worker while it runs."""
    capture_rate: int
    frames_in: int = 0
    frames_out: int = 0
    blocks: int = 0
    overflows: int = 0
    discontinuities: int = 0
    clipped: int = 0              # output samples at or past full scale
    max_gap: float = 0.0          # longest wait from one block to the next, s
    max_lag: float = 0.0          # furthest the worker fell behind the device, s
    first_time: float | None = None
    last_time: float | None = None
    # The clock check: a running least-squares line through (arrival time,
    # frames delivered so far), one point a block, kept as means and
    # co-moments so an hour of 64-frame blocks loses no precision.
    _n: int = field(default=0, repr=False)
    _mean_t: float = field(default=0.0, repr=False)
    _mean_f: float = field(default=0.0, repr=False)
    _ctt: float = field(default=0.0, repr=False)
    _ctf: float = field(default=0.0, repr=False)
    _cff: float = field(default=0.0, repr=False)

    def _arrived(self, t: float, frames: int) -> None:
        """A block of `frames` came in at perf_counter time t."""
        if self.first_time is None:
            self.first_time = t
        else:
            self.max_gap = max(self.max_gap, t - self.last_time)
        self.last_time = t
        self.frames_in += frames
        self.blocks += 1
        x, y = t - self.first_time, float(self.frames_in)
        self._n += 1
        dx, dy = x - self._mean_t, y - self._mean_f
        self._mean_t += dx / self._n
        self._mean_f += dy / self._n
        self._ctt += dx * (x - self._mean_t)
        self._ctf += dx * (y - self._mean_f)
        self._cff += dy * (y - self._mean_f)

    def measured_rate(self) -> float | None:
        """Frames the device really delivered per second by the PC's clock:
        the slope of frames against arrival time, over every block.

        A device running at a rate other than the one it claims (the H2n's
        bug) shows as a ratio: 48 kHz posing as 44.1 kHz reads 8.8% fast.
        Sound cards' clocks are off by up to about 100 ppm anyway.
        """
        if self._n < 3 or self._ctt <= 0:
            return None
        return self._ctf / self._ctt

    def clock_ppm(self) -> float | None:
        rate = self.measured_rate()
        return None if rate is None else (rate / self.capture_rate - 1) * 1e6

    def clock_uncertainty_ppm(self) -> float | None:
        """Twice the slope's standard error, in ppm. APIs that deliver in
        uneven lumps (DirectSound) need a long take before it gets small."""
        if self._n < 3 or self._ctt <= 0:
            return None
        residual = max(self._cff - self._ctf ** 2 / self._ctt, 0.0)
        error = math.sqrt(residual / (self._n - 2) / self._ctt)
        return 2 * error / self.capture_rate * 1e6

    def clock_problem(self, tolerance: float = 0.01, min_seconds: float = 2.0) -> str | None:
        """In words, if the device is clearly not delivering at the rate it
        claims: off by more than `tolerance` and by well over the measurement's
        own uncertainty. The take is no good then: PortAudio's WASAPI exclusive
        capture repeats blocks on this laptop (40% too many frames), and a
        device stuck at another rate (the H2n's bug) would show here too."""
        ppm, spread = self.clock_ppm(), self.clock_uncertainty_ppm()
        if ppm is None or self.seconds_in < min_seconds or abs(ppm) <= max(tolerance * 1e6, 3 * spread):
            return None
        return (f"the device delivered {self.measured_rate():,.0f} frames a second for the "
                f"{self.capture_rate:,} it claims ({ppm / 1e4:+.1f}%): audio is being repeated "
                "or lost, or the device is running at another rate")

    @property
    def seconds_in(self) -> float:
        return self.frames_in / self.capture_rate


def decibels(peak: float) -> float:
    return 20 * math.log10(peak) if peak > 0 else -math.inf


class Recorder:
    """Record from `source` into a new working copy, converting as it goes.

    rate, channels: the document's (by default, the source's own).
    pick: the captured channels to use, 0-based (ChannelMap explains).
    direct: (path, OutputSpec) to also encode straight into a file.
    limit: keep this many output frames and no more; `full` is set on reaching it.
    folder: where the working copy goes (takes.default_dir() if None).
    meta: noted in the working copy's .json, for whoever recovers it.
    """

    def __init__(self, source, rate: int | None = None, channels: int | None = None, pick=None,
                 *, direct: tuple[Path, OutputSpec] | None = None, limit: int | None = None,
                 folder=None, quality: str = QUALITY, meta: dict | None = None, seed=None):
        self.source = source
        self.rate = rate or source.rate
        self.channels = channels or (len(pick) if pick else source.channels)
        self.converter = Converter(source.rate, source.channels, self.rate, self.channels,
                                   pick, quality)
        self.direct = direct
        self.limit = limit
        self.full = threading.Event()
        self.folder = folder
        self.meta = dict(meta or {})
        self.seed = seed
        self.stats = Stats(source.rate)
        self.take: Take | None = None
        self.error: BaseException | None = None         # the worker failed: recording stopped
        self.direct_error: BaseException | None = None  # the file failed; the working copy goes on
        self._writer: Writer | None = None
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._worker: threading.Thread | None = None
        self._peaks = np.zeros(self.channels, np.float32)
        self._peaks_lock = threading.Lock()
        self._scope = np.zeros((max(int(self.rate * SCOPE_SECONDS), 1), self.channels), np.float32)
        self._scope_end = 0  # where the next frame goes in the ring
        self.running = False

    # -- control ------------------------------------------------------------

    def start(self) -> None:
        if self.direct:
            path, spec = self.direct
            self._writer = Writer(path, spec, self.rate, self.channels, self.seed)
            self.meta.setdefault("direct", str(path))
        try:
            self.take = Take.create(self.rate, self.channels, self.folder, **self.meta)
            self._worker = threading.Thread(target=self._work, name="Recorder worker", daemon=True)
            self._worker.start()
            self.source.start(self._deliver)
        except BaseException:
            self._shut_down()
            if self.take is not None:
                self.take.discard()
            if self._writer is not None:
                self._writer.path.unlink(missing_ok=True)
            raise
        self.running = True

    def stop(self) -> Take:
        """Stop, finish the files and hand over the working copy (still locked:
        save it, discard it, or release it to leave it for recovery)."""
        if self.running:
            self.source.stop()
            self.running = False
        self._shut_down()
        self.take.finish()
        return self.take

    def _shut_down(self) -> None:
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join()
            self._worker = None
        if self._writer is not None:
            try:
                self._writer.close()
            except BaseException as e:
                self.direct_error = self.direct_error or e

    @property
    def failure(self) -> BaseException | None:
        """Why the recording can't go on, if it can't."""
        return self.error or getattr(self.source, "failure", None)

    def recent(self, frames: int) -> np.ndarray:
        """The last `frames` output frames (up to SCOPE_SECONDS' worth), oldest
        first: for a live picture of what is coming in."""
        size = len(self._scope)
        frames = min(frames, size)
        with self._peaks_lock:
            index = (np.arange(self._scope_end - frames, self._scope_end)) % size
            return self._scope[index]

    def take_peaks(self) -> np.ndarray:
        """Each output channel's peak since the last call (0 to 1, or over)."""
        with self._peaks_lock:
            peaks = self._peaks.copy()
            self._peaks[:] = 0
        return peaks

    @property
    def seconds(self) -> float:
        return self.stats.frames_out / self.rate

    # -- capture side: as little as possible --------------------------------

    def _deliver(self, block: np.ndarray, flags: int = 0) -> None:
        self._queue.put((block, flags, time.perf_counter()))

    # -- worker side --------------------------------------------------------

    def _work(self) -> None:
        most = BATCH_SECONDS * self.source.rate
        done = False
        while not done:
            batch, frames = [], 0
            try:
                item = self._queue.get_nowait()  # behind: no pause, catch up
            except queue.Empty:
                item = self._queue.get()
                if item is not None:
                    time.sleep(GATHER_SECONDS)
            while True:
                if item is None:
                    done = True
                    break
                batch.append(item)
                frames += len(item[0])
                if frames >= most:
                    break
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
            if batch and self.error is None:  # after a failure, just drain the queue
                try:
                    self._convert(batch)
                except BaseException as e:
                    self.error = e
        if self.error is None:
            try:
                self._write(self.converter.flush())
            except BaseException as e:
                self.error = e

    def _convert(self, batch) -> None:
        s = self.stats
        s.max_lag = max(s.max_lag, time.perf_counter() - batch[0][2])
        for block, flags, t in batch:
            s._arrived(t, len(block))
            s.overflows += bool(flags & OVERFLOW)
            s.discontinuities += bool(flags & DISCONTINUITY)
        data = batch[0][0] if len(batch) == 1 else np.concatenate([b[0] for b in batch])
        self._write(self.converter.process(data))

    def _write(self, out: np.ndarray) -> None:
        if self.limit is not None:
            out = out[:max(self.limit - self.stats.frames_out, 0)]
            if self.stats.frames_out + len(out) >= self.limit:
                self.full.set()
        if not len(out):
            return
        self.take.write(out)
        self.stats.frames_out += len(out)
        size = np.abs(out)
        self.stats.clipped += int(np.count_nonzero(size >= 1.0))
        with self._peaks_lock:
            np.maximum(self._peaks, size.max(axis=0), out=self._peaks)
            ring = len(self._scope)
            tail = out[-ring:]
            index = (self._scope_end + np.arange(len(tail))) % ring
            self._scope[index] = tail
            self._scope_end = (self._scope_end + len(tail)) % ring
        if self._writer is not None and self.direct_error is None:
            try:
                self._writer.write(out)
            except BaseException as e:
                self.direct_error = e


class ArraySource:
    """Plays an array into a Recorder as a capture stream would: from a thread
    of its own, in blocks. `block` is a size, or sizes to cycle through;
    realtime=False hands blocks over as fast as they can go. `flags` maps a
    block's number to the flags it carries. `finished` is set once the last
    block is out."""

    def __init__(self, data: np.ndarray, rate: int, block=512, realtime: bool = False,
                 flags: dict | None = None):
        self.data = np.asarray(data, np.float32).reshape(len(data), -1)
        self.rate, self.channels = rate, self.data.shape[1]
        self.sizes = [block] if isinstance(block, int) else list(block)
        self.realtime = realtime
        self.flags = flags or {}
        self.finished = threading.Event()
        self.failure = None
        self._stop = threading.Event()
        self._thread = None

    def start(self, deliver) -> None:
        self._thread = threading.Thread(target=self._run, args=(deliver,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self, deliver) -> None:
        start, at, n = time.perf_counter(), 0, 0
        while at < len(self.data) and not self._stop.is_set():
            size = self.sizes[n % len(self.sizes)]
            deliver(self.data[at:at + size].copy(), self.flags.get(n, 0))
            at += size
            n += 1
            if self.realtime:
                wait = start + at / self.rate - time.perf_counter()
                if wait > 0:
                    self._stop.wait(wait)
        self.finished.set()
