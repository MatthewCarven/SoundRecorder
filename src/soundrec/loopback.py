"""WASAPI loopback: recording what a playback device is playing.

The PortAudio that ships with sounddevice doesn't offer loopback, so this goes
through soundcard, which drives WASAPI itself. Loopback runs in shared mode,
and soundcard asks Windows to convert, so any rate and channel count works;
the endpoint's engine format is the native one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopbackSource:
    id: str          # the render endpoint's MMDevice id
    name: str
    channels: int
    is_default: bool  # Windows' default playback device


def loopback_sources() -> list[LoopbackSource]:
    from . import pa  # noqa: F401  (PortAudio must claim the thread's COM apartment first)
    import soundcard

    try:
        default_id = soundcard.default_speaker().id
    except Exception:
        default_id = None
    return [LoopbackSource(m.id, m.name, m.channels, m.id == default_id)
            for m in soundcard.all_microphones(include_loopback=True) if m.isloopback]
