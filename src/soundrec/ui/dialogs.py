"""The Device menu's two dialogs, in 3.1's style.

Output Format says what Save As aims for: format, encoding, quality, rate and
channels. Each list depends on the one before it, so choosing a format refills
the encodings, an encoding the qualities and rates.

Recording Device picks where recordings come from. Choosing a device touches
no hardware: what it shows comes from the scan the window already has. Only
the Probe button asks a device about its formats, because asking can knock the
H2n to the wrong rate until it's replugged, and that button warns first.
WASAPI exclusive mode isn't offered: PortAudio repeats audio in it (WORKLOG).
"""

from __future__ import annotations

import soundfile as sf

from ..devices import API_ORDER, Device
from ..formats import RATES, channels_text
from ..output import (ONLY_RATES, OutputSpec, Target, channels_for, default_quality, format_names,
                      qualities, rate_for, subtype_names)
from ..probe import Probe
from .controls import LABEL_HEIGHT, ListBox, height_for
from .dialog import BUTTON_H, Dialog, wrap
from .fonts import system_font
from .raster import BLACK, Surface

M = 12               # between controls
BUTTON_W = 72
LINE = 16

COMMON_FORMATS = ("WAV", "FLAC", "MP3", "OGG", "M4A")  # at the top of the list: the rest are rare
BY_NAME = "From the file's name"
AS_THE_SOUND = "As the sound"
NO_QUALITY = "(no choices)"
NO_FORMAT = "(the name decides)"
CHANNEL_CHOICES = (None, 1, 2)


def rate_text(rate: int | None) -> str:
    return AS_THE_SOUND if rate is None else f"{rate:,} Hz"


def channel_text(channels: int | None) -> str:
    return AS_THE_SOUND if channels is None else channels_text([channels]).capitalize()


class OutputFormatDialog(Dialog):
    FORMAT_W, ENCODING_W = 270, 220
    QUALITY_W, RATE_W = 180, 140
    ROWS = 6

    def __init__(self, master, zoom: int, target: Target = Target(),
                 sound: tuple[int, int] | None = None):
        tall = height_for(self.ROWS)
        client_w = M + self.FORMAT_W + M + self.ENCODING_W + M + BUTTON_W + M
        client_h = M + 2 * (LABEL_HEIGHT + tall) + M + 2 * LINE + M
        super().__init__(master, zoom, "Output Format", client_w, client_h,
                         [("OK", "ok"), ("Cancel", "cancel")], "cancel")
        self.sound = sound
        cx, cy = self.client
        x0, x1 = cx + M, cx + M + self.FORMAT_W + M
        y0 = cy + M + LABEL_HEIGHT
        y1 = y0 + tall + M + LABEL_HEIGHT
        right = x1 + self.ENCODING_W - 1
        self.formats = ListBox((x0, y0, x0 + self.FORMAT_W - 1, y0 + tall - 1), "&Format:")
        self.encodings = ListBox((x1, y0, right, y0 + tall - 1), "&Encoding:")
        self.quality = ListBox((x0, y1, x0 + self.QUALITY_W - 1, y1 + tall - 1), "&Quality:")
        x2 = x0 + self.QUALITY_W + M
        self.rates = ListBox((x2, y1, x2 + self.RATE_W - 1, y1 + tall - 1), "&Rate:")
        self.channels = ListBox((x2 + self.RATE_W + M, y1, right, y1 + tall - 1), "C&hannels:")
        self.lists = [self.formats, self.encodings, self.quality, self.rates, self.channels]
        bx = right + 1 + M
        self.boxes = [(bx, y0 + i * (BUTTON_H + M), bx + BUTTON_W - 1,
                       y0 + i * (BUTTON_H + M) + BUTTON_H - 1) for i in range(2)]
        self.summary_at = (x0, y1 + tall + M)

        names = format_names()
        order = [n for n in COMMON_FORMATS if n in names] + \
                [n for n in names if n not in COMMON_FORMATS]
        self.format_keys: list[str | None] = [None] + order
        chosen = target.spec.format if target.spec else None
        self.formats.fill([BY_NAME] + [names[n] for n in order],
                          self.format_keys.index(chosen) if chosen in self.format_keys else 0)
        self.channels.fill([channel_text(c) for c in CHANNEL_CHOICES],
                           CHANNEL_CHOICES.index(target.channels)
                           if target.channels in CHANNEL_CHOICES else 0)
        self.rate_keys: list[int | None] = [None]
        self.quality_keys: list = []
        self._format_changed(target.spec, target.rate)

    # -- the lists depend on each other ------------------------------------------------

    @property
    def format(self) -> str | None:
        return self.format_keys[self.formats.selected or 0]

    @property
    def encoding(self) -> str | None:
        return self.encoding_keys[self.encodings.selected or 0] if self.format else None

    def _format_changed(self, spec: OutputSpec | None = None, rate: int | None = None) -> None:
        fmt = self.format
        if fmt is None:
            self.encoding_keys = []
            self.encodings.fill([NO_FORMAT], None)
            self.encodings.enabled = False
        else:
            names = subtype_names(fmt)
            self.encoding_keys = list(names)
            if spec is not None and spec.subtype in names:
                wanted = spec.subtype
            else:
                wanted = sf.default_subtype(fmt) if fmt != "M4A" else "AAC"
            self.encodings.fill(names.values(),
                                self.encoding_keys.index(wanted) if wanted in names else 0)
            self.encodings.enabled = True
        self._encoding_changed(spec, rate)

    def _encoding_changed(self, spec: OutputSpec | None = None, rate: int | None = None) -> None:
        wanted_rate = rate if rate is not None else self.rate
        if self.format is None:
            self.quality_keys = []
            self.quality.fill([NO_QUALITY], None)
            self.quality.enabled = False
            allowed = RATES
        else:
            bare = OutputSpec(self.format, self.encoding)
            self.quality_keys = list(qualities(bare))
            if self.quality_keys:
                keep = spec.quality if spec is not None and spec.quality in self.quality_keys \
                    else default_quality(bare)
                self.quality.fill([q.label for q in self.quality_keys],
                                  self.quality_keys.index(keep) if keep else 0)
            else:
                self.quality.fill([NO_QUALITY], None)
            self.quality.enabled = bool(self.quality_keys)
            allowed = ONLY_RATES.get(self.encoding, RATES)
        self.rate_keys = [None, *allowed]
        self.rates.fill([rate_text(r) for r in self.rate_keys],
                        self.rate_keys.index(wanted_rate) if wanted_rate in self.rate_keys else 0)
        if not self._can_focus(self.focus):
            self._move_focus(1)

    def changed(self, box) -> None:
        if box is self.formats:
            self._format_changed()
        elif box is self.encodings:
            self._encoding_changed()

    # -- the answer --------------------------------------------------------------------

    @property
    def rate(self) -> int | None:
        return self.rate_keys[self.rates.selected or 0] if self.rates.rows else None

    @property
    def result(self) -> Target:
        spec = None
        if self.format is not None:
            quality = self.quality_keys[self.quality.selected or 0] if self.quality_keys else None
            spec = OutputSpec(self.format, self.encoding, quality)
        return Target(spec, self.rate, CHANNEL_CHOICES[self.channels.selected or 0])

    def summary(self) -> str:
        target = self.result
        what = f"Save As writes {target.spec.describe()}" if target.spec else \
            "Save As takes the format from the file's name"
        if target.rate is not None:
            what += f" at {target.rate:,} Hz"
        if target.channels is not None:
            what += f", {channels_text([target.channels])}"
        what += ". New recordings run at that rate." if target.rate else "."
        if self.sound is not None:
            rate, channels = self.sound
            new_rate, new_channels = target.rate or rate, target.channels or channels
            if target.spec is not None:
                new_rate = rate_for(target.spec, new_rate)
                new_channels = channels_for(target.spec, new_channels)
            if (new_rate, new_channels) != (rate, channels):
                what += (f" This sound, {rate:,} Hz {channels_text([channels])}, would become "
                         f"{new_rate:,} Hz {channels_text([new_channels])}.")
        return what

    def paint_client(self, s: Surface) -> None:
        font = system_font()
        x, y = self.summary_at
        for i, line in enumerate(wrap(self.summary(), font, self.width - 2 * x)[:2]):
            s.text(font, x, y + i * LINE, line, BLACK)


# -- Recording Device -------------------------------------------------------------------

def sentence(text: str) -> str:
    """Text as a sentence: unlike str.capitalize, it leaves the rest of it alone."""
    return text[:1].upper() + text[1:] + "."


def is_touchy(device: Device) -> bool:
    """The H2n, or anything else of ZOOM's: asking can knock its clock (README)."""
    name = device.name.lower()
    return "h2n" in name or "zoom" in name


def advice(device: Device) -> list[str]:
    """What this laptop taught us about a device, to say before it costs a take."""
    name = device.name.lower()
    if device.api == "ASIO" and ("zoom" in name or "h2n" in name):
        return ["Its ASIO driver loses over half the audio: record it over WASAPI instead."]
    if device.api == "WDM-KS" and "pc speaker" in name:
        return ["A reference pin: what the speakers are playing, not a microphone."]
    return []


def channel_names(device: Device, probe: Probe | None) -> str:
    """ASIO names its channels, once asked. Nothing else does."""
    if probe is not None and probe.channel_names:
        return ", ".join(probe.channel_names)
    if device.channels == 1:
        return "Mono"
    if device.channels == 2:
        return "Left, Right"
    return ", ".join(str(n) for n in range(1, device.channels + 1))


def describe(device: Device, probe: Probe | None, asking: bool = False,
             error: str | None = None) -> list[str]:
    """The lines under the lists. None of this asks the device anything."""
    lines = []
    endpoint = device.endpoint
    if endpoint is not None:
        kind = ", ".join(part for part in (endpoint.form_factor, endpoint.bus) if part)
        if endpoint.engine_format is not None:
            lines.append(f"Windows runs it at {endpoint.engine_format}" + (f" ({kind})." if kind else "."))
        elif kind:
            lines.append(sentence(kind))
    lines.append(f"Channels: {channel_names(device, probe)}.")
    if asking:
        lines.append("Asking the device...")
    elif error:
        lines.append(f"Couldn't ask it: {error}")
    elif probe is None:
        lines.append("Native formats: press Probe to ask the device.")
    elif probe.native:
        lines.append(f"Native: {probe.summary()}.")
        if probe.error:
            lines.append(probe.error)
        elif probe.note:
            lines.append(sentence(probe.note))
    else:
        lines.append(sentence(probe.note))
    return lines + advice(device)


class RecordingDeviceDialog(Dialog):
    API_W, DEVICE_W = 130, 380
    ROWS = 8
    DETAIL_LINES = 7

    def __init__(self, master, zoom: int, scan, current: Device | None, probes: dict,
                 start_probe=None):
        """probes: answers so far, by device key, kept by the window between
        showings. start_probe(device, done) runs a probe on the audio thread
        and calls done(answer, error) on the UI thread; False if it can't yet."""
        tall = height_for(self.ROWS)
        client_w = M + self.API_W + M + self.DEVICE_W + M + BUTTON_W + M
        client_h = M + LABEL_HEIGHT + tall + M + self.DETAIL_LINES * LINE + M
        super().__init__(master, zoom, "Recording Device", client_w, client_h,
                         [("OK", "ok"), ("Cancel", "cancel"), ("&Probe", "probe")], "cancel")
        self.scan, self.probes, self.start_probe = scan, probes, start_probe
        self.asking: str | None = None      # the key being probed
        self.errors: dict[str, str] = {}
        cx, cy = self.client
        x0, y0 = cx + M, cy + M + LABEL_HEIGHT
        x1 = x0 + self.API_W + M
        self.api_list = ListBox((x0, y0, x0 + self.API_W - 1, y0 + tall - 1), "&API:")
        self.device_list = ListBox((x1, y0, x1 + self.DEVICE_W - 1, y0 + tall - 1), "&Device:")
        self.lists = [self.api_list, self.device_list]
        bx = x1 + self.DEVICE_W + M
        self.boxes = [(bx, y0 + i * (BUTTON_H + M), bx + BUTTON_W - 1,
                       y0 + i * (BUTTON_H + M) + BUTTON_H - 1) for i in range(3)]
        self.details_at = (x0, y0 + tall + M)
        self.apis = [a for a in API_ORDER if any(d.api == a for d in scan.inputs)]
        self.api_list.fill(self.apis, self.apis.index(current.api)
                           if current is not None and current.api in self.apis else 0)
        self._api_changed(current)

    @property
    def api(self) -> str | None:
        return self.apis[self.api_list.selected] if self.api_list.selected is not None else None

    def _api_changed(self, current: Device | None = None) -> None:
        self.devices = [d for d in self.scan.inputs if d.api == self.api]
        rows = [d.name + (" (default)" if d.is_default else "") for d in self.devices]
        chosen = next((i for i, d in enumerate(self.devices) if current is not None
                       and d.key == current.key), None)
        if chosen is None:
            chosen = next((i for i, d in enumerate(self.devices) if d.is_default), 0)
        # Endpoints that can't be used now: unplugged jacks and the like, shown greyed.
        others = []
        if self.api == "WASAPI":
            others = [f"{e.name} ({e.state})" for e in self.scan.endpoints
                      if e.flow == "capture" and e.state != "active" and not e.hidden]
        self.device_list.fill(rows + others, chosen if self.devices else None,
                              range(len(rows), len(rows) + len(others)))
        self._device_changed()

    def _device_changed(self) -> None:
        device = self.device
        self._answer_converted(device)
        converted = device is not None and device.key in self.probes \
            and not self.probes[device.key].native
        if device is None or converted or self.asking is not None:
            self.dead = {2}
        else:
            self.dead = set()

    def _answer_converted(self, device: Device | None) -> None:
        """MME, DirectSound and loopback take anything, so the answer's known
        without asking; a probe of those touches no hardware."""
        if device is not None and device.api in ("MME", "DirectSound", "Loopback") \
                and device.key not in self.probes:
            from ..probe import probe

            self.probes[device.key] = probe(device)

    def changed(self, box) -> None:
        if box is self.api_list:
            self._api_changed()
        else:
            self._device_changed()

    @property
    def device(self) -> Device | None:
        at = self.device_list.selected
        return self.devices[at] if at is not None and at < len(self.devices) else None

    def clicked(self, button: int) -> bool:
        if self.buttons[button][1] != "probe":
            return super().clicked(button)
        self.probe_device()
        return False

    def probe_device(self) -> None:
        device = self.device
        if device is None or self.start_probe is None:
            return
        if is_touchy(device) and self.message(
                f"Asking {device.name} about its formats can knock it to the wrong sample rate, "
                "and voices then come out deep until it's unplugged and plugged back in.\n\n"
                "Ask it anyway?", [("&Yes", "yes"), ("&No", "no")], kind="warning") != "yes":
            return

        def done(answer, error):
            self.asking = None
            if error is not None:
                self.errors[device.key] = str(error)
            else:
                self.errors.pop(device.key, None)
                self.probes[device.key] = answer
            self._device_changed()
            self.refresh()

        if self.start_probe(device, done) is False:
            self.errors[device.key] = "the device list is busy: try again in a moment"
            return
        self.asking = device.key
        self._device_changed()

    def details(self) -> list[str]:
        device = self.device
        if device is None:
            return []
        lines = describe(device, self.probes.get(device.key), self.asking == device.key,
                         self.errors.get(device.key))
        font = system_font()
        return [row for line in lines for row in wrap(line, font, self.width - 2 * self.details_at[0])]

    def paint_client(self, s: Surface) -> None:
        font = system_font()
        x, y = self.details_at
        for i, line in enumerate(self.details()[:self.DETAIL_LINES]):
            s.text(font, x, y + i * LINE, line, BLACK)
