"""Windows audio endpoints, read from the MMDevices registry key.

The audio service records every endpoint it has ever seen there, including the
disabled, unplugged and not-present ones that the device APIs leave out, and
keeps each one's state current. Each endpoint also stores the format the audio
engine runs it at: the "Default Format" in the Sound control panel, and the
format MME, DirectSound and shared WASAPI are really converting from.
"""

from __future__ import annotations

import struct
import uuid
import winreg
from dataclasses import dataclass

from .formats import channels_text

ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"

# Property keys, spelt the way the registry stores them.
PKEY_DEVICE_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"     # "Microphone Array"
PKEY_ENUMERATOR = "{a45c254e-df1c-4efd-8020-67d146a850e0},24"     # "USB", "INTELAUDIO"
PKEY_INTERFACE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # "Realtek(R) Audio"
PKEY_FORM_FACTOR = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},0"
PKEY_ENGINE_FORMAT = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"

# MMDevice ids put the data flow in front of the registry key's GUID.
FLOWS = (("render", "{0.0.0.00000000}"), ("capture", "{0.0.1.00000000}"))

STATES = {1: "active", 2: "disabled", 4: "not present", 8: "unplugged"}

# EndpointFormFactor, in enum order.
FORM_FACTORS = ("network", "speakers", "line level", "headphones", "microphone",
                "headset", "handset", "digital passthrough", "S/PDIF",
                "HDMI/DisplayPort", "")

WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
SUBTYPE_IEEE_FLOAT = uuid.UUID("00000003-0000-0010-8000-00aa00389b71")
VT_BLOB = 0x41


@dataclass(frozen=True)
class WaveFormat:
    rate: int
    channels: int
    bits: int        # bits per sample in the container
    valid_bits: int  # bits that carry signal: 24 of 32, say
    is_float: bool

    def __str__(self) -> str:
        depth = f"{self.valid_bits}-bit" + (" float" if self.is_float else "")
        if self.valid_bits != self.bits:
            depth += f" (in {self.bits})"
        return f"{self.rate:,} Hz, {depth}, {channels_text([self.channels])}"


def parse_waveformat(blob: bytes) -> WaveFormat | None:
    """A WAVEFORMATEX or WAVEFORMATEXTENSIBLE, as a registry property stores it.

    Stored property values start with an 8-byte header whose first word is the
    variant type; for a blob the structure follows it.
    """
    if len(blob) >= 8 and struct.unpack_from("<I", blob)[0] == VT_BLOB:
        blob = blob[8:]
    if len(blob) < 16:
        return None
    tag, channels, rate, _bytes_per_sec, _align, bits = struct.unpack_from("<HHIIHH", blob)
    is_float = tag == WAVE_FORMAT_IEEE_FLOAT
    valid = bits
    if tag == WAVE_FORMAT_EXTENSIBLE and len(blob) >= 40:
        valid = struct.unpack_from("<H", blob, 18)[0] or bits
        is_float = uuid.UUID(bytes_le=bytes(blob[24:40])) == SUBTYPE_IEEE_FLOAT
    elif tag not in (WAVE_FORMAT_PCM, WAVE_FORMAT_IEEE_FLOAT):
        return None
    return WaveFormat(rate, channels, bits, valid, is_float)


@dataclass(frozen=True)
class Endpoint:
    id: str            # the MMDevice id that WASAPI and soundcard use
    flow: str          # "capture" or "render"
    description: str   # "Microphone Array"
    interface: str     # "Realtek(R) Audio"
    state: str         # "active", "disabled", "not present" or "unplugged"
    hidden: bool       # Windows sets extra state bits on endpoints it keeps out of sight
    form_factor: str   # "microphone", "line level"... ("" when unknown)
    bus: str           # "USB", "INTELAUDIO"...
    engine_format: WaveFormat | None

    @property
    def name(self) -> str:
        """The friendly name, as WASAPI and DirectSound show it."""
        return f"{self.description} ({self.interface})" if self.interface else self.description


def make_endpoint(flow: str, id: str, state: int, props: dict) -> Endpoint:
    """An Endpoint from a key's DeviceState and its Properties values."""
    def text(key):
        value = props.get(key)
        return value if isinstance(value, str) else ""

    form = props.get(PKEY_FORM_FACTOR)
    blob = props.get(PKEY_ENGINE_FORMAT)
    return Endpoint(
        id=id,
        flow=flow,
        description=text(PKEY_DEVICE_DESC) or "(unnamed)",
        interface=text(PKEY_INTERFACE_NAME),
        state=STATES.get(state & 0xF, f"state {state & 0xF}"),
        # Seen here on phantom "Internal AUX Jack" endpoints and a stale HDMI
        # pin (0x10000004, 0x20000004), none of which the Sound panel lists.
        hidden=bool(state & ~0xF),
        form_factor=FORM_FACTORS[form] if isinstance(form, int) and 0 <= form < len(FORM_FACTORS) else "",
        bus=text(PKEY_ENUMERATOR),
        engine_format=parse_waveformat(blob) if isinstance(blob, bytes) else None,
    )


def _subkeys(key) -> list[str]:
    names = []
    while True:
        try:
            names.append(winreg.EnumKey(key, len(names)))
        except OSError:
            return names


def _values(key) -> dict:
    values = {}
    i = 0
    while True:
        try:
            name, value, _type = winreg.EnumValue(key, i)
        except OSError:
            return values
        values[name] = value
        i += 1


def _walk(read_props: bool):
    """(flow, id, DeviceState, Properties values) for every endpoint key."""
    for flow, prefix in FLOWS:
        try:
            flow_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ROOT + "\\" + flow.title())
        except OSError:
            continue
        with flow_key:
            for guid in _subkeys(flow_key):
                try:
                    with winreg.OpenKey(flow_key, guid) as key:
                        state = winreg.QueryValueEx(key, "DeviceState")[0]
                        props = {}
                        if read_props:
                            with winreg.OpenKey(key, "Properties") as pkey:
                                props = _values(pkey)
                except OSError:
                    continue  # half-written by the audio service, or not ours to read
                yield flow, f"{prefix}.{guid}", state, props


def read_endpoints() -> list[Endpoint]:
    return [make_endpoint(*row) for row in _walk(read_props=True)]


def read_states() -> dict[str, int]:
    """Every endpoint's id and raw DeviceState: cheap enough to poll."""
    return {id: state for _flow, id, state, _props in _walk(read_props=False)}
