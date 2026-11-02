"""Is a capture device delivering at the rate it claims? Counts frames only.

Records a WASAPI capture device in shared mode and fits frames delivered
against the PC's clock, stretch by stretch. With --play, a stretch in the
middle also plays silence (zeros, nothing audible) to a playback device, to
see whether opening that endpoint at its own rate moves the capture clock:
the ZOOM H2n's deep-voices bug, where one clock serves both directions.

It also sums each channel's level and how alike the channels are over the
first stretch (a mode's fingerprint: mono, XY, mid-side, 4-channel).

No audio is kept: each block becomes a timestamp, a frame count and some
running sums.

    python scripts/h2n_clock.py [--seconds 15] [--play HZ] [--capture TEXT] [--playback TEXT]

The H2n's names: in its stereo modes, with ZOOM's driver, "ZOOM Recording
Mixer" and "Speakers (ZOOM"; in 4-channel mode, with Windows' own USB
driver, "Microphone (H2n)" and "Headphones (H2n)". By default whichever is
plugged in.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from soundrec.pa import sd  # noqa: E402  (first: see pa.py)

CAPTURES = ("ZOOM Recording Mixer (ZOOM H and F Series Audio)", "Microphone (H2n)")
PLAYBACKS = ("Speakers (ZOOM H and F Series Audio)", "Headphones (H2n)")


def wasapi_device(names, direction: str) -> tuple[int, str]:
    """The first WASAPI device of `direction` whose name contains one of names."""
    apis = sd.query_hostapis()
    devices = [(i, d) for i, d in enumerate(sd.query_devices())
               if apis[d["hostapi"]]["name"] == "Windows WASAPI" and d[f"max_{direction}_channels"] > 0]
    for name in names:
        for i, d in devices:
            if name.lower() in d["name"].lower():
                return i, d["name"]
    raise SystemExit(f"no WASAPI {direction} device like {' or '.join(map(repr, names))}")


def rate_between(arrivals: np.ndarray, start: float, end: float) -> tuple[float, int]:
    """Least-squares frames per second over arrivals with start <= t < end."""
    t, total = arrivals[:, 0], np.cumsum(arrivals[:, 1])
    keep = (t >= start) & (t < end)
    if keep.sum() < 3:
        return float("nan"), int(keep.sum())
    slope = np.polyfit(t[keep], total[keep], 1)[0]
    return float(slope), int(keep.sum())


def db(x: float) -> str:
    return f"{20 * np.log10(x):6.1f}" if x > 0 else "  -inf"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seconds", type=float, default=15, help="length of each stretch")
    parser.add_argument("--play", type=int, metavar="HZ",
                        help="play silence to the playback device at this rate in the middle stretch")
    parser.add_argument("--capture", metavar="TEXT", help="part of the capture device's name")
    parser.add_argument("--playback", metavar="TEXT", help="part of the playback device's name")
    args = parser.parse_args()

    capture, capture_name = wasapi_device([args.capture] if args.capture else CAPTURES, "input")
    info = sd.query_devices(capture)
    claimed, channels = int(info["default_samplerate"]), info["max_input_channels"]
    arrivals, lock = [], threading.Lock()
    sums = {"n": 0, "sum": np.zeros(channels), "cross": np.zeros((channels, channels)),
            "peak": np.zeros(channels)}
    first_stretch = [True]

    def callback(indata, frames, t, status):
        with lock:
            arrivals.append((time.perf_counter(), frames))
            if first_stretch[0]:
                block = indata.astype(np.float64)
                sums["n"] += frames
                sums["sum"] += block.sum(axis=0)
                sums["cross"] += block.T @ block
                np.maximum(sums["peak"], np.abs(block).max(axis=0), out=sums["peak"])

    stream = sd.InputStream(device=capture, channels=channels, samplerate=claimed,
                            dtype="float32", latency="high", callback=callback)
    stream.start()
    marks = [("capture alone", time.perf_counter())]
    time.sleep(args.seconds)
    first_stretch[0] = False
    if args.play:
        playback, playback_name = wasapi_device([args.playback] if args.playback else PLAYBACKS,
                                                "output")
        out = sd.OutputStream(device=playback, channels=2, samplerate=args.play, dtype="float32",
                              latency="high",
                              callback=lambda outdata, frames, t, status: outdata.fill(0))
        marks.append((f"playing silence at {args.play:,} Hz", time.perf_counter()))
        out.start()
        time.sleep(args.seconds)
        out.stop()
        out.close()
        marks.append(("capture alone again", time.perf_counter()))
        time.sleep(args.seconds)
    end = time.perf_counter()
    stream.stop()
    stream.close()

    data = np.array(arrivals, dtype=np.float64)
    print(f"{capture_name}, WASAPI shared, {channels} ch, claims {claimed:,} Hz")
    if args.play:
        print(f"  silence played to {playback_name}")
    bounds = [m[1] for m in marks] + [end]
    for (label, start), stop in zip(marks, bounds[1:]):
        rate, blocks = rate_between(data, start + 1.0, stop)  # skip a second after each change
        ppm = (rate / claimed - 1) * 1e6
        print(f"  {label:32} {rate:10,.1f} frames/s  ({ppm:+9.0f} ppm, {blocks} blocks)")

    n = sums["n"]
    mean = sums["sum"] / n
    covariance = sums["cross"] / n - np.outer(mean, mean)
    rms = np.sqrt(np.maximum(np.diag(covariance), 0))
    print(f"  first stretch, per channel: RMS dBFS {' '.join(db(r) for r in rms)}; "
          f"peak dBFS {' '.join(db(p) for p in sums['peak'])}")
    with np.errstate(invalid="ignore", divide="ignore"):
        correlation = covariance / np.outer(rms, rms)
    print("  how alike the channels are (correlation, 1 = identical, 0 = unrelated):")
    for i in range(channels):
        print("    " + " ".join(f"{correlation[i, j]:+.3f}" for j in range(channels)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
