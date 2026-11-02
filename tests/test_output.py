import numpy as np
import pytest
import soundfile as sf

from signals import fit, peak_frequency, rms_db, sine
from soundrec.output import OutputSpec, Quantiser, Writer, preflight, spec_for


# -- what a file name asks for -------------------------------------------------

@pytest.mark.parametrize("name, bits, fmt, subtype", [
    ("a.wav", None, "WAV", "PCM_16"),
    ("a.WAV", "24", "WAV", "PCM_24"),
    ("a.wav", "8", "WAV", "PCM_U8"),      # WAV's 8-bit is unsigned
    ("a.wav", "float", "WAV", "FLOAT"),
    ("a.flac", None, "FLAC", "PCM_16"),
    ("a.flac", "8", "FLAC", "PCM_S8"),
    ("a.flac", "24", "FLAC", "PCM_24"),
    ("a.mp3", None, "MP3", "MPEG_LAYER_III"),
    ("a.ogg", None, "OGG", "VORBIS"),
    ("a.opus", None, "OGG", "OPUS"),
    ("a.aif", "16", "AIFF", "PCM_16"),
    ("a.aiff", "8", "AIFF", "PCM_S8"),
    ("a.caf", "32", "CAF", "PCM_32"),
    ("a.w64", None, "W64", "PCM_16"),
    ("a.rf64", None, "RF64", "PCM_16"),
])
def test_spec_for(name, bits, fmt, subtype):
    assert spec_for(name, bits) == OutputSpec(fmt, subtype)


@pytest.mark.parametrize("name, bits, message", [
    ("a.mp3", "16", "no bit depth"),
    ("a.flac", "float", "FLAC can't hold float"),
    ("a.flac", "32", "FLAC can't hold 32-bit"),
    ("a.xyz", None, "don't know how to write .xyz"),
    ("noext", None, "no extension"),
    ("a.wav", "12", "bits must be one of"),
])
def test_spec_for_refuses(name, bits, message):
    with pytest.raises(ValueError, match=message):
        spec_for(name, bits)


# -- quantising and dither -----------------------------------------------------

def test_16_bit_audio_comes_back_bit_for_bit():
    ints = np.random.default_rng(0).integers(-32768, 32768, (10000, 2)).astype(np.int16)
    block = ints.astype(np.float32) / 32768  # as PortAudio hands 16-bit capture over
    assert np.array_equal(Quantiser("PCM_16", seed=1)(block), ints)


def test_dither_error_is_tpdf_sized_and_unbiased():
    q = Quantiser("PCM_16", seed=3)
    lsb = 1 / 32768
    block = np.full((200000, 1), 0.3 * lsb, np.float32)  # under half a step: rounding alone gives 0
    out = q(block).astype(np.float64)
    assert np.mean(out) == pytest.approx(0.3, abs=0.01)  # dither keeps what rounding would lose
    error = out - 0.3
    assert np.max(np.abs(error)) <= 1.5
    # TPDF (variance 1/6) plus rounding (1/12): RMS 0.5 of a step.
    assert np.sqrt(np.mean(error ** 2)) == pytest.approx(0.5, abs=0.02)


def test_dither_noise_is_independent_of_the_signal():
    # A sine of 0.7 steps would round to a square-ish wave; with dither the
    # error has no component at the sine's frequency.
    rate, freq = 44100, 1000
    x = sine(freq, rate, 2.0, amplitude=0.7 / 32768)
    error = Quantiser("PCM_16", seed=5)(x)[:, 0] / 32768 - x[:, 0]
    amplitude, _, _ = fit(error, freq, rate)
    assert amplitude < 0.02 / 32768


def test_clipping_holds_at_full_scale_instead_of_wrapping():
    block = np.array([[1.0], [1.2], [-1.0], [-1.5], [0.99999]], np.float32)
    out = Quantiser("PCM_16", seed=0)(block)[:, 0]
    assert out[0] == 32767 and out[1] == 32767 and out[2] == -32768 and out[3] == -32768
    assert out[4] >= 32766


def test_8_bit_lands_on_the_8_bit_grid():
    block = sine(440, 8000, 0.5)
    out = Quantiser("PCM_U8", seed=0)(block)
    assert out.dtype == np.int16 and np.all(out % 256 == 0)
    assert np.max(np.abs(out / 32768 - block)) <= 1.5 / 128


def test_24_bit_is_rounded_without_dither():
    ints = np.array([[-2 ** 23], [-1], [0], [1], [2 ** 23 - 1]], np.int64)
    block = (ints / 2 ** 23).astype(np.float32)
    out = Quantiser("PCM_24")(block)
    assert out.dtype == np.int32 and np.array_equal(out, ints * 256)


def test_float_keeps_overs_and_lossy_codecs_get_them_clipped():
    block = np.array([[1.5], [-0.25]], np.float32)
    assert Quantiser("FLOAT")(block) is block
    assert np.array_equal(Quantiser("VORBIS")(block), np.array([[1.0], [-0.25]], np.float32))


# -- real files ----------------------------------------------------------------

def test_wav_16_round_trip_is_exact(tmp_path):
    ints = np.random.default_rng(4).integers(-32768, 32768, (4410, 2)).astype(np.int16)
    path = tmp_path / "x.wav"
    with Writer(path, spec_for(path), 44100, 2) as w:
        w.write(ints.astype(np.float32) / 32768)
    assert np.array_equal(sf.read(path, dtype="int16")[0], ints)


def test_flac_24_round_trip_is_exact(tmp_path):
    ints = np.random.default_rng(5).integers(-2 ** 23, 2 ** 23, (4800, 1))
    path = tmp_path / "x.flac"
    with Writer(path, spec_for(path, "24"), 48000, 1) as w:
        w.write((ints / 2 ** 23).astype(np.float32))
    back = sf.read(path, dtype="int32", always_2d=True)[0] // 256
    assert np.array_equal(back, ints)


@pytest.mark.parametrize("name, rate, channels", [
    ("x.mp3", 44100, 2), ("x.mp3", 48000, 1), ("x.ogg", 44100, 2), ("x.opus", 48000, 2),
])
def test_lossy_files_write_and_read_back(tmp_path, name, rate, channels):
    x = sine(997, rate, 3.0, amplitude=0.5, channels=channels)
    path = tmp_path / name
    with Writer(path, spec_for(path), rate, channels) as w:
        for i in range(0, len(x), 4096):
            w.write(x[i:i + 4096])
    y, back_rate = sf.read(path, dtype="float32", always_2d=True)
    assert back_rate == rate and y.shape[1] == channels
    assert abs(len(y) - len(x)) <= 2304  # an MP3 frame or two of padding at most
    middle = y[rate // 2:rate // 2 + 65536, 0]
    assert peak_frequency(middle, rate) == pytest.approx(997, abs=0.1)
    assert rms_db(middle) == pytest.approx(rms_db(x[:65536, 0]), abs=0.5)


def test_preflight_catches_what_a_codec_cant_take():
    preflight(spec_for("a.wav"), 44100, 2)
    preflight(spec_for("a.mp3"), 44100, 2)
    with pytest.raises(ValueError, match="can't write MP3"):
        preflight(spec_for("a.mp3"), 96000, 2)
    with pytest.raises(ValueError, match="can't write OGG Opus"):
        preflight(spec_for("a.opus"), 44100, 2)
