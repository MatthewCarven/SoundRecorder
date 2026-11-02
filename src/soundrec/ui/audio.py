"""The window's audio: finding devices off the UI thread, and playback.

A scan takes 2-5 s (once 38 s), so it runs on a thread of its own, and the
window carries on meanwhile. Every scan and rescan runs on the same thread:
PortAudio sets up COM where it starts, and should be shut down where it
started. Results go back through `notify`, which runs a function on the UI
thread (Tk can only be touched from there).

Playback goes to Windows' default playback device over WASAPI shared mode
with Windows converting the rate and channels (auto_convert), so the device
keeps its own format: the H2n's playback side stays at the rate its capture
side runs at.
"""

from __future__ import annotations

import queue
import threading

import numpy as np

from ..com import apartment


class DeviceList:
    """The devices, scanned in the background. `scan` is the latest Scan."""

    def __init__(self, notify):
        self._notify = notify
        self.scan = None
        self.error: BaseException | None = None
        self.busy = False
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._work, name="Device scans", daemon=True)
        self._thread.start()

    def refresh(self, rescan: bool = False, then=None) -> bool:
        """Scan (rescan=True: have PortAudio look again too; no stream may be
        open). then() runs on the UI thread afterwards. False if one is running."""
        if self.busy:
            return False
        self.busy = True
        self._jobs.put((rescan, then))
        return True

    def stop(self) -> None:
        self._jobs.put(None)

    def _work(self) -> None:
        with apartment("sta"):
            while True:
                job = self._jobs.get()
                if job is None:
                    return
                rescan, then = job
                try:
                    from ..devices import scan
                    result, error = scan(rescan=rescan), None
                except BaseException as e:  # shown to the user, not raised
                    result, error = None, e
                self._notify(lambda r=result, e=error, t=then: self._done(r, e, t))

    def _done(self, result, error, then) -> None:
        self.busy = False
        if result is not None:
            self.scan = result
        self.error = error
        if then is not None:
            then()

    def default_output(self):
        """Windows' default playback device, over WASAPI."""
        if self.scan is None:
            return None
        outputs = [d for d in self.scan.outputs if d.api == "WASAPI"]
        return next((d for d in outputs if d.is_default), outputs[0] if outputs else None)


class PlaybackError(Exception):
    pass


class Player:
    """Plays a take from frame `start` to its end, on a thread of its own.

    The take is mapped into memory, so the callback only copies; it is let
    go when playback stops (Windows won't delete a mapped file).
    """

    def __init__(self, take, device, start: int = 0):
        self.take, self.device = take, device
        self.rate, self.channels = take.rate, min(take.channels, max(device.channels, 1))
        self.start_frame = self.sent = start
        self.end = take.frames
        self.latency = 0.0
        self.underflows = 0  # callbacks PortAudio says came too late: a gap was heard
        self.finished = threading.Event()
        self.failure: BaseException | None = None
        self._opened = threading.Event()
        self._stop = threading.Event()
        self._open_error: BaseException | None = None
        self._thread: threading.Thread | None = None

    @property
    def position(self) -> int:
        """The frame being heard now: what was sent, less what's still in the buffers."""
        if self.finished.is_set():
            return self.sent
        return max(self.start_frame, min(self.end, self.sent - int(self.latency * self.rate)))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="Playback", daemon=True)
        self._thread.start()
        self._opened.wait()
        if self._open_error is not None:
            self._thread.join()
            raise PlaybackError(f"couldn't play through {self.device.name}: {self._open_error}") \
                from self._open_error

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        with apartment("sta"):
            try:
                from ..pa import sd

                data = np.memmap(self.take.path, np.float32, "r",
                                 shape=(self.end, self.take.channels)) if self.end else None

                def callback(outdata, frames, time_info, status):
                    if status.output_underflow:
                        self.underflows += 1
                    at = self.sent
                    n = max(min(frames, self.end - at), 0)
                    if n:
                        outdata[:n] = data[at:at + n, :self.channels]
                    outdata[n:] = 0
                    self.sent = at + n
                    if self.sent >= self.end:
                        raise sd.CallbackStop

                stream = sd.OutputStream(device=self.device.index, samplerate=self.rate,
                                         channels=self.channels, dtype="float32",
                                         extra_settings=sd.WasapiSettings(auto_convert=True),
                                         callback=callback, finished_callback=self.finished.set)
                self.latency = stream.latency
                stream.start()
            except BaseException as e:
                self._open_error = e
                self._opened.set()
                return
            self._opened.set()
            try:
                while not self._stop.is_set() and not self.finished.is_set():
                    self._stop.wait(0.05)
                stream.stop()
            except BaseException as e:
                self.failure = e
            finally:
                stream.close()
                del data
                self.finished.set()
