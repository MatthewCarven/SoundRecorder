r"""Bitmap fonts, read straight out of Windows' own .fon files.

Windows 11 still ships the fonts Windows 3.1 drew with: the System font
(vgasys.fon) for captions and menus, and MS Sans Serif (sserife.fon, 3.1's
"Helv") for Sound Recorder's labels. Tk can draw both through GDI, and the
font check at the start of Phase 3 found it does so exactly: pure black and
background, no smoothing. But GDI picks a raster font's size by itself, so at
2x the labels would come out in MS Sans Serif's 18-point design instead of
the 8-point one doubled. Reading the glyphs ourselves keeps every zoom exact
and lets the whole window be drawn, and tested, without one.

A .fon file is a 16-bit Windows (NE) executable whose RT_FONT resources are
FNT bitmap fonts, version 2 or 3: a header, a table of character widths and
offsets, and each glyph stored as columns of bytes, 8 pixels wide.

Bold MS Sans Serif isn't in the file: GDI makes it by drawing each glyph a
second time one pixel to the right, one pixel wider. So does BitmapFont.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

RT_FONT = 0x8008  # resource type 8, with the "integer id" bit


def fonts_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


@dataclass
class BitmapFont:
    face: str
    points: int
    resolution: int        # the dpi it was drawn for
    height: int            # rows in every glyph
    ascent: int            # rows from the top of a glyph to its baseline
    internal_leading: int  # blank rows at the top, inside the height
    weight: int
    first: int             # first character code in the font
    default: int           # code drawn for characters it lacks
    widths: list[int]
    glyphs: list[np.ndarray]  # bool, height x width, one per code from `first`
    bold: bool = False
    _cache: dict = field(default_factory=dict, repr=False)

    def emboldened(self) -> BitmapFont:
        return BitmapFont(self.face, self.points, self.resolution, self.height, self.ascent,
                          self.internal_leading, self.weight, self.first, self.default,
                          self.widths, self.glyphs, bold=True)

    def _codes(self, text: str) -> list[int]:
        last = self.first + len(self.glyphs) - 1
        codes = []
        for byte in text.encode("cp1252", errors="replace"):
            codes.append(byte if self.first <= byte <= last else self.default)
        return codes

    def advance(self, code: int) -> int:
        return self.widths[code - self.first] + self.bold

    def measure(self, text: str) -> int:
        return sum(self.advance(c) for c in self._codes(text))

    def offsets(self, text: str) -> list[tuple[int, int]]:
        """(left, advance) of each character, from the start of the text."""
        out, x = [], 0
        for code in self._codes(text):
            out.append((x, self.advance(code)))
            x += out[-1][1]
        return out

    def render(self, text: str) -> np.ndarray:
        """The text's ink: bool, height x measure(text)."""
        hit = self._cache.get(text)
        if hit is not None:
            return hit
        codes = self._codes(text)
        ink = np.zeros((self.height, sum(self.advance(c) for c in codes)), bool)
        x = 0
        for code in codes:
            glyph = self.glyphs[code - self.first]
            w = glyph.shape[1]
            ink[:, x:x + w] |= glyph
            if self.bold:
                ink[:, x + 1:x + 1 + w] |= glyph
            x += self.advance(code)
        if len(self._cache) < 512:
            self._cache[text] = ink
        return ink


def _fnt(data: bytes) -> BitmapFont:
    version, = struct.unpack_from("<H", data, 0)
    if version not in (0x200, 0x300):
        raise ValueError(f"FNT version {version:#x}")
    (font_type, points, vert_res, _horiz_res, ascent, internal_leading, _external_leading
     ) = struct.unpack_from("<7H", data, 66)
    weight, = struct.unpack_from("<H", data, 83)
    pix_height, = struct.unpack_from("<H", data, 88)
    first, last, default = data[95], data[96], data[97]
    face_at, = struct.unpack_from("<I", data, 105)
    if font_type & 1:
        raise ValueError("a vector font, not a bitmap one")
    face = data[face_at:data.index(b"\0", face_at)].decode("latin-1")
    table, entry = (118, "<HH") if version == 0x200 else (148, "<HI")
    size = struct.calcsize(entry)
    widths, glyphs = [], []
    for i in range(last - first + 1):
        width, at = struct.unpack_from(entry, data, table + i * size)
        columns = (width + 7) // 8
        raw = np.frombuffer(data, np.uint8, columns * pix_height, at).reshape(columns, pix_height)
        bits = np.unpackbits(raw, axis=1).reshape(columns, pix_height, 8)
        # columns x rows x 8 pixels -> rows x (columns * 8), cut to the width
        glyph = bits.transpose(1, 0, 2).reshape(pix_height, columns * 8)[:, :width].astype(bool)
        widths.append(width)
        glyphs.append(glyph)
    return BitmapFont(face, points, vert_res, pix_height, ascent, internal_leading, weight,
                      first, first + default, widths, glyphs)


def read_fon(path) -> list[BitmapFont]:
    """Every bitmap font in a .fon file."""
    data = Path(path).read_bytes()
    if data[:2] != b"MZ":
        raise ValueError(f"{path} isn't a font resource file")
    ne, = struct.unpack_from("<I", data, 0x3C)
    if data[ne:ne + 2] != b"NE":
        raise ValueError(f"{path} isn't a 16-bit (NE) font file")
    table = ne + struct.unpack_from("<H", data, ne + 0x24)[0]
    shift, = struct.unpack_from("<H", data, table)
    at, fonts = table + 2, []
    while True:
        type_id, count = struct.unpack_from("<HH", data, at)
        at += 8
        if type_id == 0:
            return fonts
        for _ in range(count):
            offset, length = struct.unpack_from("<HH", data, at)
            at += 12
            if type_id == RT_FONT:
                start = offset << shift
                fonts.append(_fnt(data[start:start + (length << shift)]))


@lru_cache(maxsize=None)
def system_font() -> BitmapFont:
    """The 3.1 System font at 96 dpi: captions, menus, dialog buttons."""
    return read_fon(fonts_dir() / "vgasys.fon")[0]


@lru_cache(maxsize=None)
def sans_serif(points: int = 8, bold: bool = False) -> BitmapFont:
    """MS Sans Serif at 96 dpi (3.1's "Helv")."""
    for font in read_fon(fonts_dir() / "sserife.fon"):
        if font.points == points:
            return font.emboldened() if bold else font
    raise ValueError(f"no {points}-point MS Sans Serif")
