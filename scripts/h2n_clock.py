"""Is a capture device delivering at the rate it claims? Counts frames only.

Records a WASAPI capture device in shared mode and fits frames delivered
against the PC's clock, window by window. With --play, a stretch in the
middle also plays silence (zeros, nothing audible) to a playback device, to
see whether opening that endpoint at its own rate moves the capture clock:
the lead on the ZOOM H2n's deep-voices bug, whose playback endpoint runs at
48 kHz while its capture endpoint runs at 44.1 kHz.

No audio is kept: each block becomes a timestamp and a frame count.

    python scripts/h2n_clock.py [--seconds 15] [--play 48000]
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

CAPTURE = "ZOOM Recording Mixer (ZOOM H and F Series Audio)"
PLAYBACK = "Speakers (ZOOM H and F Series Audio)"


def wasapi_index(name: str, direction: str) -> int:
    apis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        if (d["name"] == name and apis[d["hostapi"]]["name"] == "Windows WASAPI"
                and d[f"max_{direction}_channels"] > 0):
            return i
    raise SystemExit(f"no WASAPI {direction} device called {name!r}")


def rate_between(arrivals: np.ndarray, start: float, end: float) -> tuple[float, int]:
    """Least-squares frames per second over arrivals with start <= t < end."""
    t, total = arrivals[:, 0], np.cumsum(arrivals[:, 1])
    keep = (t >= start) & (t < end)
    if keep.sum() < 3:
        return float("nan"), int(keep.sum())
    slope = np.polyfit(t[keep], total[keep], 1)[0]
    return float(slope), int(keep.sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seconds", type=float, default=15, help="length of each stretch")
    parser.add_argument("--play", type=int, metavar="HZ",
                        help="play silence to the playback device at this rate in the middle stretch")
    args = parser.parse_args()

    capture = wasapi_index(CAPTURE, "input")
    claimed = int(sd.query_devices(capture)["default_samplerate"])
    arrivals, lock = [], threading.Lock()

    def callback(indata, frames, t, status):
        with lock:
            arrivals.append((time.perf_counter(), frames))

    stream = sd.InputStream(device=capture, channels=2, samplerate=claimed, dtype="float32",
                            latency="high", callback=callback)
    stream.start()
    t0 = time.perf_counter()
    marks = [("capture alone", t0)]
    time.sleep(args.seconds)
    if args.play:
        out = sd.OutputStream(device=wasapi_index(PLAYBACK, "output"), channels=2,
                              samplerate=args.play, dtype="float32", latency="high",
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
    print(f"{CAPTURE}, WASAPI shared, claims {claimed:,} Hz")
    bounds = [m[1] for m in marks] + [end]
    for (label, start), stop in zip(marks, bounds[1:]):
        rate, blocks = rate_between(data, start + 1.0, stop)  # skip a second after each change
        ppm = (rate / claimed - 1) * 1e6
        print(f"  {label:32} {rate:10,.1f} frames/s  ({ppm:+9.0f} ppm, {blocks} blocks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
