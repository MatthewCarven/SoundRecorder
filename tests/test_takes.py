import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from soundrec.output import spec_for
from soundrec.takes import Take, default_dir, orphans

SRC = str(Path(__file__).resolve().parents[1] / "src")


def noise(frames, channels=2, seed=0):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (frames, channels)).astype(np.float32)


def test_takes_folder_is_redirected_in_tests(takes_folder):
    assert default_dir() == takes_folder


def test_a_take_reads_back_what_was_written(takes_folder):
    take = Take.create(48000, 2, device="WASAPI: Mic")
    a, b = noise(1000), noise(500, seed=1)
    take.write(a)
    take.write(b)
    assert take.frames == 1500 and take.path.parent == takes_folder
    take.finish()
    assert np.array_equal(take.read(), np.vstack([a, b]))
    assert np.array_equal(take.read(900, 200), np.vstack([a, b])[900:1100])
    info = json.loads(take.info_path.read_text())
    assert info["frames"] == 1500 and info["device"] == "WASAPI: Mic" and info["finished"]
    take.discard()
    assert not take.path.exists() and not take.info_path.exists()


def test_a_held_take_is_no_orphan_and_a_released_one_is(takes_folder):
    take = Take.create(44100, 1)
    take.write(noise(100, 1))
    assert orphans() == []
    take.finish()
    take.release()
    found = orphans()
    assert [t.path for t in found] == [take.path]
    assert orphans() == []  # this process holds it now
    found[0].discard()
    assert list(takes_folder.iterdir()) == []


def test_half_a_frame_left_by_a_crash_is_dropped(takes_folder):
    take = Take.create(44100, 2)
    take.write(noise(10))
    take.release()
    with open(take.path, "ab") as f:
        f.write(b"\x00\x00\x80")  # three bytes of a frame that never finished
    (found,) = orphans()
    assert found.frames == 10
    assert np.array_equal(found.read(), noise(10))
    found.release()


def test_a_recovered_take_saves_to_a_file(takes_folder, tmp_path):
    take = Take.create(44100, 2)
    take.write(noise(70000))  # more than one of save's blocks
    take.release()
    (found,) = orphans()
    out = tmp_path / "recovered.flac"
    assert found.save(out, spec_for(out, "24")) == 70000
    back, rate = sf.read(out, dtype="float32")
    assert rate == 44100 and np.max(np.abs(back - noise(70000))) < 2 ** -23
    found.discard()


def test_stray_files_are_not_takes(takes_folder):
    takes_folder.mkdir()
    (takes_folder / "take-1.json").write_text("{}")  # no samples beside it
    (takes_folder / "take-2.f32").write_bytes(b"")
    (takes_folder / "take-2.json").write_text("not json")
    assert orphans() == []


def test_a_take_survives_its_recorder_being_killed(takes_folder):
    """A real crash: a recorder process killed mid-take leaves a take that
    another process finds and recovers, up to the last block it wrote."""
    script = textwrap.dedent(f"""
        import sys, threading
        sys.path.insert(0, {SRC!r})
        import numpy as np
        from soundrec.engine import ArraySource, Recorder
        data = np.random.default_rng(7).uniform(-0.5, 0.5, (48000 * 60, 2)).astype(np.float32)
        source = ArraySource(data, 48000, block=480, realtime=True)
        rec = Recorder(source, 44100, 1, meta={{"device": "test"}})
        rec.start()
        while rec.stats.frames_out < 44100:
            threading.Event().wait(0.01)
        print("recording", flush=True)
        threading.Event().wait(60)
    """)
    env = dict(os.environ, SOUNDREC_TAKES=str(takes_folder))
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, env=env,
                            text=True)
    try:
        assert proc.stdout.readline().strip() == "recording"
        assert orphans() == []  # alive: not an orphan
    finally:
        proc.kill()  # TerminateProcess: no finally blocks, no flushing
        proc.wait()
    # A venv's python.exe is a launcher, and the interpreter it started dies
    # (taking its lock with it) a moment after the launcher does.
    deadline = time.monotonic() + 10
    while not (found := orphans()) and time.monotonic() < deadline:
        time.sleep(0.05)
    (found,) = found
    assert found.info["device"] == "test" and found.info["finished"] is None
    assert found.rate == 44100 and found.channels == 1 and found.frames >= 44100
    assert np.all(np.isfinite(found.read()))
    found.discard()
