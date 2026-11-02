"""Capture sources for the Recorder: PortAudio streams and WASAPI loopback.

Each source opens, runs and closes its stream on a thread of its own, which
joins the COM apartment its API wants before anything else: an STA for
PortAudio (ASIO drivers need one, and open and close on the same thread),
an MTA for soundcard's loopback. So the caller's thread and its apartment
don't matter.

PortAudio delivers in its callback; soundcard has to be asked, so the
loopback thread reads in a loop. Either way a block goes straight to the
Recorder's queue.
"""

from __future__ import annotations

import threading

import numpy as np

from .com import apartment
from .devices import Device
from .engine import DISCONTINUITY, OVERFLOW


class CaptureError(Exception):
    pass


class _Threaded:
    """Open on a thread of its own, report how the opening went, run until stopped."""

    def __init__(self, device: Device, rate: int, channels: int):
        self.device, self.rate, self.channels = device, rate, channels
        self.failure: BaseException | None = None  # the stream died while recording
        self._opened = threading.Event()
        self._stop = threading.Event()
        self._open_error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self, deliver) -> None:
        self._thread = threading.Thread(target=self._run, args=(deliver,),
                                        name=f"Capture: {self.device.key}", daemon=True)
        self._thread.start()
        self._opened.wait()
        if self._open_error is not None:
            self._thread.join()
            raise CaptureError(f"couldn't open {self.device.key}: {self._open_error}") \
                from self._open_error

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self, deliver) -> None:
        raise NotImplementedError


class PortAudioCapture(_Threaded):
    """Any PortAudio device: MME, DirectSound, WASAPI (shared or exclusive),
    WDM-KS or ASIO. Captured as float32 whatever the device's own sample type:
    PortAudio's conversion from 16 or 24 bits is exact."""

    def __init__(self, device: Device, rate: int, channels: int, *, exclusive: bool = False,
                 blocksize: int = 0, latency="high"):
        super().__init__(device, rate, channels)
        if exclusive and device.api != "WASAPI":
            raise CaptureError("exclusive mode is WASAPI's alone")
        self.exclusive, self.blocksize, self.latency = exclusive, blocksize, latency

    def _run(self, deliver) -> None:
        with apartment("sta"):
            try:
                from .pa import sd

                def callback(indata, frames, time_info, status):
                    deliver(indata.copy(), OVERFLOW if status.input_overflow else 0)

                def finished():
                    if not self._stop.is_set():
                        self.failure = CaptureError(f"{self.device.key} stopped sending audio")

                # Exclusive without explicit_sample_format: PortAudio finds the
                # device's own sample type and converts it to float32 for us.
                extra = sd.WasapiSettings(exclusive=True) if self.exclusive else None
                stream = sd.InputStream(device=self.device.index, channels=self.channels,
                                        samplerate=self.rate, dtype="float32",
                                        blocksize=self.blocksize, latency=self.latency,
                                        extra_settings=extra, callback=callback,
                                        finished_callback=finished)
                stream.start()
            except BaseException as e:
                self._open_error = e
                self._opened.set()
                return
            self._opened.set()
            try:
                self._stop.wait()
                stream.stop()
            finally:
                stream.close()


class _GapCounter:
    """Stands in for the warnings module inside soundcard's WASAPI code, which
    reports lost loopback audio only as a "data discontinuity" warning."""

    def __init__(self, real):
        self._real = real
        self.count = 0

    def warn(self, message, category=None, stacklevel=1, **kw):
        if "discontinuity" in str(message):
            self.count += 1
        else:
            self._real.warn(message, category, stacklevel + 1, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _gap_counter() -> _GapCounter:
    import soundcard.mediafoundation as mf

    if not isinstance(mf.warnings, _GapCounter):
        mf.warnings = _GapCounter(mf.warnings)
    return mf.warnings


class LoopbackCapture(_Threaded):
    """What a playback device is playing, through soundcard (shared-mode
    WASAPI, so Windows converts to any rate and channel count asked for).

    When nothing plays, Windows sends nothing; soundcard fills the gap with
    silence by the clock, so the take keeps time.
    """

    BUFFER_SECONDS = 0.2  # WASAPI's buffer: how long the reader may be late before audio is lost

    def _run(self, deliver) -> None:
        with apartment("mta"):
            try:
                import soundcard  # devices.scan() imported it already, after PortAudio

                gaps = _gap_counter()
                mic = self._microphone(soundcard)
                recorder = mic.recorder(samplerate=self.rate, channels=self.channels,
                                        blocksize=int(self.rate * self.BUFFER_SECONDS))
                recorder.__enter__()
            except BaseException as e:
                self._open_error = e
                self._opened.set()
                return
            self._opened.set()
            try:
                seen = gaps.count
                while not self._stop.is_set():
                    block = recorder.record(numframes=None)
                    flags = DISCONTINUITY if gaps.count != seen else 0
                    seen = gaps.count
                    if len(block):
                        deliver(np.ascontiguousarray(block, dtype=np.float32), flags)
            except BaseException as e:
                self.failure = e
            finally:
                recorder.__exit__(None, None, None)

    def _microphone(self, soundcard):
        sources = [m for m in soundcard.all_microphones(include_loopback=True) if m.isloopback]
        endpoint_id = self.device.endpoint.id if self.device.endpoint else None
        hits = [m for m in sources if m.id == endpoint_id] or \
               [m for m in sources if m.name == self.device.name]
        if not hits:
            raise CaptureError(f"no loopback source for {self.device.name!r} now")
        return hits[0]


def open_capture(device: Device, rate: int | None = None, channels: int | None = None, *,
                 exclusive: bool = False, blocksize: int = 0):
    """A source for the Recorder, not started yet."""
    rate = rate or device.default_rate
    channels = channels or device.channels
    if device.api == "Loopback":
        if exclusive:
            raise CaptureError("loopback is shared mode only")
        return LoopbackCapture(device, rate, channels)
    if device.index is None:
        raise CaptureError(f"{device.key} has no PortAudio index")
    return PortAudioCapture(device, rate, channels, exclusive=exclusive, blocksize=blocksize)
