"""The window's sound (Document), its playback, its device list and its
message boxes, all without Tk or PortAudio."""

import sys
import threading
import types

import numpy as np
import pytest
import soundfile as sf

from soundrec.output import OutputSpec
from soundrec.takes import Take
from soundrec.ui.audio import DeviceList, PlaybackError, Player
from soundrec.ui.document import Document


def noise(frames, channels=2, seed=0):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (frames, channels)).astype(np.float32)


def take_of(data, rate=48000):
    take = Take.create(rate, data.shape[1])
    take.write(data)
    take.finish()
    return take


# -- Document -------------------------------------------------------------------------

def test_the_first_recording_becomes_the_sound():
    doc = Document()
    assert (doc.frames, doc.name, doc.rate) == (0, "(Untitled)", None)
    a = noise(1000)
    doc.splice(0, take_of(a))
    assert np.array_equal(doc.read(0, 2000), a) and doc.dirty and doc.rate == 48000
    doc.close()


def test_recording_from_the_middle_records_over_and_past_the_end():
    doc = Document()
    a, b, c = noise(1000), noise(300, seed=1), noise(900, seed=2)
    doc.splice(0, take_of(a))
    first = doc.take
    doc.splice(400, take_of(b))
    assert np.array_equal(doc.read(0, 5000), np.vstack([a[:400], b, a[700:]]))
    doc.splice(800, take_of(c))
    assert np.array_equal(doc.read(0, 5000), np.vstack([a[:400], b, a[700:800], c]))
    assert doc.take is first and doc.frames == 1700
    doc.splice(0, take_of(noise(2000, seed=3)))  # covers it all: replaces it
    assert doc.frames == 2000 and not first.path.exists()
    doc.close()


def test_an_empty_recording_changes_nothing():
    doc = Document()
    empty = take_of(np.zeros((0, 2), np.float32))
    doc.splice(0, empty)
    assert doc.take is None and not doc.dirty and not empty.path.exists()


def test_open_and_save_keep_16_bits_exact(tmp_path):
    pcm = (np.random.default_rng(0).integers(-32768, 32767, (4410, 2)) / 32768).astype(np.float32)
    path = tmp_path / "in.wav"
    sf.write(str(path), pcm, 44100, subtype="PCM_16")
    doc = Document.open(path)
    assert (doc.rate, doc.channels, doc.frames, doc.name) == (44100, 2, 4410, "in.wav")
    assert doc.spec == OutputSpec("WAV", "PCM_16") and not doc.dirty
    out = tmp_path / "out.wav"
    doc.save(out, doc.spec)
    data, rate = sf.read(str(out), dtype="float32")
    assert rate == 44100 and np.array_equal(data, pcm)
    assert doc.path == out and not list(tmp_path.glob("*.saving"))
    doc.close()


def test_saving_over_the_file_it_came_from(tmp_path):
    path = tmp_path / "s.flac"
    sf.write(str(path), noise(1000), 48000)
    doc = Document.open(path)
    assert doc.spec.format == "FLAC"
    doc.save(path, doc.spec)  # fine: the sound was read into the working copy
    assert sf.info(str(path)).frames == 1000
    doc.close()


def test_a_failed_save_leaves_the_old_file(tmp_path):
    doc = Document()
    doc.splice(0, take_of(noise(1000, channels=3)))
    target = tmp_path / "keep.mp3"
    target.write_bytes(b"precious")
    with pytest.raises(Exception):
        doc.save(target, OutputSpec("MP3", "MPEG_LAYER_III"))  # MP3 can't hold 3 channels
    assert target.read_bytes() == b"precious" and not list(tmp_path.glob("*.saving"))
    assert doc.path is None
    doc.close()


# -- playback -------------------------------------------------------------------------

class FakeStream:
    """Stands in for sounddevice's OutputStream: runs the callback in blocks."""

    def __init__(self, device, samplerate, channels, dtype, extra_settings, callback,
                 finished_callback):
        self.channels, self.callback, self.finished = channels, callback, finished_callback
        self.latency = 0.05
        self.heard = []
        self._thread = None
        FakeStream.last = self

    late_blocks = ()  # blocks PortAudio reports an underflow before

    def start(self):
        def run():
            block = 0
            while True:
                out = np.full((256, self.channels), 9.0, np.float32)
                status = types.SimpleNamespace(output_underflow=block in self.late_blocks)
                block += 1
                try:
                    self.callback(out, 256, None, status)
                except FakeSd.CallbackStop:
                    self.heard.append(out)
                    break
                self.heard.append(out)
            self.finished()
        self._thread = threading.Thread(target=run)
        self._thread.start()

    def stop(self):
        self._thread.join()

    def close(self):
        pass


class FakeSd:
    class CallbackStop(Exception):
        pass

    OutputStream = FakeStream

    @staticmethod
    def WasapiSettings(**kw):
        return kw


@pytest.fixture
def fake_portaudio(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundrec.pa", types.SimpleNamespace(sd=FakeSd))


def test_playback_plays_from_the_position_to_the_end(fake_portaudio):
    a = noise(1000)
    take = take_of(a)
    device = types.SimpleNamespace(index=3, channels=2, name="Speakers")
    player = Player(take, device, start=300)
    player.start()
    assert player.finished.wait(5)
    player.stop()
    heard = np.vstack(FakeStream.last.heard)
    assert np.array_equal(heard[:700], a[300:]) and not heard[700:].any()  # silence after the end
    assert player.position == 1000 and player.sent == 1000
    take.discard()  # the memory map was let go: Windows can delete it


def test_playback_counts_the_underflows_portaudio_reports(fake_portaudio, monkeypatch):
    monkeypatch.setattr(FakeStream, "late_blocks", (1, 2))
    take = take_of(noise(2000))
    player = Player(take, types.SimpleNamespace(index=0, channels=2, name="Speakers"))
    player.start()
    player.finished.wait(5)
    player.stop()
    assert player.underflows == 2
    take.discard()


def test_playback_takes_as_many_channels_as_the_device_has(fake_portaudio):
    a = noise(500, channels=4)
    take = take_of(a)
    player = Player(take, types.SimpleNamespace(index=0, channels=2, name="Headphones"))
    player.start()
    player.finished.wait(5)
    player.stop()
    assert np.array_equal(np.vstack(FakeStream.last.heard)[:500], a[:, :2])
    take.discard()


def test_playback_says_why_it_cant_start():
    take = take_of(noise(100))  # PortAudio is blocked in the tests: opening fails
    with pytest.raises(PlaybackError):
        Player(take, types.SimpleNamespace(index=0, channels=2, name="Speakers")).start()
    take.discard()


# -- the device list --------------------------------------------------------------------

def test_scans_run_off_the_ui_thread_and_report_back(monkeypatch):
    import soundrec.devices

    seen = []
    monkeypatch.setattr(soundrec.devices, "scan",
                        lambda rescan=False: (seen.append((rescan, threading.current_thread().name))
                                              or types.SimpleNamespace(inputs=[], outputs=[])))
    inbox = []
    done = threading.Event()
    devices = DeviceList(lambda job: (inbox.append(job), done.set()))
    assert devices.refresh(then=lambda: inbox.append("then"))
    assert not devices.refresh()  # one at a time
    assert done.wait(5)
    inbox.pop(0)()  # the UI thread runs the result
    assert inbox == ["then"] and devices.scan.inputs == [] and not devices.busy
    assert seen == [(False, "Device scans")]
    devices.stop()


def test_a_failed_scan_is_kept_as_the_error(monkeypatch):
    import soundrec.devices

    def broken(rescan=False):
        raise OSError("no audio service")

    monkeypatch.setattr(soundrec.devices, "scan", broken)
    done = threading.Event()
    jobs = []
    devices = DeviceList(lambda job: (jobs.append(job), done.set()))
    devices.refresh()
    done.wait(5)
    jobs[0]()
    assert isinstance(devices.error, OSError) and devices.scan is None
    devices.stop()


# -- message boxes ------------------------------------------------------------------------

def test_a_message_box_lays_out_and_answers_keys():
    from soundrec.ui.dialog import MessageBox, wrap
    from soundrec.ui.fonts import system_font

    box = MessageBox(None, 1, "Sound Recorder", "Do you want to save the changes to (Untitled)?",
                     [("&Yes", "yes"), ("&No", "no"), ("Cancel", "cancel")], kind="question")
    s = box.paint()
    assert (s.width, s.height) == (box.width, box.height)
    assert box.button_at(box.boxes[1][0] + 3, box.boxes[1][1] + 3) == 1
    assert box.key("n", "n") and box.answer == "no"
    assert box.key("Escape", "") and box.answer == "cancel"
    box.key("Tab", "")
    assert box.key("Return", "") and box.answer == "no"
    assert all(system_font().measure(line) <= 320 for line in wrap("word " * 100, system_font()))
