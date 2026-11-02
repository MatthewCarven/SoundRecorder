"""sound-recorder on the command line: list devices, probe them, watch them."""

from __future__ import annotations

import argparse
import sys
import time

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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sound-recorder",
        description="Sound Recorder: every Windows capture API, every format.")
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
