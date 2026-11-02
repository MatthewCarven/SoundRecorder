r"""Ask an ASIO driver directly what it can do.

PortAudio asks ASIO drivers about sample rates only, and loads and unloads the
driver for every question: FL Studio's took 3.5 s a time, so a full probe took
7.5 minutes. Here the driver is loaded once and asked for its rates, its input
channels' names and sample types, and its buffer sizes, then released.

An ASIO driver is an in-process COM object registered under HKLM\SOFTWARE\ASIO,
with a bare C++ vtable: no type library, nothing to marshal it between COM
apartments. By the SDK's convention its CLSID doubles as the interface ID.
"""

from __future__ import annotations

import ctypes
import struct
import threading
import winreg
from ctypes import POINTER, byref, c_char, c_char_p, c_double, c_long, c_ulong, c_void_p
from dataclasses import dataclass

from .formats import RATES

ASIO_KEY = r"SOFTWARE\ASIO"
CLSCTX_INPROC_SERVER = 1
ASE_OK = 0

# ASIOSampleType -> sample type names (formats.TYPE_TEXT reads them out).
SAMPLE_TYPES = {
    16: "int16", 17: "int24", 18: "int32", 19: "float32", 20: "float64",
    24: "int32/16", 25: "int32/18", 26: "int32/20", 27: "int32/24",
    0: "int16 big-endian", 1: "int24 big-endian", 2: "int32 big-endian",
    3: "float32 big-endian", 4: "float64 big-endian",
    32: "DSD", 33: "DSD", 40: "DSD",
}

# Slots in IASIO's vtable: IUnknown's three methods, then IASIO's in order.
_RELEASE = 2
_INIT = 3
_GET_DRIVER_NAME = 4
_GET_DRIVER_VERSION = 5
_GET_ERROR_MESSAGE = 6
_GET_CHANNELS = 9
_GET_BUFFER_SIZE = 11
_CAN_SAMPLE_RATE = 12
_GET_SAMPLE_RATE = 13
_GET_CHANNEL_INFO = 18


class _ChannelInfo(ctypes.Structure):
    _fields_ = [("channel", c_long), ("isInput", c_long), ("isActive", c_long),
                ("channelGroup", c_long), ("type", c_long), ("name", c_char * 32)]


class AsioError(Exception):
    pass


@dataclass(frozen=True)
class Channel:
    name: str
    sample_type: str


@dataclass(frozen=True)
class AsioInfo:
    driver: str                     # the name the driver gives itself
    version: int
    rates: tuple[int, ...]
    current_rate: int               # 0 if the driver wouldn't say
    inputs: tuple[Channel, ...]
    outputs: int
    buffer_sizes: tuple[int, int, int]  # smallest, largest, preferred, in frames


def drivers() -> dict[str, str]:
    """Installed ASIO drivers, by the name PortAudio lists them under, to CLSID.

    PortAudio (through the SDK's asiolist) names a driver by its Description
    value, or its key's name if it has none.
    """
    found = {}
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ASIO_KEY)
    except OSError:
        return found
    with root:
        i = 0
        while True:
            try:
                key_name = winreg.EnumKey(root, i)
            except OSError:
                return found
            i += 1
            try:
                with winreg.OpenKey(root, key_name) as key:
                    clsid = winreg.QueryValueEx(key, "CLSID")[0]
                    try:
                        name = winreg.QueryValueEx(key, "Description")[0]
                    except OSError:
                        name = key_name
            except OSError:
                continue
            found[name] = clsid


def query(name: str, timeout: float = 30.0) -> AsioInfo:
    """Load the driver PortAudio lists as `name`, ask it everything, release it.

    Runs on a thread of its own, since ASIO drivers want a single-threaded COM
    apartment and the caller's thread may have the other kind. A driver that
    hangs past `timeout` is abandoned (a thread can't be killed): TimeoutError.
    """
    if struct.calcsize("P") != 8:
        raise AsioError("needs 64-bit Python: 32-bit ASIO drivers use thiscall, which ctypes can't call")
    clsid = drivers().get(name)
    if clsid is None:
        raise AsioError(f"no ASIO driver called {name!r} in the registry")
    result = {}

    def run():
        try:
            result["info"] = _query(clsid)
        except BaseException as e:
            result["error"] = e

    thread = threading.Thread(target=run, name=f"ASIO probe: {name}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"{name} didn't answer within {timeout:g} s")
    if "error" in result:
        raise result["error"]
    return result["info"]


def _method(obj, slot, restype, *argtypes):
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[slot])


def _text(raw: bytes) -> str:
    return raw.decode("mbcs", "replace").strip()


def _check(error: int, what: str) -> None:
    if error != ASE_OK:
        raise AsioError(f"{what} failed (ASIO error {error})")


def _query(clsid: str) -> AsioInfo:
    ole32 = ctypes.OleDLL("ole32")  # raises OSError on a failing HRESULT
    guid = (ctypes.c_ubyte * 16)()
    ole32.CLSIDFromString(ctypes.c_wchar_p(clsid), byref(guid))
    ole32.CoInitialize(None)
    try:
        obj = c_void_p()
        ole32.CoCreateInstance(byref(guid), None, CLSCTX_INPROC_SERVER, byref(guid), byref(obj))
        try:
            return _ask(obj)
        finally:
            _method(obj, _RELEASE, c_ulong)(obj)
    finally:
        ole32.CoUninitialize()


def _ask(obj) -> AsioInfo:
    user32 = ctypes.WinDLL("user32")
    user32.GetDesktopWindow.restype = c_void_p
    if not _method(obj, _INIT, c_long, c_void_p)(obj, user32.GetDesktopWindow()):
        message = ctypes.create_string_buffer(124)
        _method(obj, _GET_ERROR_MESSAGE, None, c_char_p)(obj, message)
        raise AsioError(_text(message.value) or "the driver wouldn't start")

    name = ctypes.create_string_buffer(32)
    _method(obj, _GET_DRIVER_NAME, None, c_char_p)(obj, name)
    version = _method(obj, _GET_DRIVER_VERSION, c_long)(obj)

    n_in, n_out = c_long(), c_long()
    _check(_method(obj, _GET_CHANNELS, c_long, POINTER(c_long), POINTER(c_long))(
        obj, byref(n_in), byref(n_out)), "getChannels")

    can = _method(obj, _CAN_SAMPLE_RATE, c_long, c_double)
    rates = tuple(r for r in RATES if can(obj, float(r)) == ASE_OK)
    current = c_double()
    if _method(obj, _GET_SAMPLE_RATE, c_long, POINTER(c_double))(obj, byref(current)) != ASE_OK:
        current.value = 0

    get_info = _method(obj, _GET_CHANNEL_INFO, c_long, POINTER(_ChannelInfo))
    inputs = []
    for i in range(n_in.value):
        info = _ChannelInfo(channel=i, isInput=1)
        _check(get_info(obj, byref(info)), f"getChannelInfo({i})")
        inputs.append(Channel(_text(info.name) or f"Input {i + 1}",
                              SAMPLE_TYPES.get(info.type, f"type {info.type}")))

    sizes = [c_long() for _ in range(4)]  # smallest, largest, preferred, granularity
    _check(_method(obj, _GET_BUFFER_SIZE, c_long, *[POINTER(c_long)] * 4)(
        obj, *map(byref, sizes)), "getBufferSize")

    return AsioInfo(_text(name.value), version, rates, round(current.value), tuple(inputs),
                    n_out.value, (sizes[0].value, sizes[1].value, sizes[2].value))
