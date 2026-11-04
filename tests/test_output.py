import numpy as np
import pytest
import soundfile as sf

from signals import fit, peak_frequency, rms_db, sine
from soundrec.output import (OutputSpec, Quantiser, Writer, channels_for, default_quality, extension,
                             format_names, mp3_level, preflight, qualities, rate_for, spec_for,
                             subtype_names)


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


def test_replacing_puts_files_in_place_only_at_the_end(tmp_path):
    from soundrec.output import replacing

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("old")
    with replacing([a, b]) as [ta, tb]:
        ta.write_text("new a")
        tb.write_text("new b")
        assert a.read_text() == "old" and not b.exists()
    assert a.read_text() == "new a" and b.read_text() == "new b"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "b.txt"]


def test_replacing_leaves_things_as_they_were_on_a_failure(tmp_path):
    from soundrec.output import replacing

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("old")
    with pytest.raises(OSError):
        with replacing([a, b]) as [ta, tb]:
            ta.write_text("new a")
            raise OSError("disk full")
    assert a.read_text() == "old" and not b.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]


# -- quality ---------------------------------------------------------------------------

def _size(tmp_path, spec, rate=44100, channels=2, name="q"):
    path = tmp_path / (name + ".out")
    with Writer(path, spec, rate, channels) as w:
        tone = sine(440, rate, 2.0, 0.2, channels=channels)
        noise = 0.05 * np.random.default_rng(0).standard_normal(tone.shape)
        w.write((tone + noise).astype(np.float32))
    return path.stat().st_size


def test_mp3_constant_rates_are_what_they_say(tmp_path):
    for label, top in (("Constant 320 kbit/s", 345), ("Constant 192 kbit/s", 210),
                       ("Constant 128 kbit/s", 140), ("Constant 64 kbit/s", 72)):
        quality = next(q for q in qualities(OutputSpec("MP3", "MPEG_LAYER_III")) if q.label == label)
        kbps = _size(tmp_path, OutputSpec("MP3", "MPEG_LAYER_III", quality)) * 8 / 2 / 1000
        wanted = int(label.split()[1])
        assert wanted * 0.95 < kbps < top, label


def test_mp3_constant_rates_hold_at_low_sample_rates(tmp_path):
    quality = next(q for q in qualities(OutputSpec("MP3", "MPEG_LAYER_III"))
                   if q.label == "Constant 64 kbit/s")
    kbps = _size(tmp_path, OutputSpec("MP3", "MPEG_LAYER_III", quality), 22050, 1) * 8 / 2 / 1000
    assert 55 < kbps < 75
    assert mp3_level(320, 8000) == 0.0  # past the top of that MPEG version's range: the top


def test_every_quality_of_every_codec_writes_and_more_means_more(tmp_path):
    for fmt, subtype, rate in (("MP3", "MPEG_LAYER_III", 44100), ("OGG", "VORBIS", 44100),
                               ("OGG", "OPUS", 48000), ("M4A", "AAC", 44100),
                               ("FLAC", "PCM_16", 44100)):
        sizes = {}
        for quality in qualities(OutputSpec(fmt, subtype)):
            sizes[quality.label] = _size(tmp_path, OutputSpec(fmt, subtype, quality), rate)
        first, last = list(sizes.values())[0], list(sizes.values())[-1]
        assert all(size > 0 for size in sizes.values()), subtype
        assert first > last, (subtype, sizes)  # each list runs from the most data to the least


def test_the_default_line_is_in_the_list():
    for spec in (OutputSpec("MP3", "MPEG_LAYER_III"), OutputSpec("OGG", "VORBIS"),
                 OutputSpec("OGG", "OPUS"), OutputSpec("M4A", "AAC"), OutputSpec("FLAC", "PCM_24")):
        assert default_quality(spec) in qualities(spec)
    assert default_quality(OutputSpec("WAV", "PCM_16")) is None
    assert qualities(OutputSpec("WAV", "PCM_16")) == ()


def test_a_quality_shows_in_the_description():
    spec = OutputSpec("M4A", "AAC", default_quality(OutputSpec("M4A", "AAC")))
    assert spec.describe() == "M4A AAC, 192 kbit/s"


def test_a_spec_without_a_quality_still_equals_itself():
    assert OutputSpec("WAV", "PCM_16") == OutputSpec("WAV", "PCM_16", None)


# -- what each format can hold ----------------------------------------------------------

def test_the_lists_hold_only_what_really_writes():
    assert list(subtype_names("MP3")) == ["MPEG_LAYER_III"]  # libsndfile lists I and II too
    assert "MPEG_LAYER_III" not in subtype_names("WAV")
    assert "DWVW_12" not in subtype_names("AIFF")
    assert {"VORBIS", "OPUS"} <= set(subtype_names("OGG"))
    assert subtype_names("M4A") == {"AAC": "AAC"}
    assert "M4A" in format_names() and "WAV" in format_names()


def test_rates_a_codec_cant_hold_go_up_to_one_it_can():
    opus, mp3 = OutputSpec("OGG", "OPUS"), OutputSpec("MP3", "MPEG_LAYER_III")
    assert rate_for(opus, 44100) == 48000 and rate_for(opus, 48000) == 48000
    assert rate_for(opus, 96000) == 48000 and rate_for(opus, 22050) == 24000
    assert rate_for(mp3, 96000) == 48000 and rate_for(mp3, 44100) == 44100
    assert rate_for(OutputSpec("WAV", "PCM_16"), 192000) == 192000


def test_channels_a_format_cant_hold_come_down():
    assert channels_for(OutputSpec("MP3", "MPEG_LAYER_III"), 4) == 2
    assert channels_for(OutputSpec("MP3", "MPEG_LAYER_III"), 1) == 1
    assert channels_for(OutputSpec("WAV", "PCM_16"), 32) == 32


def test_extensions_round_trip_through_spec_for():
    for fmt in format_names():
        for subtype in subtype_names(fmt):
            spec = OutputSpec(fmt, subtype)
            if fmt in ("WAVEX",):
                assert extension(spec) == ".wav"
            else:
                assert spec_for("x" + extension(spec)).format == fmt, spec


# -- AAC through ffmpeg ------------------------------------------------------------------

def test_m4a_comes_from_its_extension():
    assert spec_for("x.m4a") == OutputSpec("M4A", "AAC")
    with pytest.raises(ValueError):
        spec_for("x.m4a", bits="16")


def test_aac_round_trip_keeps_length_pitch_and_level(tmp_path):
    from soundrec.ffmpeg import readable

    rate, seconds = 44100, 2.0
    data = sine(997, rate, seconds, 0.25, channels=2)
    path = tmp_path / "a.m4a"
    with Writer(path, OutputSpec("M4A", "AAC"), rate, 2) as w:
        for at in range(0, len(data), 10_000):
            w.write(data[at:at + 10_000])
    with readable(path) as source:
        assert source != path
        back, back_rate = sf.read(str(source), dtype="float32", always_2d=True)
    assert back_rate == rate and back.shape[1] == 2
    assert abs(len(back) - len(data)) <= 2048
    middle = back[10_000:-10_000, 0]
    assert abs(peak_frequency(middle, rate) - 997) < 2
    assert abs(rms_db(middle) - rms_db(data[:, 0])) < 0.3


def test_aac_holds_four_channels(tmp_path):
    from soundrec.ffmpeg import readable

    data = np.zeros((44100, 4), np.float32)
    path = tmp_path / "q.m4a"
    with Writer(path, OutputSpec("M4A", "AAC"), 44100, 4) as w:
        w.write(data)
    with readable(path) as source:
        assert sf.info(str(source)).channels == 4


def test_a_broken_encoder_says_so(tmp_path):
    with pytest.raises(RuntimeError):
        with Writer(tmp_path / "no" / "such" / "folder.m4a", OutputSpec("M4A", "AAC"), 44100, 2) as w:
            w.write(np.zeros((1000, 2), np.float32))


def test_preflight_checks_aac_too():
    preflight(OutputSpec("M4A", "AAC"), 44100, 2)


def test_what_neither_can_read_says_so(tmp_path):
    from soundrec.ffmpeg import readable

    path = tmp_path / "not-sound.bin"
    path.write_bytes(b"nothing here")
    with pytest.raises(Exception):
        with readable(path):
            pass
