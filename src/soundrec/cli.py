"""sound-recorder on the command line: list devices, probe them, watch them,
record from them (`rec`), and save what a crash left behind (`recover`)."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

from . import __version__


def _print_device(device, probe_it: bool) -> None:
    from .probe import probe

    endpoint = device.endpoint
    mark = "*" if device.is_default else " "
    detail = f"{device.channels} ch, {device.default_rate:,} Hz"
    if endpoint and endpoint.form_factor:
        detail += f", {endpoint.form_factor}"
    if endpoint and endpoint.bus:
        detail += f", {endpoint.bus}"
    print(f"  {mark} {device.name}  ({detail})")
    if not probe_it:
        if endpoint and endpoint.engine_format:
            print(f"      engine: {endpoint.engine_format}")
        return
    result = probe(device)
    if result.native and (result.rates or result.channels):
        print(f"      native: {result.summary()}")
    if result.channel_names:
        print(f"      inputs: {', '.join(result.channel_names)}")
    if result.note:
        print(f"      {result.note}")
    if result.error:
        print(f"      ! {result.error}")


def _print_scan(scan, args) -> None:
    from .devices import API_ORDER

    groups = [("Capture", scan.inputs)]
    if args.outputs:
        groups.append(("Playback", scan.outputs))
    for title, devices in groups:
        if args.device:
            devices = [d for d in devices if args.device.lower() in d.name.lower()]
        apis = [api for api in API_ORDER if any(d.api == api for d in devices)]
        print(f"{title} devices: {len(devices)} over {len(apis)} APIs  (* = that API's default)")
        for api in apis:
            print(f"\n {api}")
            for device in devices:
                if device.api == api:
                    _print_device(device, args.probe and title == "Capture")
        print()

    others = [e for e in scan.endpoints
              if e.state != "active" and (args.all or not e.hidden)
              and (args.outputs or e.flow == "capture")]
    if others:
        print("Endpoints Windows knows but can't use now" + ("" if args.all else " (--all adds hidden ones)"))
        for e in sorted(others, key=lambda e: (e.flow, e.state, e.name)):
            hidden = ", hidden" if e.hidden else ""
            print(f"    {e.flow:7}  {e.state:11}  {e.name}{hidden}")


def _watch() -> int:
    from .devices import scan
    from .endpoints import read_endpoints
    from .hotplug import DeviceWatcher

    def on_change(change):
        names = {e.id: e for e in read_endpoints()}
        stamp = time.strftime("%H:%M:%S")

        def label(id):
            e = names.get(id)
            return f"{e.name} [{e.flow}, {e.state}]" if e else id

        for id in change.appeared:
            print(f"{stamp}  appeared:  {label(id)}")
        for id in change.vanished:
            print(f"{stamp}  vanished:  {id}")
        for id in change.changed:
            print(f"{stamp}  now        {label(id)}")
        # Can't rescan from inside the watcher's callback in the app (a stream
        # may be open); here nothing is, so show the effect straight away.
        print(f"{stamp}  PortAudio now lists {len(scan(rescan=True).inputs)} capture devices", flush=True)

    watcher = DeviceWatcher(on_change)
    watcher.start()
    print("Watching for audio devices coming and going. Ctrl+C stops.", flush=True)
    try:
        while watcher.error is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
    if watcher.error is not None:
        print(f"Stopped watching: {watcher.error}", file=sys.stderr)
        return 1
    return 0


# -- rec ----------------------------------------------------------------------

def choose_device(inputs, text=None, api=None):
    """The capture device `text` (part of its name) and `api` mean: the most
    direct API's, when several APIs have it (inputs come in API_ORDER).
    No text: the default device. ValueError when it's not clear which."""
    pool = list(inputs)
    if api:
        pool = [d for d in pool if d.api.lower() == api.lower()]
        if not pool:
            raise ValueError(f"no {api} capture devices")
    if text:
        exact = [d for d in pool if d.name.lower() == text.lower()]
        pool = exact or [d for d in pool if text.lower() in d.name.lower()]
    else:
        pool = [d for d in pool if d.is_default]
    if not pool:
        raise ValueError(f"no capture device matches {text!r}" if text else "no default capture device")
    same_api = [d for d in pool if d.api == pool[0].api]
    if len(same_api) > 1:
        names = "\n".join(f"  {d.key}" for d in same_api)
        raise ValueError(f"{len(same_api)} devices match; say which:\n{names}")
    return same_api[0]


def parse_pick(text):
    """'3,4' or '1-4' (1-based, as the UI shows them) -> 0-based channels."""
    if not text:
        return None
    channels = []
    for part in text.split(","):
        first, dash, last = part.strip().partition("-")
        try:
            first, last = int(first), int(last) if dash else int(first)
            if last < first:
                raise ValueError
        except ValueError:
            raise ValueError(f"--pick wants channel numbers like 3,4 or 1-4, not {text!r}") from None
        channels += range(first, last + 1)
    if min(channels) < 1:
        raise ValueError("channels count from 1")
    return tuple(c - 1 for c in channels)


def plan_channels(available, out=None, pick=None, keep_all=False):
    """(channels to capture, channels to keep, pick) for a device with
    `available` inputs. By default: stereo from the first two, or mono mixed
    from them; a mono device copied up if stereo is asked for."""
    if keep_all:
        if pick or (out and out != available):
            raise ValueError("--keep-all keeps every channel: leave out --pick and --channels")
        return available, available, None
    if pick:
        if max(pick) >= available:
            raise ValueError(f"the device has {available} channels")
        return max(pick) + 1, out or len(pick), pick
    out = out or min(available, 2)
    return min(available, max(out, 2)), out, None


def native_rate(device) -> int:
    """The rate to capture at when none is asked for. PortAudio says 44.1 kHz
    for every MME and DirectSound device, but Windows converts those from the
    engine's rate, so asking for that one leaves the audio unconverted."""
    engine = device.endpoint.engine_format if device.endpoint else None
    if device.api in ("MME", "DirectSound") and engine:
        return engine.rate
    return device.default_rate


def _clock(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


def _levels(peaks) -> str:
    names = ["L", "R"] if len(peaks) == 2 else [str(i + 1) for i in range(len(peaks))]
    def db(p):
        value = 20 * math.log10(p) if p > 0 else -math.inf
        return "  -inf" if value == -math.inf else f"{value:6.1f}"
    return "  ".join(f"{n} {db(p)} dB" + ("!" if p >= 1 else " ") for n, p in zip(names, peaks))


def _report(rec) -> list[str]:
    s = rec.stats
    lines = [f"Captured {s.seconds_in:.1f} s ({s.frames_in:,} frames at {s.capture_rate:,} Hz); "
             f"wrote {s.frames_out:,} frames at {rec.rate:,} Hz."]
    rate, ppm, spread = s.measured_rate(), s.clock_ppm(), s.clock_uncertainty_ppm()
    if rate is not None:
        lines.append(f"Device clock: {rate:,.1f} frames/s by the PC's clock "
                     f"({ppm:+.1f} ppm, give or take {spread:.1f}).")
        problem = s.clock_problem(min_seconds=0)
        if problem:
            lines.append(f"  The take is no good: {problem}.")
    lost = s.overflows + s.discontinuities
    detail = (f"longest wait between blocks {s.max_gap * 1000:.0f} ms, "
              f"worker at most {s.max_lag:.2f} s behind")
    if lost:
        lines.append(f"Dropouts: {s.overflows} overflows, {s.discontinuities} gaps reported ({detail}).")
    else:
        lines.append(f"Dropouts: none reported ({detail}).")
    if s.clipped:
        lines.append(f"Clipped: {s.clipped:,} samples at or past full scale.")
    return lines


def _rec(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="sound-recorder rec",
        description="Record from a capture device into a file, converting rate and channels "
                    "as it records. Ctrl+C stops.")
    parser.add_argument("out", help="the file to make; its extension picks the format "
                                    "(.wav .flac .mp3 .ogg .opus .aiff .caf .w64 .rf64 ...)")
    parser.add_argument("--device", metavar="TEXT",
                        help="part of the device's name (default: Windows' default device)")
    parser.add_argument("--api", help="WASAPI, Loopback, ASIO, WDM-KS, DirectSound or MME "
                                      "(default: the most direct one that has the device)")
    parser.add_argument("--capture-rate", type=int, metavar="HZ",
                        help="rate to open the device at (default: its own, or for MME and "
                             "DirectSound the rate Windows runs it at)")
    parser.add_argument("--rate", type=int, metavar="HZ",
                        help="rate of the file (default: the capture rate); converted live")
    parser.add_argument("--channels", type=int, metavar="N",
                        help="channels in the file (default: 2, or 1 for a mono device)")
    parser.add_argument("--pick", metavar="LIST",
                        help="device channels to use, from 1: 3,4 or 1-4 (several into "
                             "--channels 1 are mixed)")
    parser.add_argument("--keep-all", action="store_true", help="keep every channel the device has")
    parser.add_argument("--bits", choices=("8", "16", "24", "32", "float"),
                        help="bit depth (default: the format's usual; 8 and 16 bits get TPDF dither)")
    parser.add_argument("--seconds", type=float, metavar="S", help="stop after S seconds")
    parser.add_argument("--live", action="store_true",
                        help="write the file as it records, not when it stops")
    parser.add_argument("--exclusive", action="store_true",
                        help="WASAPI exclusive mode (broken in this PortAudio: it repeats blocks, "
                             "so the take stops once the clock check sees it; see README)")
    parser.add_argument("--blocksize", type=int, default=0, metavar="FRAMES",
                        help="frames per block from PortAudio (default: let it choose)")
    parser.add_argument("--force", action="store_true", help="overwrite OUT if it exists")
    args = parser.parse_args(argv)

    from .output import preflight, spec_for

    out = Path(args.out)
    try:
        spec = spec_for(out, args.bits)
        pick = parse_pick(args.pick)
    except ValueError as e:
        parser.error(str(e))
    if out.exists() and not args.force:
        parser.error(f"{out} exists (--force overwrites it)")
    if not out.resolve().parent.is_dir():
        parser.error(f"no folder {out.resolve().parent}")

    from .devices import scan
    try:
        device = choose_device(scan().inputs, args.device, args.api)
        capture_channels, channels, pick = plan_channels(device.channels, args.channels, pick,
                                                         args.keep_all)
        capture_rate = args.capture_rate or native_rate(device)
        rate = args.rate or capture_rate
        preflight(spec, rate, channels)
    except ValueError as e:
        print(f"sound-recorder rec: {e}", file=sys.stderr)
        return 2

    from .capture import CaptureError, open_capture
    from .engine import Recorder

    try:
        source = open_capture(device, capture_rate, capture_channels, exclusive=args.exclusive,
                              blocksize=args.blocksize)
        rec = Recorder(source, rate, channels, pick, direct=(out, spec) if args.live else None,
                       limit=None if args.seconds is None else round(args.seconds * rate),
                       meta={"device": device.key, "target": str(out.resolve()),
                             "bits": args.bits})
    except (CaptureError, ValueError) as e:
        print(f"sound-recorder rec: {e}", file=sys.stderr)
        return 2

    mode = ("exclusive mode" if args.exclusive else "shared mode") if device.api == "WASAPI" else device.api
    conversion = [rec.converter.map.describe()]
    if not rec.converter.resampler.passthrough:
        conversion.append("resampled by soxr")
    if spec.dithered:
        conversion.append("TPDF dither")
    print(f"Recording from {device.key}")
    print(f"  captured   {capture_rate:,} Hz, {capture_channels} ch, {mode}")
    print(f"  into       {out}: {spec.describe()}, {rate:,} Hz, {channels} ch ({'; '.join(conversion)})")
    print(f"  written    {'as it records' if args.live else 'when recording stops'}")

    try:
        rec.start()
    except (CaptureError, OSError, RuntimeError) as e:  # the device, or the --live file
        print(f"sound-recorder rec: {e}", file=sys.stderr)
        return 1
    print(f"  working copy  {rec.take.path}")
    print("Ctrl+C stops." if args.seconds is None else f"Recording {args.seconds:g} s; Ctrl+C stops sooner.",
          flush=True)

    interactive = sys.stdout.isatty()
    last_print = started = time.monotonic()
    clock_problem = None
    try:
        while rec.failure is None and not rec.full.wait(0.25):
            s = rec.stats
            clock_problem = s.clock_problem()
            if clock_problem:
                break
            now = time.monotonic()
            quiet = now - started if s.last_time is None else time.perf_counter() - s.last_time
            status = f"  {_clock(s.seconds_in)}  {_levels(rec.take_peaks())}  behind {s.max_lag:.2f} s"
            if quiet > 2:
                status += f"  no audio from the device for {quiet:.0f} s"
            if interactive:
                print("\r" + status + "   ", end="", flush=True)
            elif now - last_print >= 30:
                print(status, flush=True)
                last_print = now
    except KeyboardInterrupt:
        pass
    take = rec.stop()
    if interactive:
        print()
    for line in _report(rec):
        print(line)
    if rec.failure is not None:
        print(f"Recording stopped early: {rec.failure}", file=sys.stderr)
    if clock_problem:
        print("Recording stopped early: the device's clock is wrong (above). "
              + ("PortAudio's exclusive mode repeats blocks: record without --exclusive."
                 if args.exclusive else "If it's the H2n, replug it."), file=sys.stderr)
    if rec.direct_error is not None:
        print(f"Writing {out} live failed ({rec.direct_error}); saving it from the working copy.",
              file=sys.stderr)

    try:
        if not args.live or rec.direct_error is not None:
            take.save(out, spec)
    except Exception as e:
        take.release()
        print(f"Couldn't save {out}: {e}\nThe take is kept: `sound-recorder recover` lists it.",
              file=sys.stderr)
        return 1
    size = out.stat().st_size
    size_text = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} kB"
    print(f"Saved {out} ({take.seconds:.1f} s, {size_text}).")
    take.discard()
    return 1 if rec.failure is not None or clock_problem else 0


# -- recover ------------------------------------------------------------------

def _recover(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="sound-recorder recover",
        description="Takes a crash left behind: list them, save one, or throw one away.")
    parser.add_argument("number", nargs="?", type=int, help="which take (from the list)")
    parser.add_argument("out", nargs="?",
                        help="file to save it to (default: the file it was being recorded for)")
    parser.add_argument("--bits", choices=("8", "16", "24", "32", "float"))
    parser.add_argument("--discard", action="store_true", help="delete the take")
    parser.add_argument("--force", action="store_true", help="overwrite OUT if it exists")
    args = parser.parse_args(argv)

    from .output import spec_for
    from .takes import default_dir, orphans

    takes = orphans()
    try:
        if args.number is None:
            if not takes:
                print(f"No takes left behind in {default_dir()}.")
            for i, t in enumerate(takes, 1):
                meant = t.info.get("target") or "?"
                print(f"{i}  {t.info.get('started', '?')}  {_clock(t.seconds)}  {t.rate:,} Hz  "
                      f"{t.channels} ch  {t.info.get('device', '?')}\n   for {meant}")
            return 0
        if not 1 <= args.number <= len(takes):
            parser.error(f"there are {len(takes)} takes left behind")
        take = takes[args.number - 1]
        if args.discard:
            take.discard()
            print(f"Deleted take {args.number}.")
            return 0
        out = Path(args.out or take.info.get("target") or "")
        if not args.out and (not take.info.get("target") or out.exists()):
            parser.error("say which file to save it to")
        if out.exists() and not args.force:
            parser.error(f"{out} exists (--force overwrites it)")
        try:
            spec = spec_for(out, args.bits or take.info.get("bits"))
        except ValueError as e:
            parser.error(str(e))
        frames = take.save(out, spec)
        take.discard()
        print(f"Saved {out}: {frames / take.rate:.1f} s, {spec.describe()}.")
        return 0
    finally:
        for t in takes:
            t.release()  # no-op for the one saved or deleted


def _gui(argv) -> int:
    from .ui.app import main as gui_main
    return gui_main(argv)


COMMANDS = {"rec": _rec, "recover": _recover, "gui": _gui}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    parser = argparse.ArgumentParser(
        prog="sound-recorder",
        description="Sound Recorder: every Windows capture API, every format.",
        epilog="Commands: `sound-recorder gui` opens the window, `sound-recorder rec OUT` "
               "records, `sound-recorder recover` saves takes a crash left behind (each has --help).")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--list", action="store_true", help="list capture devices (the default)")
    parser.add_argument("--probe", action="store_true",
                        help="ask each capture device which formats it really takes "
                             "(can trip the ZOOM H2n's sample-rate bug: see README)")
    parser.add_argument("--device", metavar="TEXT",
                        help="only devices whose name contains TEXT (any case)")
    parser.add_argument("--outputs", action="store_true", help="list playback devices too")
    parser.add_argument("--all", action="store_true", help="include endpoints Windows hides")
    parser.add_argument("--watch", action="store_true",
                        help="report devices being plugged in and unplugged until Ctrl+C")
    args = parser.parse_args(argv)

    if args.watch:
        return _watch()

    from .devices import scan
    _print_scan(scan(), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
