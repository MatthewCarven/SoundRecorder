import numpy as np
import pytest
import soundfile as sf

from soundrec.cli import choose_device, main, native_rate, parse_pick, plan_channels
from soundrec.devices import Device
from soundrec.endpoints import Endpoint, WaveFormat
from soundrec.takes import Take, orphans

# In API_ORDER, as scan() returns them.
INPUTS = [
    Device("WASAPI", "Stereo Mix (Realtek(R) Audio)", 2, 48000, 10),
    Device("WASAPI", "ZOOM Recording Mixer (ZOOM H and F Series Audio)", 2, 44100, 11, is_default=True),
    Device("ASIO", "ZOOM H and F Series ASIO", 2, 44100, 5),
    Device("WDM-KS", "Microphone Array 2 (Realtek HD Audio Mic input with SST)", 4, 16000, 20),
    Device("WDM-KS", "Microphone Array 3 (Realtek HD Audio Mic input with SST)", 4, 16000, 21),
    Device("MME", "Stereo Mix (Realtek(R) Audio)", 2, 44100, 2),
    Device("MME", "ZOOM Recording Mixer (ZOOM H an", 2, 44100, 1, is_default=True),
]


def test_the_most_direct_api_wins():
    assert choose_device(INPUTS, "stereo mix").key == "WASAPI: Stereo Mix (Realtek(R) Audio)"
    assert choose_device(INPUTS, "stereo mix", "mme").index == 2


def test_no_name_means_the_default_device():
    assert choose_device(INPUTS).index == 11
    assert choose_device(INPUTS, api="MME").index == 1


def test_asio_by_api():
    assert choose_device(INPUTS, "zoom", "ASIO").index == 5


def test_an_unclear_name_lists_the_choices():
    with pytest.raises(ValueError, match="2 devices match") as e:
        choose_device(INPUTS, "microphone array")
    assert "WDM-KS: Microphone Array 3" in str(e.value)
    assert choose_device(INPUTS, "microphone array 3").index == 21


@pytest.mark.parametrize("text, api, message", [
    ("nothing like it", None, "no capture device matches"),
    ("zoom", "Loopback", "no Loopback capture devices"),
])
def test_no_such_device(text, api, message):
    with pytest.raises(ValueError, match=message):
        choose_device(INPUTS, text, api)


@pytest.mark.parametrize("text, channels", [
    (None, None), ("3,4", (2, 3)), ("1-4", (0, 1, 2, 3)), ("2", (1,)), ("1, 3-4", (0, 2, 3)),
])
def test_parse_pick(text, channels):
    assert parse_pick(text) == channels


@pytest.mark.parametrize("text", ["0", "a,b", "3-"])
def test_parse_pick_refuses(text):
    with pytest.raises(ValueError):
        parse_pick(text)


@pytest.mark.parametrize("available, out, pick, keep_all, planned", [
    (2, None, None, False, (2, 2, None)),        # stereo as it comes
    (2, 1, None, False, (2, 1, None)),           # both mixed to mono
    (1, 2, None, False, (1, 2, None)),           # mono copied to both sides
    (1, None, None, False, (1, 1, None)),
    (4, None, None, False, (2, 2, None)),        # the first two of four
    (4, 1, (2, 3), False, (4, 1, (2, 3))),       # inputs 3 and 4 mixed
    (4, None, (2,), False, (3, 1, (2,))),        # input 3 alone
    (4, None, None, True, (4, 4, None)),
])
def test_plan_channels(available, out, pick, keep_all, planned):
    assert plan_channels(available, out, pick, keep_all) == planned


def test_plan_channels_refuses():
    with pytest.raises(ValueError, match="has 2 channels"):
        plan_channels(2, None, (2,))
    with pytest.raises(ValueError, match="keep-all"):
        plan_channels(4, 2, None, True)


def test_mme_captures_at_the_engines_rate():
    engine = WaveFormat(48000, 2, 16, 16, False)
    endpoint = Endpoint("id", "capture", "Stereo Mix", "Realtek(R) Audio", "active", False,
                        "", "INTELAUDIO", engine)
    assert native_rate(Device("MME", "Stereo Mix", 2, 44100, 2, endpoint)) == 48000
    assert native_rate(Device("DirectSound", "Stereo Mix", 2, 44100, 3, endpoint)) == 48000
    assert native_rate(Device("MME", "Sound Mapper", 2, 44100, 0)) == 44100
    assert native_rate(Device("ASIO", "ZOOM", 2, 44100, 5)) == 44100


def test_recover_lists_saves_and_discards(tmp_path, capsys):
    target = tmp_path / "meant.flac"
    for seed in (1, 2):
        take = Take.create(44100, 2, device="WASAPI: Mic", target=str(target), bits="24")
        take.write(np.random.default_rng(seed).uniform(-0.5, 0.5, (4410, 2)).astype(np.float32))
        take.release()  # as a crash would leave it

    assert main(["recover"]) == 0
    listing = capsys.readouterr().out
    assert listing.count("WASAPI: Mic") == 2 and str(target) in listing

    assert main(["recover", "1"]) == 0  # to the file it was meant for, at its bit depth
    assert sf.info(str(target)).subtype == "PCM_24" and sf.info(str(target)).frames == 4410
    with pytest.raises(SystemExit):
        main(["recover", "1"])  # the next one's target exists now
    assert main(["recover", "1", "--discard"]) == 0
    assert orphans() == []
    assert main(["recover"]) == 0
    assert "No takes left behind" in capsys.readouterr().out
