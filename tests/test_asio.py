import pytest

from soundrec import asio
from soundrec.formats import TYPE_TEXT


def test_every_little_endian_pcm_type_reads_out():
    for code in (16, 17, 18, 19, 20, 24, 25, 26, 27):
        assert asio.SAMPLE_TYPES[code] in TYPE_TEXT


def test_unknown_driver_is_refused_before_anything_loads(monkeypatch):
    monkeypatch.setattr(asio, "drivers", lambda: {"Real ASIO": "{00000000-0000-0000-0000-000000000000}"})
    with pytest.raises(asio.AsioError, match="no ASIO driver called 'Nope'"):
        asio.query("Nope")
