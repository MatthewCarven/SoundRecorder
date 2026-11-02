"""Every audio device on every Windows API, in one list.

PortAudio lists MME, DirectSound, WASAPI, WDM-KS and ASIO devices; soundcard
adds WASAPI loopback; the registry adds the endpoints none of them show, and
each device is tied to its endpoint where the names allow it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .endpoints import Endpoint, read_endpoints

# Most direct first: the order the device list shows them in.
API_ORDER = ("WASAPI", "Loopback", "ASIO", "WDM-KS", "DirectSound", "MME")

# PortAudio's host API names, shortened to what the UI shows.
PA_API_NAMES = {
    "MME": "MME",
    "Windows DirectSound": "DirectSound",
    "Windows WASAPI": "WASAPI",
    "Windows WDM-KS": "WDM-KS",
    "ASIO": "ASIO",
}

# WAVEINCAPS keeps 32 characters including the terminator, so MME cuts
# "Microphone Array (Realtek(R) Audio)" to "Microphone Array (Realtek(R) Au".
MME_NAME_LIMIT = 31


@dataclass(frozen=True)
class Device:
    api: str                     # one of API_ORDER
    name: str
    channels: int                # the most channels the API offers
    default_rate: int
    index: int | None = None     # PortAudio's index; None for loopback
    endpoint: Endpoint | None = None
    is_default: bool = False     # this API's default device

    @property
    def key(self) -> str:
        """What to remember a choice by: indexes change on every rescan."""
        return f"{self.api}: {self.name}"


@dataclass(frozen=True)
class Scan:
    inputs: list[Device]
    outputs: list[Device]
    endpoints: list[Endpoint] = field(default_factory=list)


def match_endpoint(api: str, name: str, endpoints: list[Endpoint]) -> Endpoint | None:
    """The endpoint behind a PortAudio device, when its name says which.

    WASAPI and DirectSound use the friendly name and MME a truncated one.
    WDM-KS names the driver's pin instead, and ASIO bypasses endpoints.
    """
    if api in ("WASAPI", "DirectSound"):
        hits = [e for e in endpoints if e.name == name]
    elif api == "MME":
        hits = [e for e in endpoints
                if e.name == name or (len(name) == MME_NAME_LIMIT and e.name.startswith(name))]
    else:
        return None
    return hits[0] if len(hits) == 1 else None


def _api_rank(device: Device) -> int:
    return API_ORDER.index(device.api) if device.api in API_ORDER else len(API_ORDER)


def build_devices(direction: str, pa_devices, pa_apis, endpoints: list[Endpoint],
                  loopbacks=()) -> list[Device]:
    """Devices for one direction ("input" or "output") from PortAudio's tables.

    pa_devices and pa_apis are what sounddevice's query_devices() and
    query_hostapis() return; loopbacks are LoopbackSources (inputs only).
    """
    flow = "capture" if direction == "input" else "render"
    active = [e for e in endpoints if e.flow == flow and e.state == "active"]
    found = []
    for index, d in enumerate(pa_devices):
        channels = d[f"max_{direction}_channels"]
        if channels < 1:
            continue
        hostapi = pa_apis[d["hostapi"]]
        api = PA_API_NAMES.get(hostapi["name"], hostapi["name"])
        found.append(Device(api, d["name"], channels, round(d["default_samplerate"]), index,
                            match_endpoint(api, d["name"], active),
                            hostapi[f"default_{direction}_device"] == index))
    renders = {e.id: e for e in endpoints if e.flow == "render"}
    for source in loopbacks:
        endpoint = renders.get(source.id)
        rate = endpoint.engine_format.rate if endpoint and endpoint.engine_format else 48000
        found.append(Device("Loopback", source.name, source.channels, rate, None, endpoint,
                            source.is_default))
    return sorted(found, key=_api_rank)  # stable: PortAudio's order within an API


def scan(rescan: bool = False) -> Scan:
    """Look at the system as it is now; rescan=True makes PortAudio look again too."""
    from . import pa
    from .loopback import loopback_sources

    if rescan:
        pa.rescan()
    pa_devices = pa.sd.query_devices()
    pa_apis = pa.sd.query_hostapis()
    endpoints = read_endpoints()
    try:
        loopbacks = loopback_sources()
    except Exception:
        loopbacks = []  # no loopback is no reason to list nothing
    return Scan(build_devices("input", pa_devices, pa_apis, endpoints, loopbacks),
                build_devices("output", pa_devices, pa_apis, endpoints),
                endpoints)
