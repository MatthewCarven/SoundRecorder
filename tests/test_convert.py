import numpy as np
import pytest
import soxr

from signals import fit, peak_frequency, rms_db, sine
from soundrec.convert import ChannelMap, Converter, Resampler


def stream(converter, x, sizes):
    """Push x through in blocks of the given sizes (cycled), then flush."""
    out, at, n = [], 0, 0
    while at < len(x):
        size = sizes[n % len(sizes)]
        out.append(converter.process(x[at:at + size]))
        at += size
        n += 1
    out.append(converter.flush())
    return np.concatenate(out)


def ragged_sizes(seed=1, count=500):
    """Block sizes from 1 frame to 5000, with ASIO's 64 and WASAPI's 480 among them."""
    rng = np.random.default_rng(seed)
    return [64, 1, 480, 4799] + list(rng.integers(1, 5000, count))


# -- channel map ---------------------------------------------------------------

def test_keep_all_is_untouched():
    m = ChannelMap.build(2, 2)
    block = np.ones((10, 2), np.float32)
    assert m.is_identity and m.apply(block) is block
    assert m.describe() == "all channels as captured"


def test_pick_routes_channels():
    block = np.arange(40, dtype=np.float32).reshape(10, 4)
    m = ChannelMap.build(4, 2, pick=(2, 3))  # ZOOM inputs 3 and 4
    assert np.array_equal(m.apply(block), block[:, 2:4])
    assert m.describe() == "channels 3, 4"


def test_mix_to_mono_is_the_average():
    block = np.array([[0.5, -0.5], [0.25, 0.75], [1.0, 1.0]], np.float32)
    m = ChannelMap.build(2, 1)
    assert np.array_equal(m.apply(block), [[0.0], [0.5], [1.0]])
    assert m.apply(block).dtype == np.float32
    assert m.describe() == "channels 1, 2 mixed to mono"


def test_one_channel_copied_to_stereo():
    block = np.array([[0.1], [0.2]], np.float32)
    m = ChannelMap.build(1, 2)
    assert np.array_equal(m.apply(block), np.array([[0.1, 0.1], [0.2, 0.2]], np.float32))
    assert m.describe() == "channel 1 copied to 2 channels"


@pytest.mark.parametrize("inputs, outputs, pick, message", [
    (2, 2, (0, 2), "channel 3 isn't captured"),
    (4, 2, None, "4 channels can't make 2"),
    (2, 1, (), "no channels picked"),
])
def test_impossible_maps(inputs, outputs, pick, message):
    with pytest.raises(ValueError, match=message):
        ChannelMap.build(inputs, outputs, pick)


# -- resampler -----------------------------------------------------------------

def test_matching_rates_pass_samples_through_untouched():
    r = Resampler(48000, 48000, 2)
    block = np.random.default_rng(0).standard_normal((1000, 2)).astype(np.float32)
    assert r.passthrough and r.process(block) is block
    assert r.flush().shape == (0, 2)


def test_streaming_matches_resampling_the_whole_take_at_once():
    x = np.random.default_rng(2).standard_normal((48000 * 2, 2)).astype(np.float32) * 0.3
    streamed = stream(Converter(48000, 2, 44100, 2), x, ragged_sizes())
    whole = soxr.resample(x, 48000, 44100, quality="VHQ")
    assert streamed.shape == whole.shape == (88200, 2)
    assert np.array_equal(streamed, whole)


def test_sine_keeps_its_pitch_and_level_with_no_clicks_at_block_boundaries():
    rate_in, rate_out, freq = 48000, 44100, 997.0
    x = sine(freq, rate_in, 5.0)
    y = stream(Converter(rate_in, 1, rate_out, 1), x, ragged_sizes())[:, 0]
    assert len(y) == 5 * rate_out

    edge = 2000  # the sine starts and stops dead: leave those edges out
    middle = y[edge:-edge]
    amplitude, phase, worst = fit(middle, freq, rate_out, start=edge)
    assert 20 * np.log10(amplitude / 0.5) == pytest.approx(0, abs=0.001)  # level, in dB
    assert abs(phase) < 1e-4            # no delay: soxr takes its own filter's out
    # No sample anywhere strays: no clicks. This also pins the pitch: 0.001 Hz
    # off would drift 0.03 rad over the 5 s, a residual of 0.016.
    assert worst < 1e-5
    # A second opinion by another method (the estimate's own bias is ~0.01 Hz).
    assert peak_frequency(y[edge:edge + 65536], rate_out) == pytest.approx(freq, abs=0.05)
    assert rms_db(middle) == pytest.approx(rms_db(x[edge:-edge]), abs=0.002)


def test_mix_then_resample():
    left = sine(997, 48000, 1.0, amplitude=0.4)
    right = sine(997, 48000, 1.0, amplitude=0.2)
    y = stream(Converter(48000, 2, 44100, 1), np.hstack([left, right]), [480])[:, 0]
    amplitude, _, worst = fit(y[2000:-2000], 997, 44100, start=2000)
    assert amplitude == pytest.approx(0.3, rel=1e-4)
    assert worst < 1e-5


@pytest.mark.parametrize("rate_in, rate_out", [(44100, 48000), (48000, 16000), (16000, 44100)])
def test_other_rates_keep_pitch(rate_in, rate_out):
    y = stream(Converter(rate_in, 1, rate_out, 1), sine(440, rate_in, 2.0), [333])[:, 0]
    assert len(y) == 2 * rate_out
    amplitude, phase, worst = fit(y[2000:-2000], 440, rate_out, start=2000)
    assert amplitude == pytest.approx(0.5, rel=1e-4) and abs(phase) < 1e-4 and worst < 1e-4
