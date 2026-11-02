from soundrec.formats import channels_text, khz, rates_text, types_text


def test_khz_drops_trailing_zeros():
    assert khz(44100) == "44.1"
    assert khz(48000) == "48"
    assert khz(11025) == "11.025"
    assert khz(352800) == "352.8"


def test_rates_text_sorts():
    assert rates_text([48000, 44100]) == "44.1, 48 kHz"
    assert rates_text([]) == "no rate"


def test_channels_text():
    assert channels_text([1]) == "mono"
    assert channels_text([2]) == "stereo"
    assert channels_text([6]) == "6 ch"
    assert channels_text([2, 1, 3, 4]) == "1-4 ch"
    assert channels_text([1, 2, 6]) == "1, 2, 6 ch"
    assert channels_text([]) == "no channels"


def test_types_text_reads_asio_left_aligned_types():
    assert types_text(["int16", "float32"]) == "16-bit, 32-bit float"
    assert types_text(["int32/24"]) == "24-bit (in 32)"
    assert types_text(["DSD"]) == "DSD"
