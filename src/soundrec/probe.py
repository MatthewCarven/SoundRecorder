"""Which formats a capture device really takes.

How far an answer can be trusted depends on the API (measured on this laptop,
2026-11-02):

- MME and DirectSound accept anything: Windows converts to and from the format
  the audio engine runs the endpoint at, so probing proves nothing. That engine
  format is the native one.
- WASAPI in exclusive mode, with PortAudio told not to substitute another
  sample type (explicit_sample_format), hands the format straight to the
  driver: an honest answer for rate, sample type and channels together.
- WDM-KS checks rates and channel counts against the driver's pin, but
  PortAudio converts sample types itself, so those can't be seen.
- ASIO is asked directly (asio.py) for its rates, channels and sample type.
- Loopback is shared-mode WASAPI with Windows converting, like MME.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .devices import Device
from .formats import RATES, SAMPLE_TYPES, channels_text, rates_text, types_text

# PortAudio's answers that mean "not that format", as opposed to "can't ask":
# invalid sample rate, invalid channel count, sample format not supported.
FORMAT_REFUSALS = {-9997, -9998, -9994}


@dataclass(frozen=True)
class Probe:
    native: bool                   # False: Windows converts, so this says little about the hardware
    rates: tuple[int, ...] = ()
    sample_types: tuple[str, ...] = ()  # () when converted on the way and the native one can't be seen
    channels: tuple[int, ...] = ()
    # (rate, sample type, channels) the device took together, where they were
    # tried together. When sample types are unknown the type is "float32" here
    # and stands for any: PortAudio converts.
    combos: frozenset = frozenset()
    channel_names: tuple[str, ...] = ()
    note: str = ""
    error: str = ""

    @classmethod
    def from_combos(cls, combos, *, types_known: bool = True, **kw) -> Probe:
        return cls(
            rates=tuple(sorted({c[0] for c in combos})),
            sample_types=tuple(t for t in SAMPLE_TYPES if any(c[1] == t for c in combos))
            if types_known else (),
            channels=tuple(sorted({c[2] for c in combos})),
            combos=frozenset(combos),
            **kw)

    def summary(self) -> str:
        types = types_text(self.sample_types) if self.sample_types else "any sample type (converted)"
        return f"{rates_text(self.rates)}; {types}; {channels_text(self.channels)}"


def _error_code(error: Exception) -> int | None:
    # sounddevice raises PortAudioError(message, code, ...); fall back on the text.
    if len(error.args) > 1 and isinstance(error.args[1], int):
        return error.args[1]
    match = re.search(r"PaErrorCode (-?\d+)", str(error))
    return int(match[1]) if match else None


def _grid(device: Device, check, types, extra):
    """Try every rate x type x channel count; return what passed and any real errors."""
    combos, errors = set(), []
    for rate in RATES:
        for sample_type in types:
            for channels in range(1, device.channels + 1):
                try:
                    check(device.index, channels=channels, dtype=sample_type,
                          samplerate=rate, extra_settings=extra)
                except Exception as e:
                    if _error_code(e) not in FORMAT_REFUSALS:
                        errors.append(str(e))
                else:
                    combos.add((rate, sample_type, channels))
    return combos, errors


def _converted_note(device: Device, what: str) -> str:
    fmt = device.endpoint.engine_format if device.endpoint else None
    return f"{what}, converted by Windows" + (f" from the engine's {fmt}" if fmt else "")


def probe(device: Device, *, check=None, exclusive=None, asio_query=None) -> Probe:
    """What `device` takes. check, exclusive and asio_query stand in for
    sounddevice's check_input_settings, WasapiSettings(exclusive) and
    asio.query in tests; by default the real ones are used."""
    if device.api in ("MME", "DirectSound", "Loopback"):
        return Probe(native=False, rates=RATES, sample_types=SAMPLE_TYPES,
                     channels=tuple(range(1, device.channels + 1)),
                     note=_converted_note(device, "takes anything"))

    if check is None:
        from .pa import sd
        check = sd.check_input_settings
        exclusive = exclusive or sd.WasapiSettings(exclusive=True, explicit_sample_format=True)

    if device.api == "WASAPI":
        shared = _converted_note(device, "shared mode takes anything")
        combos, errors = _grid(device, check, SAMPLE_TYPES, exclusive)
        if not combos:
            return Probe(native=True, note=shared,
                         error=errors[0] if errors else "took no format in exclusive mode")
        return Probe.from_combos(combos, native=True, note="native is exclusive mode; " + shared)

    if device.api == "ASIO":
        return _probe_asio(device, check, asio_query)

    # WDM-KS, and anything PortAudio adds later: one sample type stands for all.
    combos, errors = _grid(device, check, ("float32",), None)
    if not combos:
        return Probe(native=True, error=errors[0] if errors else "took no format")
    return Probe.from_combos(combos, types_known=False, native=True,
                             note="rates and channels from the driver; PortAudio converts sample types")


def _probe_asio(device: Device, check, asio_query) -> Probe:
    if asio_query is None:
        from .asio import query as asio_query
    try:
        info = asio_query(device.name)
    except Exception as e:
        # PortAudio's way: rates only, reloading the driver for each one (slow).
        rates = []
        for rate in RATES:
            try:
                check(device.index, channels=1, dtype="float32", samplerate=rate)
            except Exception:
                continue
            rates.append(rate)
        return Probe(native=True, rates=tuple(rates), channels=tuple(range(1, device.channels + 1)),
                     note="rates from PortAudio; sample type not known",
                     error=f"couldn't ask the driver directly: {e}")
    smallest, largest, preferred = info.buffer_sizes
    return Probe(native=True, rates=info.rates,
                 sample_types=tuple(dict.fromkeys(c.sample_type for c in info.inputs)),
                 channels=tuple(range(1, len(info.inputs) + 1)),
                 channel_names=tuple(c.name for c in info.inputs),
                 note=f"from the driver; buffer {smallest}-{largest} frames, prefers {preferred}")
