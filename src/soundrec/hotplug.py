"""Notice audio devices coming and going.

The audio service writes every endpoint's state into the MMDevices registry
key, so a change notification on that key fires when a device is plugged in,
unplugged, enabled or disabled. That needs no window and no COM callback
object (IMMNotificationClient). The same key also changes for things that
don't matter here (volume, settings), so a change only counts once the
endpoints' states differ from before; and one plug-in writes a burst of values,
so the callback runs once the key has been quiet for `settle` seconds.

ASIO drivers aren't endpoints: a newly installed one needs a rescan by hand.
"""

from __future__ import annotations

import ctypes
import threading
import winreg
from ctypes import wintypes
from dataclasses import dataclass

from .endpoints import ROOT, read_states

REG_NOTIFY_CHANGE_NAME = 0x1
REG_NOTIFY_CHANGE_LAST_SET = 0x4
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF


@dataclass(frozen=True)
class StateChange:
    appeared: tuple[str, ...]   # endpoint ids new to the registry
    vanished: tuple[str, ...]
    changed: tuple[str, ...]    # same id, different DeviceState

    def __bool__(self) -> bool:
        return bool(self.appeared or self.vanished or self.changed)


def compare(old: dict[str, int], new: dict[str, int]) -> StateChange:
    return StateChange(tuple(sorted(new.keys() - old.keys())),
                       tuple(sorted(old.keys() - new.keys())),
                       tuple(sorted(i for i in old.keys() & new.keys() if old[i] != new[i])))


def settle_loop(wait, settle: float, on_settled) -> None:
    """The watcher's loop, apart from Windows so it can be tested.

    wait(timeout) blocks until the key changes ("change"), the timeout passes
    ("timeout") or the watcher is stopped ("stop"); timeout None is forever.
    on_settled() runs after each burst of changes, once `settle` seconds pass
    with no more.
    """
    pending = False
    while True:
        event = wait(settle if pending else None)
        if event == "stop":
            return
        if event == "change":
            pending = True
        elif pending:  # quiet for `settle` seconds after a change
            pending = False
            on_settled()


class DeviceWatcher:
    """Calls on_change(StateChange) from its own thread when endpoints change."""

    def __init__(self, on_change, settle: float = 1.0):
        self._on_change = on_change
        self._settle = settle
        self.error: BaseException | None = None  # why the thread stopped, if not asked to
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateEventW.restype = wintypes.HANDLE
        self._stop = self._kernel32.CreateEventW(None, True, False, None)
        self._thread = None

    def start(self) -> None:
        if self._thread is None:
            self._kernel32.ResetEvent(wintypes.HANDLE(self._stop))
            self._thread = threading.Thread(target=self._run, name="DeviceWatcher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._kernel32.SetEvent(wintypes.HANDLE(self._stop))
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        try:
            self._watch()
        except BaseException as e:
            self.error = e

    def _watch(self) -> None:
        k32 = self._kernel32
        advapi32 = ctypes.WinDLL("advapi32")
        changed = k32.CreateEventW(None, False, False, None)
        handles = (wintypes.HANDLE * 2)(changed, self._stop)
        states = read_states()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ROOT, 0,
                                winreg.KEY_NOTIFY | winreg.KEY_READ) as key:
                def arm():
                    # One-shot: has to be asked for again after every signal.
                    error = advapi32.RegNotifyChangeKeyValue(
                        wintypes.HKEY(key.handle), True,
                        REG_NOTIFY_CHANGE_NAME | REG_NOTIFY_CHANGE_LAST_SET,
                        wintypes.HANDLE(changed), True)
                    if error:
                        raise ctypes.WinError(error)

                def wait(timeout):
                    ms = INFINITE if timeout is None else int(timeout * 1000)
                    result = k32.WaitForMultipleObjects(2, handles, False, ms)
                    if result == WAIT_OBJECT_0:
                        arm()
                        return "change"
                    return "timeout" if result == WAIT_TIMEOUT else "stop"

                def settled():
                    nonlocal states
                    new = read_states()
                    change = compare(states, new)
                    states = new
                    if change:
                        self._on_change(change)

                arm()
                settle_loop(wait, self._settle, settled)
        finally:
            k32.CloseHandle(wintypes.HANDLE(changed))
