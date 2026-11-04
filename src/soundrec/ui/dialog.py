"""3.1-style dialogs: message boxes, and the base the Device dialogs stand on.

A 3.1 dialog has a thick frame (a black line, then four pixels of the active
caption colour), the caption bar, and a white client area, with push buttons
that have a doubled black border on the default one. Message boxes add an
icon and text in the System font. Painted like the main window; shown modally
in a borderless window of its own.

Everything but Dialog.run is pure logic and pixels: press, motion, release,
key and paint take dialog coordinates and need no window, so the dialogs are
driven in tests just as the Tracker is.
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
REPEAT_DELAY_MS, REPEAT_MS = 400, 60  # a held scroll arrow, as on the main window


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


class Dialog:
    """A modal dialog: its frame, push buttons, list boxes and focus.

    buttons: (label with '&', answer) pairs, the first the default; `cancel`
    is what Escape gives. `boxes` is each button's rectangle, `lists` its
    ListBoxes in Tab order, ahead of the buttons. A subclass lays those out,
    paints the rest in paint_client, and hears of a list changing in changed.
    """

    def __init__(self, master: tk.Misc | None, zoom: int, title: str, client_w: int, client_h: int,
                 buttons=(), cancel: str | None = None):
        self._master, self._zoom, self.title = master, zoom, title
        self.buttons = list(buttons)
        self.cancel = cancel if cancel is not None else self.buttons[-1][1]
        self.answer = self.cancel
        self.width = client_w + 2 * FRAME
        self.height = client_h + 2 * FRAME + CAPTION + 1
        self.client = (FRAME, FRAME + CAPTION + 1)
        self.boxes: list[tuple[int, int, int, int]] = []
        self.lists: list = []
        self.dead: set[int] = set()         # buttons greyed
        self.focus = 0                      # an index into lists + buttons
        self.pressed: int | None = None     # the button drawn down
        self.down_on: int | None = None     # the button the mouse went down on
        self.held = None                    # the list the mouse went down on
        self._top = None
        self._window = None

    # -- focus --------------------------------------------------------------------

    @property
    def focused_list(self):
        return self.lists[self.focus] if self.focus < len(self.lists) else None

    @property
    def focused_button(self) -> int | None:
        return None if self.focus < len(self.lists) else self.focus - len(self.lists)

    def _can_focus(self, index: int) -> bool:
        if index < len(self.lists):
            return self.lists[index].enabled
        return index - len(self.lists) not in self.dead

    def _move_focus(self, step: int) -> None:
        count = len(self.lists) + len(self.buttons)
        for i in range(1, count + 1):
            index = (self.focus + step * i) % count
            if self._can_focus(index):
                self.focus = index
                return

    # -- what a subclass does -------------------------------------------------------

    def paint_client(self, s: Surface) -> None:
        pass

    def changed(self, box) -> None:
        """A list's selection moved."""

    def clicked(self, button: int) -> bool:
        """A button was pressed: True if that's the answer."""
        self.answer = self.buttons[button][1]
        return True

    # -- input ----------------------------------------------------------------------

    def button_at(self, x: int, y: int) -> int | None:
        for i, (x0, y0, x1, y1) in enumerate(self.boxes):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def on_caption(self, x: int, y: int) -> bool:
        return FRAME + 18 < x < self.width - FRAME and FRAME <= y < FRAME + CAPTION

    def _push(self, button: int) -> bool:
        return False if button in self.dead else self.clicked(button)

    def key(self, keysym: str, char: str = "", alt: bool = False) -> bool:
        """A key: True once an answer is chosen. Alt+letter reaches any list or
        button by its mnemonic; a plain letter only a button, unless a list
        has the focus, where it finds a row."""
        if keysym == "Escape":
            self.answer = self.cancel
            return True
        if keysym in ("Return", "KP_Enter"):
            focused = self.focused_button
            return self._push(0 if focused is None else focused)
        if keysym == "Tab":
            self._move_focus(1)
            return False
        if keysym == "ISO_Left_Tab":
            self._move_focus(-1)
            return False
        if alt:
            return self._mnemonic(char, lists=True)
        box = self.focused_list
        if box is not None:
            if box.key(keysym, char):
                self.changed(box)
            return False
        if keysym == "space":
            return self._push(self.focused_button)
        if keysym in ("Right", "Down"):
            self._move_focus(1)
        elif keysym in ("Left", "Up"):
            self._move_focus(-1)
        elif char:
            return self._mnemonic(char, lists=False)
        return False

    def _mnemonic(self, char: str, lists: bool) -> bool:
        if not char:
            return False
        if lists:
            for i, box in enumerate(self.lists):
                text, index = strip_mnemonic(box.label)
                if box.enabled and index is not None and text[index].lower() == char.lower():
                    self.focus = i
                    return False
        for i, (label, _) in enumerate(self.buttons):
            text, index = strip_mnemonic(label)
            if index is not None and text[index].lower() == char.lower():
                if self._push(i):
                    return True
                if i not in self.dead:  # a button that doesn't close the dialog keeps the focus
                    self.focus = len(self.lists) + i
                return False
        return False

    def press(self, x: int, y: int) -> None:
        i = self.button_at(x, y)
        if i is not None:
            if i not in self.dead:
                self.pressed = self.down_on = i
                self.focus = len(self.lists) + i
            return
        for n, box in enumerate(self.lists):
            if box.enabled and box.contains(x, y):
                self.focus = n
                self.held = box
                if box.press(x, y):
                    self.changed(box)
                return

    def motion(self, x: int, y: int) -> bool:
        """The mouse moved with its button down: True if that changed anything."""
        if self.held is not None:
            box = self.held
            if box.held == "thumb":
                return box.drag(y)
            what = box.hit(x, y)
            if box.held is None and isinstance(what, int) and what not in box.greyed:
                if box.select(what):
                    self.changed(box)
                    return True
            return False
        if self.down_on is not None:
            down = self.down_on if self.button_at(x, y) == self.down_on else None
            if down != self.pressed:
                self.pressed = down
                return True
        return False

    def release(self, x: int, y: int) -> bool:
        """The mouse came up: True once an answer is chosen."""
        if self.held is not None:
            self.held.release()
            self.held = None
            return False
        was, self.down_on, self.pressed = self.down_on, None, None
        return was is not None and self.button_at(x, y) == was and self._push(was)

    def double(self, x: int, y: int) -> bool:
        """A double-click on a row means that row, and OK."""
        for box in self.lists:
            if box.enabled and isinstance(box.hit(x, y), int):
                return self._push(0)
        return False

    def wheel(self, x: int, y: int, notches: int) -> None:
        box = next((b for b in self.lists if b.enabled and b.contains(x, y)), self.focused_list)
        if box is not None:
            box.scroll(-3 * notches)

    # -- painting -------------------------------------------------------------------

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
        self.paint_client(s)
        for i, box in enumerate(self.lists):
            box.paint(s, i == self.focus)
        focused = self.focused_button
        default = 0 if focused is None else focused
        for i, ((label, _), box) in enumerate(zip(self.buttons, self.boxes)):
            self._button(s, box, label, default=i == default, focus=i == focused,
                         down=i == self.pressed, enabled=i not in self.dead)
        return s

    def _button(self, s: Surface, box, label: str, default: bool, focus: bool, down: bool,
                enabled: bool = True) -> None:
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
        s.text(font, tx, ty, text, BLACK if enabled else DARK, underline=mnemonic)
        if focus:
            for x in range(tx - 2, tx + w + 2, 2):
                s.pixels[ty, x] = BLACK
                s.pixels[ty + 15, x] = BLACK
            for y in range(ty, ty + 16, 2):
                s.pixels[y, tx - 2] = BLACK
                s.pixels[y, tx + w + 1] = BLACK

    # -- showing -----------------------------------------------------------------

    def refresh(self) -> None:
        """Repaint, from outside the dialog's own events: a result arriving."""
        if self._window is not None:
            self._window.show(self.paint())

    def message(self, text: str, buttons=(("OK", "ok"),), kind: str = "info") -> str:
        """A message box on top of this dialog, which keeps the input after it."""
        top = self._top
        box = MessageBox(top, self._zoom, self.title, text, buttons, kind=kind)
        answer = box.run((top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()))
        top.grab_set()
        top.focus_force()
        return answer

    def run(self, centre_on: tuple[int, int, int, int] | None = None) -> str:
        """Show it, wait for an answer, return it. centre_on: (x, y, w, h) on screen."""
        top = self._top = tk.Toplevel(self._master)
        window = self._window = PixelWindow(top, self._zoom)
        z = self._zoom
        if centre_on is None:
            sx, sy, sw, sh = 0, 0, top.winfo_screenwidth(), top.winfo_screenheight()
        else:
            sx, sy, sw, sh = centre_on
        x = min(sx + (sw - self.width * z) // 2, top.winfo_screenwidth() - self.width * z)
        y = min(sy + (sh - self.height * z) // 2, top.winfo_screenheight() - self.height * z)
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        grab = []  # where the caption was grabbed, while it's dragged
        repeating = []

        def redraw():
            window.show(self.paint())

        def here(e):
            return (e.x_root - top.winfo_rootx()) // z, (e.y_root - top.winfo_rooty()) // z

        def repeat():
            repeating.clear()
            box = self.held
            if box is not None and box.held not in (None, "thumb") and box.repeat():
                redraw()
                repeating.append(top.after(REPEAT_MS, repeat))

        def press(e):
            x, y = here(e)
            if self.button_at(x, y) is None and self.on_caption(x, y):
                grab[:] = [e.x_root - top.winfo_rootx(), e.y_root - top.winfo_rooty()]
                return
            self.press(x, y)
            redraw()
            if self.held is not None and self.held.held not in (None, "thumb"):
                repeating.append(top.after(REPEAT_DELAY_MS, repeat))

        def motion(e):
            if grab:
                window.move_to(e.x_root - grab[0], e.y_root - grab[1])
            elif self.motion(*here(e)):
                redraw()

        def release(e):
            grab.clear()
            while repeating:
                top.after_cancel(repeating.pop())
            if self.release(*here(e)):
                top.destroy()
            else:
                redraw()

        def double(e):
            if self.double(*here(e)):
                top.destroy()
            else:
                redraw()

        def key(e):
            keysym = "ISO_Left_Tab" if e.keysym == "Tab" and e.state & 1 else e.keysym
            if self.key(keysym, e.char, alt=bool(e.state & 0x20000)):
                top.destroy()
            else:
                redraw()
            return "break"

        def wheel(e):
            self.wheel(*here(e), round(e.delta / 120))
            redraw()

        window.label.bind("<ButtonPress-1>", press)
        window.label.bind("<B1-Motion>", motion)
        window.label.bind("<ButtonRelease-1>", release)
        window.label.bind("<Double-Button-1>", double)
        top.bind("<KeyPress>", key)
        top.bind("<MouseWheel>", wheel)
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        redraw()
        top.attributes("-topmost", True)
        top.focus_force()
        top.grab_set()
        top.wait_window()
        self._top = self._window = None
        try:  # back to the window that asked, not whatever Windows picks next
            self._master.focus_force()
        except tk.TclError:
            pass
        return self.answer


class MessageBox(Dialog):
    """Ask, and wait for a button. buttons: (label with '&', answer) pairs;
    the first is the default, `cancel` is what Escape gives."""

    def __init__(self, master: tk.Misc | None, zoom: int, title: str, text: str,
                 buttons=(("OK", "ok"),), kind: str = "info", cancel: str | None = None):
        self.kind = kind
        font = system_font()
        self.lines = wrap(text, font)
        text_w = max(font.measure(line) for line in self.lines)
        text_h = 16 * len(self.lines)
        buttons = list(buttons)
        self.button_w = max([BUTTON_MIN_W] + [font.measure(strip_mnemonic(b[0])[0]) + 20
                                              for b in buttons])
        buttons_w = len(buttons) * self.button_w + (len(buttons) - 1) * BUTTON_GAP
        client_w = max(MARGIN + ICON + MARGIN + text_w + MARGIN, buttons_w + 2 * MARGIN,
                       font.measure(title) + 60)
        body_h = max(ICON, text_h)
        client_h = MARGIN + body_h + MARGIN + BUTTON_H + MARGIN
        super().__init__(master, zoom, title, client_w, client_h, buttons, cancel)
        cx, cy = self.client
        self.icon_at = (cx + MARGIN, cy + MARGIN)
        self.text_at = (cx + MARGIN + ICON + MARGIN, cy + MARGIN + max(0, (ICON - text_h) // 2))
        left = cx + (client_w - buttons_w) // 2
        top = cy + MARGIN + body_h + MARGIN
        self.boxes = [(left + i * (self.button_w + BUTTON_GAP), top,
                       left + i * (self.button_w + BUTTON_GAP) + self.button_w - 1,
                       top + BUTTON_H - 1) for i in range(len(self.buttons))]

    def paint_client(self, s: Surface) -> None:
        font = system_font()
        s.blit(icon(self.kind), *self.icon_at)
        tx, ty = self.text_at
        for i, line in enumerate(self.lines):
            s.text(font, tx, ty + 16 * i, line, BLACK)
