import pytest

from soundrec.asio import AsioInfo, Channel
from soundrec.devices import Device
from soundrec.endpoints import Endpoint, WaveFormat
from soundrec.formats import RATES, SAMPLE_TYPES
from soundrec.probe import Probe, _error_code, probe

ENGINE = WaveFormat(48000, 2, 16, 16, False)
ENDPOINT = Endpoint("id", "capture", "Microphone Array", "Realtek(R) Audio", "active", False,
                    "microphone", "INTELAUDIO", ENGINE)


class PaError(Exception):
    """Shaped like sounddevice.PortAudioError: (message, code), printed the same way."""

    def __str__(self):
        return f"{self.args[0]} [PaErrorCode {self.args[1]}]"


REFUSED = PaError("Invalid sample rate", -9997)


def accepting(allowed, error=REFUSED, calls=None):
    def check(index, channels, dtype, samplerate, extra_settings=None):
        if calls is not None:
            calls.append((samplerate, dtype, channels, extra_settings))
        if (samplerate, dtype, channels) not in allowed:
            raise error
    return check


def never_called(*args, **kw):
    raise AssertionError("should not be asked")


def test_shared_apis_are_not_probed():
    for api in ("MME", "DirectSound", "Loopback"):
        result = probe(Device(api, "Mic", 4, 44100, 0, ENDPOINT), check=never_called)
        assert not result.native
        assert result.rates == RATES and result.sample_types == SAMPLE_TYPES
        assert result.channels == (1, 2, 3, 4)
        assert "from the engine's 48,000 Hz, 16-bit, stereo" in result.note


def test_shared_api_without_an_endpoint():
    result = probe(Device("MME", "Microsoft Sound Mapper - Input", 2, 44100, 0), check=never_called)
    assert result.note == "takes anything, converted by Windows"


def test_wasapi_exclusive_answers_jointly():
    allowed = {(44100, "int16", 1), (44100, "int16", 2), (48000, "int16", 2), (48000, "int24", 2)}
    calls = []
    result = probe(Device("WASAPI", "ZOOM", 2, 44100, 5, ENDPOINT),
                   check=accepting(allowed, calls=calls), exclusive="EXCLUSIVE")
    assert result.native
    assert result.rates == (44100, 48000)
    assert result.sample_types == ("int16", "int24")
    assert result.channels == (1, 2)
    assert result.combos == frozenset(allowed)
    assert result.summary() == "44.1, 48 kHz; 16-bit, 24-bit; 1-2 ch"
    assert result.note.startswith("native is exclusive mode; shared mode takes anything")
    assert len(calls) == len(RATES) * len(SAMPLE_TYPES) * 2
    assert {c[3] for c in calls} == {"EXCLUSIVE"}


def test_wasapi_that_cant_be_asked_says_why():
    busy = PaError("Device unavailable", -9985)
    result = probe(Device("WASAPI", "Mic", 2, 48000, 5, ENDPOINT), check=accepting(set(), busy))
    assert result.rates == () and result.error == "Device unavailable [PaErrorCode -9985]"


def test_wasapi_refusing_everything():
    result = probe(Device("WASAPI", "Mic", 2, 48000, 5, ENDPOINT), check=accepting(set()))
    assert result.error == "took no format in exclusive mode"


def test_wdm_ks_tries_one_sample_type_and_says_types_are_converted():
    allowed = {(16000, "float32", c) for c in (1, 2, 3, 4)}
    calls = []
    result = probe(Device("WDM-KS", "Microphone Array 2", 4, 16000, 9),
                   check=accepting(allowed, calls=calls))
    assert {c[1] for c in calls} == {"float32"}
    assert result.native and result.sample_types == ()
    assert result.rates == (16000,) and result.channels == (1, 2, 3, 4)
    assert result.summary() == "16 kHz; any sample type (converted); 1-4 ch"


def test_asio_asks_the_driver():
    info = AsioInfo("ZOOM", 1, (44100, 48000), 44100,
                    (Channel("In 01", "int16"), Channel("In 02", "int16")), 2, (64, 64, 64))
    result = probe(Device("ASIO", "ZOOM H and F Series ASIO", 2, 44100, 4),
                   check=never_called, asio_query=lambda name: info)
    assert result.rates == (44100, 48000)
    assert result.sample_types == ("int16",)
    assert result.channel_names == ("In 01", "In 02")
    assert result.channels == (1, 2)
    assert "buffer 64-64 frames" in result.note


def test_asio_falls_back_on_portaudio_rates():
    def broken(name):
        raise OSError("driver missing")

    allowed = {(44100, "float32", 1), (48000, "float32", 1)}
    result = probe(Device("ASIO", "Gone ASIO", 2, 44100, 4), check=accepting(allowed),
                   asio_query=broken)
    assert result.rates == (44100, 48000)
    assert result.sample_types == ()
    assert "driver missing" in result.error


@pytest.mark.parametrize("error, code", [
    (PaError("Invalid sample rate", -9997), -9997),
    (Exception("Invalid number of channels [PaErrorCode -9998]"), -9998),
    (Exception("something else"), None),
])
def test_error_code(error, code):
    assert _error_code(error) == code


def test_from_combos_orders_sample_types_smallest_first():
    p = Probe.from_combos({(48000, "float32", 2), (48000, "uint8", 1)}, native=True)
    assert p.sample_types == ("uint8", "float32")
