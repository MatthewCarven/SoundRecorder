import struct
import uuid

from soundrec.endpoints import (PKEY_DEVICE_DESC, PKEY_ENGINE_FORMAT, PKEY_ENUMERATOR,
                                PKEY_FORM_FACTOR, PKEY_INTERFACE_NAME, WaveFormat,
                                make_endpoint, parse_waveformat)

# Straight from this laptop's registry (2026-11-02).
MIC_ARRAY_ENGINE = bytes.fromhex(
    "4100000001000000feff020080bb000000ee02000400100016001000"
    "030000000100000000001000800000aa00389b71")
MIC_ARRAY_RAW_FLOAT = bytes.fromhex(
    "4100000001000000feff0400803e000000e803001000200016002000"
    "000000000300000000001000800000aa00389b71")

PCM = uuid.UUID("00000001-0000-0010-8000-00aa00389b71")


def extensible(rate, channels, bits, valid, subtype=PCM):
    align = channels * bits // 8
    return (struct.pack("<HHIIHHHHI", 0xFFFE, channels, rate, rate * align, align, bits,
                        22, valid, 3) + subtype.bytes_le)


def test_engine_format_from_registry():
    assert parse_waveformat(MIC_ARRAY_ENGINE) == WaveFormat(48000, 2, 16, 16, False)
    assert str(parse_waveformat(MIC_ARRAY_ENGINE)) == "48,000 Hz, 16-bit, stereo"


def test_float_subtype_from_registry():
    assert parse_waveformat(MIC_ARRAY_RAW_FLOAT) == WaveFormat(16000, 4, 32, 32, True)
    assert str(parse_waveformat(MIC_ARRAY_RAW_FLOAT)) == "16,000 Hz, 32-bit float, 4 ch"


def test_24_bits_in_32():
    fmt = parse_waveformat(extensible(44100, 2, 32, 24))
    assert (fmt.bits, fmt.valid_bits, fmt.is_float) == (32, 24, False)
    assert str(fmt) == "44,100 Hz, 24-bit (in 32), stereo"


def test_plain_waveformatex_without_header():
    blob = struct.pack("<HHIIHH", 1, 1, 11025, 11025, 1, 8)
    assert parse_waveformat(blob) == WaveFormat(11025, 1, 8, 8, False)


def test_unknown_or_short_blobs_give_none():
    assert parse_waveformat(struct.pack("<HHIIHH", 0x55, 2, 44100, 16000, 1, 0)) is None  # MP3
    assert parse_waveformat(b"\x41\x00\x00\x00\x01\x00\x00\x00\x01\x00") is None


def props(**kw):
    base = {PKEY_DEVICE_DESC: "Microphone Array", PKEY_INTERFACE_NAME: "Realtek(R) Audio",
            PKEY_FORM_FACTOR: 4, PKEY_ENUMERATOR: "INTELAUDIO", PKEY_ENGINE_FORMAT: MIC_ARRAY_ENGINE}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def test_make_endpoint_reads_the_properties():
    e = make_endpoint("capture", "{0.0.1.00000000}.{x}", 1, props())
    assert e.name == "Microphone Array (Realtek(R) Audio)"
    assert (e.state, e.hidden, e.form_factor, e.bus) == ("active", False, "microphone", "INTELAUDIO")
    assert e.engine_format.rate == 48000


def test_state_flags():
    assert make_endpoint("capture", "x", 0x10000004, props()).state == "not present"
    assert make_endpoint("capture", "x", 0x10000004, props()).hidden
    assert make_endpoint("render", "x", 8, props()).state == "unplugged"
    assert make_endpoint("render", "x", 2, props()).state == "disabled"


def test_missing_properties():
    e = make_endpoint("capture", "x", 4, props(**{PKEY_INTERFACE_NAME: None, PKEY_FORM_FACTOR: 99,
                                                   PKEY_ENGINE_FORMAT: None}))
    assert e.name == "Microphone Array"
    assert e.form_factor == ""
    assert e.engine_format is None
    assert make_endpoint("capture", "x", 1, {}).name == "(unnamed)"
