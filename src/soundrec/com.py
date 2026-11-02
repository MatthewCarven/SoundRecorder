"""COM apartments for the threads that open audio streams.

Every thread that touches COM has to join an apartment first, and the two
capture paths want different ones: ASIO drivers expect a single-threaded
apartment (STA), and soundcard's WASAPI loopback asks for a multithreaded one
(MTA) when it is imported, on that thread only. A recording thread is new, so
it sets up its own.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager

COINIT_MULTITHREADED = 0x0
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: the thread already has the other kind

# CoGetApartmentType's answers.
APARTMENTS = {0: "sta", 1: "mta", 2: "neutral", 3: "main sta"}


def _ole32():
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoGetApartmentType.restype = ctypes.c_long
    return ole32


@contextmanager
def apartment(kind: str):
    """Run the block with this thread in a COM apartment: "sta" or "mta".

    Yields True if this call set the apartment up, False if the thread was
    already in the other kind (which is kept: COM can't change it).
    """
    flag = {"sta": COINIT_APARTMENTTHREADED, "mta": COINIT_MULTITHREADED}[kind]
    ole32 = _ole32()
    hr = ole32.CoInitializeEx(None, flag)
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise OSError(f"CoInitializeEx failed: HRESULT {hr & 0xFFFFFFFF:#010x}")
    try:
        yield hr >= 0
    finally:
        if hr >= 0:  # S_OK and S_FALSE both need balancing
            ole32.CoUninitialize()


def current() -> str | None:
    """This thread's apartment, or None if it hasn't joined one. A thread
    that hasn't, in a process where another thread made an MTA, is "implicit
    mta": COM lets it borrow that one."""
    kind, qualifier = ctypes.c_int(), ctypes.c_int()
    if _ole32().CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier)) < 0:
        return None
    if qualifier.value == 1:  # APTTYPEQUALIFIER_IMPLICIT_MTA
        return "implicit mta"
    return APARTMENTS.get(kind.value, str(kind.value))
