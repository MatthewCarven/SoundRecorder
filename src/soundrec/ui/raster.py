"""A pixel surface to draw the window on: numpy RGB, 3.1's sixteen colours.

The window is drawn here at 3.1's own size, one array element per pixel,
and handed to Tk as a single image, scaled up by a whole number when the
screen wants it bigger. Drawing our own pixels keeps every line where 3.1
put it (Tk's canvas has its own ideas about line ends and widths), and it
means the whole window can be drawn, compared and saved as a PNG in a test,
with no window on the screen.

Coordinates are inclusive, as in a paint program: fill(0, 0, 3, 3) colours
a 4 x 4 square.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY = (192, 192, 192)        # button face, window background
DARK = (128, 128, 128)        # shadows, disabled text on grey
NAVY = (0, 0, 128)            # active caption, menu highlight
GREEN = (0, 255, 0)           # the waveform

# The standard VGA sixteen, in palette order. 3.1 inverted a colour by its
# index (15 - i), so light grey inverts to dark grey, not to (63, 63, 63).
PALETTE = [(0, 0, 0), (0, 0, 128), (0, 128, 0), (0, 128, 128), (128, 0, 0), (128, 0, 128),
           (128, 128, 0), (192, 192, 192), (128, 128, 128), (0, 0, 255), (0, 255, 0),
           (0, 255, 255), (255, 0, 0), (255, 0, 255), (255, 255, 0), (255, 255, 255)]


class Surface:
    def __init__(self, width: int, height: int, colour=GREY):
        self.width, self.height = width, height
        self.pixels = np.empty((height, width, 3), np.uint8)
        self.pixels[:] = colour

    # -- shapes -------------------------------------------------------------

    def fill(self, x0: int, y0: int, x1: int, y1: int, colour) -> None:
        if x1 < x0 or y1 < y0:
            return
        self.pixels[max(y0, 0):y1 + 1, max(x0, 0):x1 + 1] = colour

    def hline(self, x0: int, x1: int, y: int, colour) -> None:
        self.fill(x0, y, x1, y, colour)

    def vline(self, x: int, y0: int, y1: int, colour) -> None:
        self.fill(x, y0, x, y1, colour)

    def frame(self, x0: int, y0: int, x1: int, y1: int, colour) -> None:
        """A one-pixel outline."""
        self.hline(x0, x1, y0, colour)
        self.hline(x0, x1, y1, colour)
        self.vline(x0, y0, y1, colour)
        self.vline(x1, y0, y1, colour)

    def invert(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Invert a box as 3.1 did on a 16-colour screen: each colour to the
        one at the opposite end of the palette."""
        region = self.pixels[y0:y1 + 1, x0:x1 + 1]
        out = region.copy()
        for i, colour in enumerate(PALETTE):
            out[np.all(region == colour, axis=-1)] = PALETTE[15 - i]
        region[:] = out

    def sunken(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """3.1's one-pixel inset edge: dark grey above and left, white below and right."""
        self.hline(x0, x1, y0, DARK)
        self.vline(x0, y0, y1, DARK)
        self.hline(x0 + 1, x1, y1, WHITE)
        self.vline(x1, y0 + 1, y1 - 1, WHITE)

    def raised(self, x0: int, y0: int, x1: int, y1: int, light: int = 1, shadow: int = 2,
               light_wins: bool = False) -> None:
        """A raised edge just inside the box: `light` white rows and columns top
        and left, `shadow` dark ones bottom and right, meeting in diagonals at
        the two far corners. Who owns those corners differs in 3.1: the shadow on
        scroll arrows and the minimize button, the light on push buttons."""
        def lights():
            for i in range(light):
                self.hline(x0, x1 - i, y0 + i, WHITE)
                self.vline(x0 + i, y0, y1 - i, WHITE)

        def shadows():
            for i in range(shadow):
                self.hline(x0 + i, x1, y1 - i, DARK)
                self.vline(x1 - i, y0 + i, y1, DARK)

        first, second = (shadows, lights) if light_wins else (lights, shadows)
        first()
        second()

    def mask(self, x: int, y: int, ink: np.ndarray, colour, checker=None) -> None:
        """Colour the true pixels of a bool array with its top-left at (x, y),
        clipped to the surface. checker=(ox, oy) keeps only every other pixel,
        counted from that origin: 3.1's look for a disabled glyph, its pattern
        lined up with the control the glyph is on."""
        h, w = ink.shape
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, self.width), min(y + h, self.height)
        if x1 <= x0 or y1 <= y0:
            return
        part = ink[y0 - y:y1 - y, x0 - x:x1 - x]
        if checker is not None:
            ys, xs = np.ogrid[y0:y1, x0:x1]
            part = part & ((xs - checker[0] + ys - checker[1]) % 2 == 0)
        self.pixels[y0:y1, x0:x1][part] = colour

    def pattern(self, x: int, y: int, rows, colours=None) -> None:
        """Small multicoloured bitmaps: '#' black, 'w' white, 'd' dark grey,
        'g' grey, anything else left alone."""
        colours = colours or {"#": BLACK, "w": WHITE, "d": DARK, "g": GREY}
        for dy, row in enumerate(rows):
            for dx, c in enumerate(row):
                if c in colours and 0 <= x + dx < self.width and 0 <= y + dy < self.height:
                    self.pixels[y + dy, x + dx] = colours[c]

    def text(self, font, x: int, y: int, text: str, colour, underline: int | None = None,
             underline_shift: int = 0, checker=None) -> int:
        """Draw text with its glyph cells' top-left at (x, y); returns its width.
        `underline` is the index of the character to underline (a mnemonic),
        drawn two rows below the baseline across the character's cell;
        underline_shift moves it (3.1's menus put it a pixel to the left)."""
        ink = font.render(text)
        self.mask(x, y, ink, colour, checker)
        if underline is not None and 0 <= underline < len(text):
            left, advance = font.offsets(text)[underline]
            if underline:
                left += underline_shift
            self.hline(x + left, x + left + advance - 1, y + font.ascent + 1, colour)
        return ink.shape[1]

    def blit(self, other: Surface, x: int, y: int) -> None:
        h, w = other.height, other.width
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, self.width), min(y + h, self.height)
        if x1 > x0 and y1 > y0:
            self.pixels[y0:y1, x0:x1] = other.pixels[y0 - y:y1 - y, x0 - x:x1 - x]

    # -- out ----------------------------------------------------------------

    def scaled(self, zoom: int) -> np.ndarray:
        if zoom == 1:
            return self.pixels
        return self.pixels.repeat(zoom, axis=0).repeat(zoom, axis=1)

    def ppm(self, zoom: int = 1) -> bytes:
        """Binary PPM, which Tk's photo images take as data."""
        pixels = self.scaled(zoom)
        return b"P6\n%d %d\n255\n" % (pixels.shape[1], pixels.shape[0]) + pixels.tobytes()

    def png(self, zoom: int = 1) -> bytes:
        pixels = self.scaled(zoom)
        h, w = pixels.shape[:2]
        rows = np.zeros((h, w * 3 + 1), np.uint8)  # each row starts with filter type 0
        rows[:, 1:] = pixels.reshape(h, w * 3)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows.tobytes(), 9)) + chunk(b"IEND", b""))


def bitmap(*rows: str) -> np.ndarray:
    """A bool array from rows of '#' (ink) and '.' (none)."""
    return np.array([[c == "#" for c in row] for row in rows], bool)
