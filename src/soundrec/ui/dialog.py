"""3.1-style message boxes: "Do you want to save...?", errors, About.

A 3.1 dialog has a thick frame (a black line, then four pixels of the active
caption colour), the caption bar, and a white client area; message boxes add
an icon, the text in the System font, and push buttons with a doubled black
border on the default one. Painted like the main window; shown modally in a
borderless window of its own.
"""

from __future__ import annotations

import tkinter as tk

import numpy as np

from .face import CONTROL_MENU_GLYPH, strip_mnemonic
from .fonts import system_font
from .raster import BLACK, DARK, GREY, NAVY, WHITE, Surface
from .window import PixelWindow

FRAME = 5            # black line + four of navy
CAPTION = 18
BUTTON_H = 23
BUTTON_MIN_W = 64
BUTTON_GAP = 16
MARGIN = 16
ICON = 32
WRAP = 320           # widest line of text before it wraps


def wrap(text: str, font, width: int = WRAP) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if line and font.measure(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def icon(kind: str) -> Surface:
    """A round 32 x 32 sign: '?' for questions, '!' for warnings, 'i' for information."""
    s = Surface(ICON, ICON, WHITE)
    ys, xs = np.mgrid[0:ICON, 0:ICON]
    r = np.hypot(xs - 15.5, ys - 15.5)
    s.pixels[r > 15.5] = WHITE
    s.pixels[(r <= 15.5) & (r > 13.5)] = BLACK
    font = system_font()
    mark = {"question": "?", "warning": "!", "info": "i"}.get(kind, "!")
    ink = font.render(mark)
    big = ink.repeat(2, axis=0).repeat(2, axis=1)
    h, w = big.shape
    s.mask((ICON - w) // 2, (ICON - h) // 2 + 1, big, BLACK)
    return s


class MessageBox:
    """Ask, and wait for a button. buttons: (label with '&', answer) pairs;
    the first is the default, `cancel` is what Escape gives."""

    def __init__(self, master: tk.Misc, zoom: int, title: str, text: str,
                 buttons=(("OK", "ok"),), kind: str = "info", cancel: str | None = None):
        self.title, self.kind, self.buttons = title, kind, list(buttons)
        self.cancel = cancel if cancel is not None else self.buttons[-1][1]
        self.answer = self.cancel
        self.focus = 0
        self.pressed: int | None = None
        font = system_font()
        self.lines = wrap(text, font)
        text_w = max(font.measure(line) for line in self.lines)
        text_h = 16 * len(self.lines)
        self.button_w = max([BUTTON_MIN_W] + [font.measure(strip_mnemonic(b[0])[0]) + 20
                                              for b in self.buttons])
        buttons_w = len(self.buttons) * self.button_w + (len(self.buttons) - 1) * BUTTON_GAP
        client_w = max(MARGIN + ICON + MARGIN + text_w + MARGIN, buttons_w + 2 * MARGIN,
                       font.measure(title) + 60)
        body_h = max(ICON, text_h)
        client_h = MARGIN + body_h + MARGIN + BUTTON_H + MARGIN
        self.width = client_w + 2 * FRAME
        self.height = client_h + 2 * FRAME + CAPTION + 1
        self.client = (FRAME, FRAME + CAPTION + 1)
        cx, cy = self.client
        self.icon_at = (cx + MARGIN, cy + MARGIN)
        self.text_at = (cx + MARGIN + ICON + MARGIN, cy + MARGIN + max(0, (ICON - text_h) // 2))
        left = cx + (client_w - buttons_w) // 2
        top = cy + MARGIN + body_h + MARGIN
        self.boxes = [(left + i * (self.button_w + BUTTON_GAP), top,
                       left + i * (self.button_w + BUTTON_GAP) + self.button_w - 1,
                       top + BUTTON_H - 1) for i in range(len(self.buttons))]
        self._master, self._zoom = master, zoom

    # -- painting ---------------------------------------------------------------

    def paint(self) -> Surface:
        s = Surface(self.width, self.height, WHITE)
        s.frame(0, 0, self.width - 1, self.height - 1, BLACK)
        for i in range(1, FRAME):
            s.frame(i, i, self.width - 1 - i, self.height - 1 - i, NAVY)
        # Caption: control-menu box, title, black line under.
        top, x0, x1 = FRAME, FRAME, self.width - 1 - FRAME
        s.fill(x0, top, x1, top + CAPTION - 1, NAVY)
        s.fill(x0, top, x0 + 17, top + CAPTION - 1, GREY)
        s.pattern(x0 + 2, top + 7, CONTROL_MENU_GLYPH)
        s.vline(x0 + 18, top, top + CAPTION - 1, BLACK)
        s.hline(x0, x1, top + CAPTION, BLACK)
        font = system_font()
        area = x1 - (x0 + 19) + 1
        s.text(font, x0 + 19 + (area - font.measure(self.title)) // 2, top + 1, self.title, WHITE)
        s.blit(icon(self.kind), *self.icon_at)
        tx, ty = self.text_at
        for i, line in enumerate(self.lines):
            s.text(font, tx, ty + 16 * i, line, BLACK)
        for i, ((label, _), box) in enumerate(zip(self.buttons, self.boxes)):
            self._button(s, box, label, default=i == 0, focus=i == self.focus,
                         down=i == self.pressed)
        return s

    def _button(self, s: Surface, box, label: str, default: bool, focus: bool, down: bool) -> None:
        x0, y0, x1, y1 = box
        if default:
            s.frame(x0 - 1, y0 - 1, x1 + 1, y1 + 1, BLACK)
            s.pixels[[y0 - 1, y0 - 1, y1 + 1, y1 + 1], [x0 - 1, x1 + 1, x0 - 1, x1 + 1]] = WHITE
        s.hline(x0 + 1, x1 - 1, y0, BLACK)
        s.hline(x0 + 1, x1 - 1, y1, BLACK)
        s.vline(x0, y0 + 1, y1 - 1, BLACK)
        s.vline(x1, y0 + 1, y1 - 1, BLACK)
        s.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, GREY)
        if down:
            s.hline(x0 + 1, x1 - 1, y0 + 1, DARK)
            s.vline(x0 + 1, y0 + 1, y1 - 1, DARK)
        else:
            s.raised(x0 + 1, y0 + 1, x1 - 1, y1 - 1, light=2, shadow=2, light_wins=True)
        font = system_font()
        text, mnemonic = strip_mnemonic(label)
        w = font.measure(text)
        shift = 2 if down else 0
        tx = x0 + (x1 - x0 + 1 - w) // 2 + shift
        ty = y0 + (y1 - y0 + 1 - 16) // 2 + shift
        s.text(font, tx, ty, text, BLACK, underline=mnemonic)
        if focus:
            for x in range(tx - 2, tx + w + 2, 2):
                s.pixels[ty, x] = BLACK
                s.pixels[ty + 15, x] = BLACK
            for y in range(ty, ty + 16, 2):
                s.pixels[y, tx - 2] = BLACK
                s.pixels[y, tx + w + 1] = BLACK

    def button_at(self, x: int, y: int) -> int | None:
        for i, (x0, y0, x1, y1) in enumerate(self.boxes):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def on_caption(self, x: int, y: int) -> bool:
        return FRAME + 18 < x < self.width - FRAME and FRAME <= y < FRAME + CAPTION

    def key(self, keysym: str, char: str) -> bool:
        """A key: True once an answer is chosen."""
        if keysym in ("Return", "KP_Enter", "space"):
            self.answer = self.buttons[self.focus][1]
            return True
        if keysym == "Escape":
            self.answer = self.cancel
            return True
        if keysym in ("Tab", "Right", "Down"):
            self.focus = (self.focus + 1) % len(self.buttons)
        elif keysym in ("ISO_Left_Tab", "Left", "Up"):
            self.focus = (self.focus - 1) % len(self.buttons)
        elif char:
            for label, answer in self.buttons:
                text, index = strip_mnemonic(label)
                if index is not None and text[index].lower() == char.lower():
                    self.answer = answer
                    return True
        return False

    # -- showing -----------------------------------------------------------------

    def run(self, centre_on: tuple[int, int, int, int] | None = None) -> str:
        """Show it, wait for an answer, return it. centre_on: (x, y, w, h) on screen."""
        top = tk.Toplevel(self._master)
        window = PixelWindow(top, self._zoom)
        z = self._zoom
        if centre_on is None:
            sx, sy, sw, sh = 0, 0, top.winfo_screenwidth(), top.winfo_screenheight()
        else:
            sx, sy, sw, sh = centre_on
        x = sx + (sw - self.width * z) // 2
        y = sy + (sh - self.height * z) // 2
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        grab = []  # where the caption was grabbed, while it's dragged

        def redraw():
            window.show(self.paint())

        def press(e):
            x, y = e.x // z, e.y // z
            i = self.button_at(x, y)
            if i is not None:
                self.pressed = self.focus = i
                redraw()
            elif self.on_caption(x, y):
                grab[:] = [e.x_root - top.winfo_rootx(), e.y_root - top.winfo_rooty()]

        def motion(e):
            if grab:
                window.move_to(e.x_root - grab[0], e.y_root - grab[1])
            elif self.pressed is not None:
                i = self.button_at(e.x // z, e.y // z)
                down = self.focus if i == self.focus else None
                if down != self.pressed:
                    self.pressed = down
                    redraw()

        def release(e):
            grab.clear()
            was, self.pressed = self.pressed, None
            if was is not None and self.button_at(e.x // z, e.y // z) == was:
                self.answer = self.buttons[was][1]
                top.destroy()
            else:
                redraw()

        def key(e):
            if self.key(e.keysym, e.char):
                top.destroy()
            else:
                redraw()
            return "break"

        window.label.bind("<ButtonPress-1>", press)
        window.label.bind("<B1-Motion>", motion)
        window.label.bind("<ButtonRelease-1>", release)
        top.bind("<KeyPress>", key)
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        redraw()
        top.attributes("-topmost", True)
        top.focus_force()
        top.grab_set()
        top.wait_window()
        return self.answer
