import threading
import time

import numpy as np
import pytest
import soundfile as sf
import soxr

from signals import fit
from soundrec.engine import DISCONTINUITY, OVERFLOW, ArraySource, Recorder, Stats, decibels
from soundrec.output import spec_for


def noise(frames, channels=2, seed=0, level=0.5):
    return np.random.default_rng(seed).uniform(-level, level, (frames, channels)).astype(np.float32)


def record(source, *args, **kw):
    rec = Recorder(source, *args, **kw)
    rec.start()
    source.finished.wait(30)
    return rec, rec.stop()


def test_the_working_copy_is_the_whole_take_converted(takes_folder):
    x = noise(48000 * 3)
    rec, take = record(ArraySource(x, 48000, block=[480, 64, 4799, 1, 2000]), 44100, 1)
    expected = soxr.resample(x.mean(axis=1, dtype=np.float32), 48000, 44100, quality="VHQ")
    assert take.frames == 3 * 44100 == rec.stats.frames_out
    assert np.array_equal(take.read()[:, 0], expected)
    assert rec.stats.frames_in == len(x) and rec.error is None
    assert take.path.parent == takes_folder
    take.discard()


class SineSource:
    """A sine generated block by block, as a device would hand it over, held
    back while the recorder has more than a few blocks waiting."""

    def __init__(self, freq, rate, seconds, sizes, backlog):
        self.freq, self.rate, self.channels = freq, rate, 1
        self.total, self.sizes, self.backlog = int(rate * seconds), sizes, backlog
        self.finished = threading.Event()
        self._thread = None

    def start(self, deliver):
        def run():
            at, n = 0, 0
            while at < self.total:
                while self.backlog() > 32:
                    time.sleep(0.001)
                size = min(self.sizes[n % len(self.sizes)], self.total - at)
                t = 2 * np.pi * self.freq * (at + np.arange(size)) / self.rate
                deliver((0.5 * np.sin(t)).astype(np.float32)[:, None])
                at, n = at + size, n + 1
            self.finished.set()
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._thread.join()


def test_a_ten_minute_take_48k_to_44k1_loses_nothing(takes_folder):
    """Every sample through: the count comes out exact, and the sine's phase
    is where it should be all through the take. One input sample lost or
    doubled anywhere would move every later window by 0.13 rad."""
    freq = 997.0
    holder = {}
    source = SineSource(freq, 48000, 600, [4800, 64, 4799, 1000, 333],
                        backlog=lambda: holder["rec"]._queue.qsize())
    rec = holder["rec"] = Recorder(source, 44100, 1)
    rec.start()
    source.finished.wait(120)
    take = rec.stop()
    try:
        assert rec.error is None
        assert rec.stats.frames_in == 600 * 48000
        assert take.frames == 600 * 44100
        for start in np.linspace(44100, take.frames - 44100, 25).astype(int):
            amplitude, phase, worst = fit(take.read(start, 8192)[:, 0], freq, 44100, start)
            assert amplitude == pytest.approx(0.5, rel=1e-4)
            assert abs(phase) < 1e-3, f"phase off at {start / 44100:.1f} s"
            assert worst < 1e-4
    finally:
        take.discard()


def test_direct_to_file_matches_the_working_copy(tmp_path):
    x = noise(44100 * 2, level=0.3)
    out = tmp_path / "live.flac"
    rec, take = record(ArraySource(x, 48000, block=480), 44100, 2,
                       direct=(out, spec_for(out)), seed=1)
    assert rec.direct_error is None and take.info["direct"] == str(out)
    y, rate = sf.read(out, dtype="float32")
    working = take.read()
    assert rate == 44100 and y.shape == working.shape
    assert np.max(np.abs(y - working)) <= 1.5 / 32768  # dithered to 16 bits, nothing more
    take.discard()


def test_a_failing_file_leaves_the_working_copy_going(tmp_path):
    out = tmp_path / "live.wav"
    source = ArraySource(noise(48000), 48000, block=480)
    rec = Recorder(source, direct=(out, spec_for(out)))
    rec.start()
    calls = []

    def broken(block):
        calls.append(len(block))
        raise OSError("disk full")
    rec._writer.write = broken
    source.finished.wait(10)
    take = rec.stop()
    assert isinstance(rec.direct_error, OSError) and len(calls) == 1
    assert rec.error is None and take.frames == 48000
    take.discard()


def test_flags_are_counted():
    source = ArraySource(noise(4800), 48000, block=480, flags={3: OVERFLOW, 5: DISCONTINUITY,
                                                              6: OVERFLOW | DISCONTINUITY})
    rec, take = record(source)
    assert rec.stats.overflows == 2 and rec.stats.discontinuities == 2
    assert rec.stats.blocks == 10
    take.discard()


def test_peaks_and_clipping():
    x = np.zeros((4800, 2), np.float32)
    x[100, 0], x[200, 1], x[300, 1] = 0.25, -1.0, 1.5
    rec, take = record(ArraySource(x, 48000, block=480))
    assert np.array_equal(rec.take_peaks(), np.array([0.25, 1.5], np.float32))
    assert np.array_equal(rec.take_peaks(), [0, 0])  # reset by reading
    assert rec.stats.clipped == 2
    assert decibels(0.5) == pytest.approx(-6.02, abs=0.01) and decibels(0) == -np.inf
    take.discard()


def test_the_clock_check_sees_a_device_at_the_wrong_rate():
    # The H2n's bug, as numbers: claims 44.1 kHz, delivers 48 kHz, in 64-frame blocks.
    s = Stats(44100)
    for i in range(1, 48000 * 10 // 64):
        s._arrived(100.0 + i * 64 / 48000, 64)
    assert s.measured_rate() == pytest.approx(48000, rel=1e-9)
    assert s.clock_ppm() == pytest.approx((48000 / 44100 - 1) * 1e6, rel=1e-6)
    assert s.clock_uncertainty_ppm() < 1


def test_the_clock_check_sees_through_lumpy_delivery():
    # DirectSound's way: 64 ms lumps, each up to 30 ms late, at a true 44,100 Hz.
    rng = np.random.default_rng(0)
    s = Stats(44100)
    lump = int(44100 * 0.064)
    for i in range(1, 600 * 1000 // 64):
        s._arrived(i * lump / 44100 + rng.uniform(0, 0.030), lump)
    assert abs(s.clock_ppm()) < 20 and s.clock_uncertainty_ppm() < 20
    short = Stats(44100)
    for i in range(1, 50):  # three seconds of the same
        short._arrived(i * lump / 44100 + rng.uniform(0, 0.030), lump)
    assert short.clock_uncertainty_ppm() > abs(short.clock_ppm()) / 3  # too short to judge


def test_a_wrong_clock_is_called_a_problem_and_a_right_one_is_not():
    def fed(claimed, real, seconds, block=480, jitter=0.0, seed=0):
        rng = np.random.default_rng(seed)
        s = Stats(claimed)
        for i in range(1, int(real * seconds / block)):
            s._arrived(i * block / real + rng.uniform(0, jitter), block)
        return s

    # PortAudio's exclusive mode here: 480-frame blocks at 67,000 frames/s for 48,000.
    message = fed(48000, 67000, 3).clock_problem()
    assert "67,000 frames a second for the 48,000 it claims (+39.6%)" in message
    assert fed(44100, 48000, 3).clock_problem()            # the H2n's bug, as it would look
    assert fed(48000, 48003, 60).clock_problem() is None   # an ordinary crystal, 60 ppm out
    assert fed(48000, 67000, 1).clock_problem() is None    # too soon to say
    lumpy = fed(44100, 44100, 3, block=2822, jitter=0.03)  # DirectSound's lumps, 3 s
    assert lumpy.clock_problem() is None


def test_a_limit_keeps_exactly_that_many_frames(tmp_path):
    out = tmp_path / "three.wav"
    source = ArraySource(noise(48000 * 5), 48000, block=4800)
    rec = Recorder(source, 44100, direct=(out, spec_for(out)), limit=3 * 44100)
    rec.start()
    assert rec.full.wait(10)
    take = rec.stop()
    assert take.frames == 3 * 44100 == sf.info(str(out)).frames
    take.discard()


def test_the_clock_check_reads_a_real_time_source(takes_folder):
    source = ArraySource(noise(48000), 48000, block=480, realtime=True)
    rec, take = record(source)
    # Loose: a busy laptop shifts the timing; this only proves it's measured.
    assert rec.stats.measured_rate() == pytest.approx(48000, rel=0.1)
    assert rec.stats.max_gap < 0.5
    take.discard()


def test_a_source_that_wont_open_leaves_nothing_behind(takes_folder, tmp_path):
    class Busy(ArraySource):
        def start(self, deliver):
            raise OSError("device in use")

    out = tmp_path / "x.wav"
    rec = Recorder(Busy(noise(10), 48000), direct=(out, spec_for(out)))
    with pytest.raises(OSError, match="device in use"):
        rec.start()
    assert not out.exists()
    assert not takes_folder.exists() or list(takes_folder.iterdir()) == []


def test_impossible_channels_are_refused_before_anything_opens(takes_folder):
    with pytest.raises(ValueError, match="4 channels can't make 2"):
        Recorder(ArraySource(noise(10, 4), 48000), 48000, 2)
    assert not takes_folder.exists()
