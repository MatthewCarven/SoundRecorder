"""The Sound Recorder window, drawn as Windows 3.1 drew it.

Every position here was measured from a 640 x 480 screenshot of the real
3.1 Sound Recorder: a 317 x 169 window with a one-pixel black border, an
18-pixel caption, an 18-pixel white menu bar, and a grey client area holding
the status box, the Position, wave and Length panels, the scrollbar and five
56 x 23 buttons. Coordinates are the window's own, border included, and
inclusive at both ends.

`paint(state)` draws a whole window from a FaceState; `hit(x, y)` says
what's under a point. Neither needs Tk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .fonts import sans_serif, system_font
from .raster import BLACK, DARK, GREEN, GREY, NAVY, WHITE, Surface, bitmap

WIDTH, HEIGHT = 317, 169

CAPTION = (1, 1, 315, 18)
CONTROL_BOX = (1, 1, 18, 18)
TITLE = (20, 1, 296, 18)
MINIMIZE = (298, 1, 315, 18)
MENU_BAR = (1, 20, 315, 37)
CLIENT = (1, 39, 315, 167)
STATUS = (12, 46, 305, 68)
POSITION = (12, 75, 81, 111)
WAVE = (92, 75, 224, 111)
LENGTH = (236, 75, 305, 111)
SCROLL = (12, 119, 305, 135)
SCROLL_LEFT = (13, 120, 27, 134)
SCROLL_RIGHT = (290, 120, 304, 134)
TROUGH = (29, 120, 288, 134)
THUMB_TRAVEL = (28, 273)  # where the thumb's left edge line can be
BUTTON_NAMES = ("rewind", "forward", "play", "stop", "record")
BUTTONS = dict(zip(BUTTON_NAMES, [(12, 140, 67, 162), (71, 140, 126, 162), (131, 140, 186, 162),
                                  (190, 140, 245, 162), (250, 140, 305, 162)]))

MENU_TEXT_X = 9   # the first title's text
MENU_GAP = 16     # between one title's text and the next


def _left(tip: int):
    """3.1's button triangle, 11 rows tall, pointing left with its tip at column `tip`."""
    return [(row, tip + 2 * abs(row - 5), tip + 10) for row in range(11)]


def _right(base: int):
    return [(row, base, base + 10 - 2 * abs(row - 5)) for row in range(11)]


def _glyph(spans, top: int) -> np.ndarray:
    """A 50 x 17 button face from (row, first column, last column) spans."""
    ink = np.zeros((17, 50), bool)
    for row, a, b in spans:
        ink[top + row, a:b + 1] = True
    return ink


GLYPHS = {
    "rewind": _glyph(_left(14) + _left(25), 3),
    "forward": _glyph(_right(13) + _right(24), 3),
    "play": _glyph(_right(20), 3),
    "stop": _glyph([(row, 18, 30) for row in range(9)], 4),
    "record": np.pad(bitmap(  # the microphone, drawn on the slant
        "............#.#..",
        "...........#...#.",
        "..........#.#...#",
        ".............#.#.",
        "..........#...#.#",
        ".........#.#.#.#.",
        "........#...#.#..",
        ".......#...#.....",
        "......#...#......",
        ".....#...#.......",
        "....#...#........",
        "...#...#.........",
        "......#..........",
        ".....#...........",
        "..#..............",
        ".#...............",
        "#................",
    ), ((0, 0), (16, 17))),
}

CONTROL_MENU_GLYPH = (  # the "space bar" in the control-menu box, with its shadow
    "#############.",
    "#wwwwwwwwwww#d",
    "#############d",
    ".ddddddddddddd",
)
MINIMIZE_ARROW = bitmap(
    "#######",
    ".#####.",
    "..###..",
    "...#...",
)


def seconds_text(seconds: float) -> str:
    """3.1's readout: hundredths, never rounded up past the true value."""
    return f"{math.floor(max(seconds, 0.0) * 100 + 1e-6) / 100:.2f} sec."


@dataclass
class FaceState:
    title: str = "Sound Recorder - (Untitled)"
    active: bool = True             # the window has the focus: navy caption
    menus: tuple[str, ...] = ("&File", "&Edit", "Effect&s", "&Help")
    menu_highlight: int | None = None
    control_box_down: bool = False  # its menu is open
    minimize_down: bool = False
    status: str = "Stopped"
    position: float = 0.0           # seconds
    length: float = 0.0
    thumb: float = 0.0              # 0 (start) to 1 (end)
    scroll_down: str | None = None  # "left" or "right" while held
    trace: np.ndarray | None = None  # one sample per wave-box column, -1 to 1; None: a flat line
    enabled: dict[str, bool] = field(default_factory=lambda: {
        "rewind": False, "forward": False, "play": False, "stop": False, "record": True})
    pressed: str | None = None      # a button held down
    focus: str | None = None        # the button with the keyboard focus


def menu_titles(titles) -> list[tuple[int, int, str, int | None]]:
    """(text x, width, text, underline index) for each menu-bar title."""
    font = system_font()
    out, x = [], MENU_TEXT_X
    for title in titles:
        text, mnemonic = strip_mnemonic(title)
        width = font.measure(text)
        out.append((x, width, text, mnemonic))
        x += width + MENU_GAP
    return out


def title_box(titles, index: int) -> tuple[int, int, int, int]:
    """The highlight behind a menu-bar title: half the gap either side."""
    x, width, _, _ = menu_titles(titles)[index]
    return (x - MENU_GAP // 2, MENU_BAR[1], x + width + MENU_GAP // 2 - 1, MENU_BAR[3])


def strip_mnemonic(label: str) -> tuple[str, int | None]:
    """'E&xit' -> ('Exit', 1); '&&' is a literal ampersand."""
    text, index, i = [], None, 0
    while i < len(label):
        if label[i] == "&" and i + 1 < len(label):
            if label[i + 1] != "&" and index is None:
                index = len(text)
            i += 1
        text.append(label[i])
        i += 1
    return "".join(text), index


def thumb_left(fraction: float) -> int:
    low, high = THUMB_TRAVEL
    return low + round(min(max(fraction, 0.0), 1.0) * (high - low))


def fraction_at(thumb_x: int) -> float:
    """The thumb position (0 to 1) for its left edge line at thumb_x."""
    low, high = THUMB_TRAVEL
    return min(max((thumb_x - low) / (high - low), 0.0), 1.0)


# -- painting -------------------------------------------------------------------

def paint(state: FaceState) -> Surface:
    s = Surface(WIDTH, HEIGHT, GREY)
    s.frame(0, 0, WIDTH - 1, HEIGHT - 1, BLACK)
    _caption(s, state)
    s.hline(0, WIDTH - 1, 19, BLACK)
    _menu_bar(s, state)
    s.hline(0, WIDTH - 1, 38, BLACK)
    _client(s, state)
    return s


def _caption(s: Surface, state: FaceState) -> None:
    x0, y0, x1, y1 = TITLE
    back, ink = (NAVY, WHITE) if state.active else (WHITE, BLACK)
    s.fill(x0, y0, x1, y1, back)
    font = system_font()
    width = font.measure(state.title)
    s.text(font, x0 + (x1 - x0 + 1 - width) // 2, y0 + 1, state.title, ink)
    s.vline(19, 1, 18, BLACK)
    s.vline(297, 1, 18, BLACK)
    # The control-menu box: grey, or inverted while its menu is open.
    bx0, by0, bx1, by1 = CONTROL_BOX
    s.fill(bx0, by0, bx1, by1, GREY)
    s.pattern(bx0 + 2, by0 + 7, CONTROL_MENU_GLYPH)
    if state.control_box_down:
        s.invert(bx0, by0, bx1, by1)
    # The minimize button.
    mx0, my0, mx1, my1 = MINIMIZE
    s.fill(mx0, my0, mx1, my1, GREY)
    if state.minimize_down:
        s.hline(mx0, mx1, my0, DARK)
        s.vline(mx0, my0, my1, DARK)
        s.mask(mx0 + 6, my0 + 8, MINIMIZE_ARROW, BLACK)
    else:
        s.raised(mx0, my0, mx1, my1, light=1, shadow=2)
        s.mask(mx0 + 5, my0 + 7, MINIMIZE_ARROW, BLACK)


def _menu_bar(s: Surface, state: FaceState) -> None:
    x0, y0, x1, y1 = MENU_BAR
    s.fill(x0, y0, x1, y1, WHITE)
    font = system_font()
    for i, (x, width, text, mnemonic) in enumerate(menu_titles(state.menus)):
        ink = BLACK
        if i == state.menu_highlight:
            bx0, by0, bx1, by1 = title_box(state.menus, i)
            s.fill(bx0, by0, bx1, by1, NAVY)
            ink = WHITE
        s.text(font, x, y0, text, ink, underline=mnemonic)


def _centred(s: Surface, font, box, y: int, text: str, ink=BLACK) -> None:
    """Text centred in a box the way 3.1's static controls put it: a pixel left of true."""
    x0, _, x1, _ = box
    s.text(font, x0 + (x1 - x0 + 1 - font.measure(text)) // 2 - 1, y, text, ink)


def _client(s: Surface, state: FaceState) -> None:
    label, bold = sans_serif(8), sans_serif(8, bold=True)

    s.sunken(*STATUS)
    _centred(s, bold, STATUS, STATUS[1] + 3, state.status)

    for box, name, seconds in ((POSITION, "Position:", state.position),
                               (LENGTH, "Length:", state.length)):
        s.sunken(*box)
        _centred(s, label, box, box[1] + 5, name)
        _centred(s, label, box, box[1] + 21, seconds_text(seconds))

    _wave(s, state.trace)
    _scrollbar(s, state)
    for name in BUTTON_NAMES:
        _button(s, name, state)


def _wave(s: Surface, trace) -> None:
    x0, y0, x1, y1 = WAVE
    s.sunken(x0, y0, x1, y1)
    ix0, iy0, ix1, iy1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
    s.fill(ix0, iy0, ix1, iy1, BLACK)
    middle, reach = (iy0 + iy1) // 2, (iy1 - iy0) // 2
    if trace is None or not len(trace):
        s.hline(ix0, ix1, middle, GREEN)
        return
    values = np.clip(np.asarray(trace, np.float64)[:ix1 - ix0 + 1], -1.0, 1.0)
    ys = middle - np.round(values * reach).astype(int)
    previous = ys[0]
    for i, y in enumerate(ys):
        s.vline(ix0 + i, min(previous, y), max(previous, y), GREEN)
        previous = y


def _arrow_button(s: Surface, box, pointing: str, down: bool) -> None:
    x0, y0, x1, y1 = box
    s.fill(x0, y0, x1, y1, GREY)
    shift = 1 if down else 0
    if down:
        s.hline(x0, x1, y0, DARK)
        s.vline(x0, y0, y1, DARK)
    else:
        s.raised(x0, y0, x1, y1, light=1, shadow=2)
    # A triangle of four rows with a three-pixel shaft, 3.1's scroll arrow.
    cx, cy = x0 + 4 + shift, y0 + 4 + shift
    for row in range(7):
        half = 3 - abs(row - 3)
        if pointing == "left":
            s.hline(cx + 3 - half, cx + 3, cy + row, BLACK)
            if 2 <= row <= 4:
                s.hline(cx + 4, cx + 6, cy + row, BLACK)
        else:
            s.hline(cx + 3, cx + 3 + half, cy + row, BLACK)
            if 2 <= row <= 4:
                s.hline(cx, cx + 2, cy + row, BLACK)


def _scrollbar(s: Surface, state: FaceState) -> None:
    x0, y0, x1, y1 = SCROLL
    s.frame(x0, y0, x1, y1, BLACK)
    _arrow_button(s, SCROLL_LEFT, "left", state.scroll_down == "left")
    s.vline(SCROLL_LEFT[2] + 1, y0, y1, BLACK)
    _arrow_button(s, SCROLL_RIGHT, "right", state.scroll_down == "right")
    s.vline(SCROLL_RIGHT[0] - 1, y0, y1, BLACK)
    tx0, ty0, tx1, ty1 = TROUGH
    s.fill(tx0, ty0, tx1, ty1, GREY)
    left = thumb_left(state.thumb)
    s.vline(left, y0, y1, BLACK)
    s.vline(left + 16, y0, y1, BLACK)
    s.fill(left + 1, ty0, left + 15, ty1, GREY)
    s.raised(left + 1, ty0, left + 15, ty1, light=1, shadow=2)


def _button(s: Surface, name: str, state: FaceState) -> None:
    x0, y0, x1, y1 = BUTTONS[name]
    # Black outline with its corners cut, then the bevel inside it.
    s.hline(x0 + 1, x1 - 1, y0, BLACK)
    s.hline(x0 + 1, x1 - 1, y1, BLACK)
    s.vline(x0, y0 + 1, y1 - 1, BLACK)
    s.vline(x1, y0 + 1, y1 - 1, BLACK)
    s.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, GREY)
    down = state.pressed == name
    if down:
        s.hline(x0 + 1, x1 - 1, y0 + 1, DARK)
        s.vline(x0 + 1, y0 + 1, y1 - 1, DARK)
    else:
        s.raised(x0 + 1, y0 + 1, x1 - 1, y1 - 1, light=2, shadow=2, light_wins=True)
    enabled = state.enabled.get(name, False)
    shift = 2 if down else 0
    gx, gy = x0 + 3 + shift, y0 + 3 + shift
    glyph = GLYPHS[name]
    if name == "record" and not enabled:
        # Every pixel of the microphone falls on the same squares of 3.1's
        # grey pattern, so the pattern would leave it unchanged: grey it instead.
        s.mask(gx, gy, glyph, DARK)
    else:
        s.mask(gx, gy, glyph, BLACK, checker=None if enabled else (x0, y0))
    if state.focus == name:
        _focus_rect(s, x0 + 4, y0 + 4, x1 - 4, y1 - 4)


def _focus_rect(s: Surface, x0: int, y0: int, x1: int, y1: int) -> None:
    """3.1's dotted focus rectangle: every other pixel, black."""
    for x in range(x0, x1 + 1, 2):
        s.pixels[y0, x] = BLACK
        s.pixels[y1, x] = BLACK
    for y in range(y0, y1 + 1, 2):
        s.pixels[y, x0] = BLACK
        s.pixels[y, x1] = BLACK


# -- hit testing ----------------------------------------------------------------

def _inside(x: int, y: int, box) -> bool:
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def hit(x: int, y: int, state: FaceState) -> tuple[str, object] | None:
    """What's at (x, y): ("control", None), ("minimize", None), ("caption", None),
    ("menu", index), ("button", name), ("scroll", "left" | "right" | "thumb" |
    "page-left" | "page-right"), or None."""
    if _inside(x, y, CONTROL_BOX):
        return ("control", None)
    if _inside(x, y, MINIMIZE):
        return ("minimize", None)
    if _inside(x, y, TITLE):
        return ("caption", None)
    if _inside(x, y, MENU_BAR):
        for i in range(len(state.menus)):
            if _inside(x, y, title_box(state.menus, i)):
                return ("menu", i)
        return None
    for name, box in BUTTONS.items():
        if _inside(x, y, box):
            return ("button", name)
    if _inside(x, y, SCROLL):
        if x <= SCROLL_LEFT[2]:
            return ("scroll", "left")
        if x >= SCROLL_RIGHT[0]:
            return ("scroll", "right")
        left = thumb_left(state.thumb)
        if left <= x <= left + 16:
            return ("scroll", "thumb")
        return ("scroll", "page-left" if x < left else "page-right")
    return None
