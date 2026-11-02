from soundrec.devices import Device, build_devices, match_endpoint
from soundrec.endpoints import Endpoint, WaveFormat
from soundrec.loopback import LoopbackSource


def endpoint(flow, description, interface, state="active", id=None, fmt=None):
    return Endpoint(id or f"{flow}:{description}:{interface}", flow, description, interface, state,
                    False, "", "", fmt)


MIC = endpoint("capture", "Microphone Array", "Realtek(R) Audio")
MIX = endpoint("capture", "Stereo Mix", "Realtek(R) Audio")
ZOOM = endpoint("capture", "ZOOM Recording Mixer", "ZOOM H and F Series Audio")
GONE = endpoint("capture", "Microphone", "High Definition Audio Device", state="not present")
SPEAKERS = endpoint("render", "Speakers", "Realtek(R) Audio", id="{0.0.0.00000000}.{spk}",
                    fmt=WaveFormat(44100, 2, 32, 24, False))
ENDPOINTS = [MIC, MIX, ZOOM, GONE, SPEAKERS]

APIS = [
    {"name": "MME", "default_input_device": 1, "default_output_device": 7},
    {"name": "Windows DirectSound", "default_input_device": 3, "default_output_device": -1},
    {"name": "ASIO", "default_input_device": 4, "default_output_device": 4},
    {"name": "Windows WASAPI", "default_input_device": 6, "default_output_device": 8},
    {"name": "Windows WDM-KS", "default_input_device": 9, "default_output_device": -1},
]


def dev(name, hostapi, inputs, outputs=0, rate=44100.0):
    return {"name": name, "hostapi": hostapi, "max_input_channels": inputs,
            "max_output_channels": outputs, "default_samplerate": rate}


# Shaped like this laptop's PortAudio table.
PA = [
    dev("Microsoft Sound Mapper - Input", 0, 2),
    dev("ZOOM Recording Mixer (ZOOM H an", 0, 2),
    dev("Microphone Array (Realtek(R) Au", 0, 4),
    dev("ZOOM Recording Mixer (ZOOM H and F Series Audio)", 1, 2),
    dev("ZOOM H and F Series ASIO", 2, 2, 2),
    dev("Stereo Mix (Realtek(R) Audio)", 0, 2),
    dev("Microphone Array (Realtek(R) Audio)", 3, 2, 0, 48000.0),
    dev("Speakers (Realtek(R) Audio)", 0, 0, 2),
    dev("Speakers (Realtek(R) Audio)", 3, 0, 2, 48000.0),
    dev("Microphone Array 2 (Realtek HD Audio Mic input with SST)", 4, 4, 0, 16000.0),
]


def by_key(devices):
    return {d.key: d for d in devices}


def test_every_api_with_an_input_is_listed_in_display_order():
    inputs = build_devices("input", PA, APIS, ENDPOINTS)
    assert [d.api for d in inputs] == ["WASAPI", "ASIO", "WDM-KS", "DirectSound",
                                       "MME", "MME", "MME", "MME"]
    # within an API, PortAudio's order stands
    assert [d.name for d in inputs if d.api == "MME"][:2] == ["Microsoft Sound Mapper - Input",
                                                             "ZOOM Recording Mixer (ZOOM H an"]


def test_endpoints_are_matched_by_name_per_api():
    inputs = by_key(build_devices("input", PA, APIS, ENDPOINTS))
    assert inputs["WASAPI: Microphone Array (Realtek(R) Audio)"].endpoint is MIC
    assert inputs["DirectSound: ZOOM Recording Mixer (ZOOM H and F Series Audio)"].endpoint is ZOOM
    assert inputs["MME: ZOOM Recording Mixer (ZOOM H an"].endpoint is ZOOM   # cut to 31 characters
    assert inputs["MME: Stereo Mix (Realtek(R) Audio)"].endpoint is MIX     # short enough to be whole
    assert inputs["MME: Microsoft Sound Mapper - Input"].endpoint is None
    assert inputs["ASIO: ZOOM H and F Series ASIO"].endpoint is None
    assert inputs["WDM-KS: Microphone Array 2 (Realtek HD Audio Mic input with SST)"].endpoint is None


def test_defaults_and_channels():
    inputs = by_key(build_devices("input", PA, APIS, ENDPOINTS))
    assert inputs["MME: ZOOM Recording Mixer (ZOOM H an"].is_default
    assert not inputs["MME: Microphone Array (Realtek(R) Au"].is_default
    assert inputs["MME: Microphone Array (Realtek(R) Au"].channels == 4
    assert inputs["WASAPI: Microphone Array (Realtek(R) Audio)"].default_rate == 48000


def test_short_mme_names_must_match_whole():
    other = endpoint("capture", "Stereo Mix", "Realtek(R) Audio Extra")
    assert match_endpoint("MME", "Stereo Mix (Realtek(R) Audio)", [MIX, other]) is MIX


def test_ambiguous_truncated_name_matches_nothing():
    twin = endpoint("capture", "ZOOM Recording Mixer", "ZOOM H and F Series Audio 2")
    assert match_endpoint("MME", "ZOOM Recording Mixer (ZOOM H an", [ZOOM, twin]) is None


def test_inactive_endpoints_are_not_matched():
    inputs = build_devices("input", [dev("Microphone (High Definition Audio Device)", 3, 2)],
                           APIS, ENDPOINTS)
    assert inputs[0].endpoint is None


def test_loopback_joins_its_render_endpoint():
    loops = [LoopbackSource("{0.0.0.00000000}.{spk}", "Speakers (Realtek(R) Audio)", 2, True),
             LoopbackSource("{0.0.0.00000000}.{other}", "Other", 2, False)]
    inputs = build_devices("input", [], APIS, ENDPOINTS, loops)
    assert [d.api for d in inputs] == ["Loopback", "Loopback"]
    assert inputs[0].endpoint is SPEAKERS and inputs[0].default_rate == 44100
    assert inputs[0].is_default and inputs[0].index is None
    assert inputs[1].endpoint is None and inputs[1].default_rate == 48000


def test_outputs_use_output_channels_and_render_endpoints():
    outputs = by_key(build_devices("output", PA, APIS, ENDPOINTS))
    assert set(outputs) == {"ASIO: ZOOM H and F Series ASIO", "MME: Speakers (Realtek(R) Audio)",
                            "WASAPI: Speakers (Realtek(R) Audio)"}
    assert outputs["WASAPI: Speakers (Realtek(R) Audio)"].endpoint is SPEAKERS
    assert outputs["WASAPI: Speakers (Realtek(R) Audio)"].is_default


def test_key_is_api_and_name():
    assert Device("ASIO", "FL Studio ASIO", 2, 44100).key == "ASIO: FL Studio ASIO"
