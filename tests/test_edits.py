import numpy as np
import pytest
import soundfile as sf

from soundrec import edits
from soundrec.convert import fit_channels
from soundrec.takes import Take


@pytest.fixture(autouse=True)
def small_blocks(monkeypatch):
    """Blocks of 1000 frames, so every edit crosses block edges."""
    monkeypatch.setattr(edits, "BLOCK", 1000)


def noise(frames, channels=2, seed=0):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (frames, channels)).astype(np.float32)


def take_of(data, rate=8000):
    take = Take.create(rate, data.shape[1])
    take.write(data)
    take.finish()
    return take


def everything(take):
    data = take.read()
    take.discard()
    return data


def test_delete_before_and_after():
    a = noise(3500)
    take = take_of(a)
    assert np.array_equal(everything(edits.delete_before(take, 1234)), a[1234:])
    assert np.array_equal(everything(edits.delete_after(take, 1234)), a[:1234])
    assert len(everything(edits.delete_after(take, 0))) == 0
    assert np.array_equal(everything(edits.delete_before(take, 0)), a)
    take.discard()


def test_insert_moves_the_rest_along():
    a, b = noise(3500), noise(2200, seed=1)
    take = take_of(a)
    out = everything(edits.insert(take, 1500, iter([b[:700], b[700:]])))
    assert np.array_equal(out, np.vstack((a[:1500], b, a[1500:])))
    out = everything(edits.insert(take, take.frames, iter([b])))  # at the end
    assert np.array_equal(out, np.vstack((a, b)))
    take.discard()


def test_mix_adds_and_runs_past_the_end():
    a, b = noise(3500), noise(2500, seed=1)
    take = take_of(a)
    out = everything(edits.mix(take, 500, iter([b])))
    want = a.copy()
    want[500:3000] += b
    assert np.allclose(out, want) and len(out) == 3500
    out = everything(edits.mix(take, 2000, iter([b[:1000], np.zeros((0, 2), np.float32), b[1000:]])))
    assert len(out) == 4500  # 2000 + 2500
    assert np.allclose(out[:2000], a[:2000])
    assert np.allclose(out[2000:3500], a[2000:] + b[:1500])
    assert np.allclose(out[3500:], b[1500:])
    take.discard()


def test_volume_up_then_down_gives_the_sound_back():
    a = noise(3500)
    take = take_of(a)
    louder = edits.volume(take, edits.VOLUME_STEP)
    assert np.allclose(louder.read(), a * 1.25)
    back = everything(edits.volume(louder, 1 / edits.VOLUME_STEP))
    assert np.allclose(back, a, atol=1e-6)
    louder.discard()
    take.discard()


def test_volume_keeps_overs_in_the_working_copy():
    a = np.full((10, 1), 0.9, np.float32)
    take = take_of(a)
    out = everything(edits.volume(take, 1.25))
    assert np.allclose(out, 1.125)  # clipped only when saved to a format without room
    take.discard()


def test_reverse():
    a = noise(3500)
    take = take_of(a)
    assert np.array_equal(everything(edits.reverse(take)), a[::-1])
    take.discard()


def test_echo_is_one_repeat_at_the_delay():
    rate = 8000
    a = np.zeros((4000, 2), np.float32)
    a[100] = [1.0, -1.0]
    take = take_of(a, rate)
    out = everything(edits.echo(take, seconds=0.25, level=0.5))
    delay = 2000
    assert len(out) == 4000
    assert np.allclose(out[100], [1.0, -1.0])
    assert np.allclose(out[100 + delay], [0.5, -0.5])
    out[100] = out[100 + delay] = 0
    assert not out.any()
    take.discard()


def test_echo_across_block_edges_matches_doing_it_all_at_once():
    a = noise(3500)
    take = take_of(a)
    out = everything(edits.echo(take, seconds=0.1, level=0.5))  # 800 frames
    want = a.copy()
    want[800:] += 0.5 * a[:-800]
    assert np.allclose(out, want, atol=1e-6)
    take.discard()


def tone(frames, rate, hz):
    t = np.arange(frames) / rate
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)[:, None]


def peak_hz(data, rate):
    spectrum = np.abs(np.fft.rfft(data[:, 0] * np.hanning(len(data))))
    return np.fft.rfftfreq(len(data), 1 / rate)[spectrum.argmax()]


def test_faster_halves_the_length_and_doubles_the_pitch():
    rate = 8000
    take = take_of(tone(8000, rate, 500), rate)
    out = everything(edits.speed(take, edits.SPEED_STEP))
    assert abs(len(out) - 4000) <= 1
    assert abs(peak_hz(out[200:-200], rate) - 1000) < 5
    take.discard()


def test_slower_doubles_the_length_and_halves_the_pitch():
    rate = 8000
    take = take_of(tone(8000, rate, 1000), rate)
    out = everything(edits.speed(take, 1 / edits.SPEED_STEP))
    assert abs(len(out) - 16000) <= 1
    assert abs(peak_hz(out[200:-200], rate) - 500) < 5
    take.discard()


def test_a_failed_edit_leaves_no_take_behind(takes_folder):
    take = take_of(noise(3500))

    def broken():
        yield noise(100)
        raise OSError("disk full")

    with pytest.raises(OSError):
        edits.insert(take, 100, broken())
    assert sorted(p.name for p in takes_folder.iterdir()) == sorted([take.path.name,
                                                                     take.info_path.name])
    take.discard()


def test_a_file_comes_in_at_the_sounds_rate_and_channels(tmp_path):
    path = tmp_path / "in.wav"
    sf.write(path, tone(4410, 44100, 441), 44100, "FLOAT")  # 0.1 s of mono at 44.1 kHz
    blocks = list(edits.file_blocks(path, 8000, 2))
    data = np.vstack(blocks)
    assert data.shape[1] == 2 and abs(len(data) - 800) <= 1
    assert np.array_equal(data[:, 0], data[:, 1])  # mono to both sides
    assert abs(peak_hz(data, 8000) - 441) < 20


def test_fitting_channels():
    block = np.array([[0.1, 0.2, 0.3, 0.4]], np.float32)
    assert np.allclose(fit_channels(block, 2), [[0.2, 0.3]])  # 1 and 3 left, 2 and 4 right
    assert np.allclose(fit_channels(block, 1), [[0.25]])
    assert np.allclose(fit_channels(block[:, :2], 4), [[0.1, 0.2, 0.1, 0.2]])
    assert np.allclose(fit_channels(block[:, :1], 2), [[0.1, 0.1]])
    assert fit_channels(block, 4) is block
    assert fit_channels(block, 2).dtype == np.float32
