"""The 3.1 controls the dialogs need beyond push buttons: a list box and a
one-line edit box.

Pure logic and pixels, like the Tracker: a dialog hands them dialog coordinates
and keys, and asks them to paint themselves on a Surface, so they can be driven
and looked at in tests with no window. The look is 3.1's: a one-pixel black
frame, white inside, the System font, and navy behind what's selected. A list
box has a scrollbar only when the rows don't fit, drawn as the main window's is.
"""

from __future__ import annotations

from .face import strip_mnemonic
from .fonts import system_font
from .raster import BLACK, DARK, GREY, NAVY, WHITE, Surface

ROW = 16          # the System font's height
LABEL_HEIGHT = 17  # a label above a list box
TEXT_INSET = 3    # from the frame to the text
SCROLL_WIDTH = 16  # the scrollbar's column, its dividing line included
ARROW_SIZE = 15   # a scroll arrow's button, square
THUMB_SIZE = 15
PAGE_OVERLAP = 1  # rows kept on screen when paging
EDIT_HEIGHT = ROW + 6
EDIT_LIMIT = 255  # characters: plenty for a line, and far short of the 4,300 digits int() refuses
CTRL_A = "\x01"   # what Ctrl+A types


def height_for(rows: int) -> int:
    """The height of a list box showing `rows` rows, frame included."""
    return rows * ROW + 2


def arrow_button(s: Surface, box, pointing: str, down: bool) -> None:
    """A vertical scroll arrow: the main window's, turned on its side."""
    x0, y0, x1, y1 = box
    s.fill(x0, y0, x1, y1, GREY)
    shift = 1 if down else 0
    if down:
        s.hline(x0, x1, y0, DARK)
        s.vline(x0, y0, y1, DARK)
    else:
        s.raised(x0, y0, x1, y1, light=1, shadow=2)
    cx, cy = x0 + 4 + shift, y0 + 4 + shift
    for column in range(7):
        half = 3 - abs(column - 3)
        if pointing == "up":
            s.vline(cx + column, cy + 3 - half, cy + 3, BLACK)
            if 2 <= column <= 4:
                s.vline(cx + column, cy + 4, cy + 6, BLACK)
        else:
            s.vline(cx + column, cy + 3, cy + 3 + half, BLACK)
            if 2 <= column <= 4:
                s.vline(cx + column, cy, cy + 2, BLACK)


class ListBox:
    def __init__(self, box: tuple[int, int, int, int], label: str = ""):
        self.box, self.label = box, label
        self.rows: list[str] = []
        self.greyed: set[int] = set()   # shown but can't be chosen
        self.selected: int | None = None
        self.top = 0                    # the first row showing
        self.enabled = True
        self.held: str | None = None    # "up", "down", "page-up", "page-down", or "thumb"
        self._grab = 0                  # where on the thumb it was grabbed

    # -- what's in it ---------------------------------------------------------

    def fill(self, rows, selected: int | None = 0, greyed=()) -> None:
        self.rows, self.greyed = list(rows), set(greyed)
        self.top = 0
        self.selected = None
        if selected is not None and self.rows:
            self.select(selected if selected not in self.greyed else self._step(selected, 1))

    def select(self, index: int | None) -> bool:
        """Select a row and bring it into view; True if the selection moved."""
        moved = index != self.selected
        self.selected = index
        if index is not None:
            if index < self.top:
                self.top = index
            elif index >= self.top + self.visible:
                self.top = index - self.visible + 1
        return moved

    # -- shape ----------------------------------------------------------------

    @property
    def visible(self) -> int:
        return (self.box[3] - self.box[1] - 1) // ROW

    @property
    def scrolls(self) -> bool:
        return len(self.rows) > self.visible

    @property
    def last_top(self) -> int:
        return max(len(self.rows) - self.visible, 0)

    @property
    def text_right(self) -> int:
        return self.box[2] - 1 - (SCROLL_WIDTH if self.scrolls else 0)

    @property
    def _trough(self) -> tuple[int, int]:
        y0, y1 = self.box[1], self.box[3]
        return y0 + ARROW_SIZE + 2, y1 - ARROW_SIZE - 2

    @property
    def thumb_y(self) -> int:
        """The top of the thumb, its upper black line."""
        top, bottom = self._trough
        travel = bottom - top + 1 - (THUMB_SIZE + 2)
        return top + (round(self.top * travel / self.last_top) if self.last_top else 0)

    def contains(self, x: int, y: int) -> bool:
        x0, y0, x1, y1 = self.box
        return x0 <= x <= x1 and y0 <= y <= y1

    def hit(self, x: int, y: int):
        """What's at a point: a row number, or a part of the scrollbar, or None."""
        if not self.contains(x, y):
            return None
        x0, y0, x1, y1 = self.box
        if self.scrolls and x > self.text_right:
            if y <= y0 + ARROW_SIZE:
                return "up"
            if y >= y1 - ARROW_SIZE:
                return "down"
            thumb = self.thumb_y
            if y < thumb:
                return "page-up"
            return "thumb" if y <= thumb + THUMB_SIZE + 1 else "page-down"
        row = self.top + (y - y0 - 1) // ROW
        return row if y0 < y < y1 and 0 <= row < len(self.rows) else None

    # -- moving about -----------------------------------------------------------

    def _step(self, start: int, step: int) -> int | None:
        i = start
        while 0 <= i < len(self.rows):
            if i not in self.greyed:
                return i
            i += step
        return None

    def _go(self, index: int, step: int) -> bool:
        index = min(max(index, 0), len(self.rows) - 1)
        target = self._step(index, step)
        if target is None:
            target = self._step(index, -step)
        return False if target is None else self.select(target)

    def key(self, keysym: str, char: str = "") -> bool:
        """A key; True if the selection moved."""
        if not self.rows or not self.enabled:
            return False
        at = self.selected if self.selected is not None else -1
        page = max(self.visible - PAGE_OVERLAP, 1)
        if keysym == "Down":
            return self._go(at + 1, 1)
        if keysym == "Up":
            return self._go(max(at, 0) - 1, -1)
        if keysym == "Next":
            return self._go(at + page, 1)
        if keysym == "Prior":
            return self._go(max(at, 0) - page, -1)
        if keysym == "Home":
            return self._go(0, 1)
        if keysym == "End":
            return self._go(len(self.rows) - 1, -1)
        if char and char.isprintable() and char != " ":
            for i in range(1, len(self.rows) + 1):  # the next row starting with it
                row = (at + i) % len(self.rows)
                if row not in self.greyed and self.rows[row][:1].lower() == char.lower():
                    return self.select(row)
        return False

    def scroll(self, rows: int) -> None:
        self.top = min(max(self.top + rows, 0), self.last_top)

    def press(self, x: int, y: int) -> bool:
        """The mouse went down; True if the selection moved."""
        what = self.hit(x, y)
        if isinstance(what, int):
            return what not in self.greyed and self.select(what)
        self.held = what
        if what == "thumb":
            self._grab = y - self.thumb_y
        else:
            self.repeat()
        return False

    def repeat(self) -> bool:
        """The scrollbar's arrow or trough still held: move again."""
        step = {"up": -1, "down": 1, "page-up": -self.visible, "page-down": self.visible}.get(self.held)
        if step is None:
            return False
        before = self.top
        self.scroll(step)
        return self.top != before

    def drag(self, y: int) -> bool:
        """The mouse moved with the thumb held; True if the rows moved."""
        if self.held != "thumb" or not self.last_top:
            return False
        top, bottom = self._trough
        travel = bottom - top + 1 - (THUMB_SIZE + 2)
        wanted = round((y - self._grab - top) * self.last_top / travel) if travel > 0 else 0
        before = self.top
        self.top = min(max(wanted, 0), self.last_top)
        return self.top != before

    def release(self) -> None:
        self.held = None

    def double(self, x: int, y: int) -> bool:
        """A double-click: True if it landed on a row, which means OK too."""
        return isinstance(self.hit(x, y), int)

    def blink(self) -> bool:
        """A list has no caret."""
        return False

    # -- pixels -------------------------------------------------------------------

    def paint(self, s: Surface, focused: bool) -> None:
        font = system_font()
        x0, y0, x1, y1 = self.box
        if self.label:
            text, mnemonic = strip_mnemonic(self.label)
            s.text(font, x0, y0 - LABEL_HEIGHT, text, BLACK if self.enabled else GREY,
                   underline=mnemonic)
        s.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, WHITE)
        s.frame(x0, y0, x1, y1, BLACK)
        right = self.text_right
        for row in range(self.top, min(self.top + self.visible, len(self.rows))):
            y = y0 + 1 + (row - self.top) * ROW
            lit = row == self.selected and self.enabled
            if lit:
                s.fill(x0 + 1, y, right, y + ROW - 1, NAVY)
            ink = BLACK if self.enabled and row not in self.greyed else GREY
            if lit:
                ink = WHITE
            s.mask(x0 + TEXT_INSET, y, font.render(self.rows[row])[:, :right - x0 - TEXT_INSET], ink)
            if lit and focused:
                for x in range(x0 + 1, right + 1, 2):
                    s.pixels[y, x] = WHITE
                    s.pixels[y + ROW - 1, x] = WHITE
                for yy in range(y, y + ROW, 2):
                    s.pixels[yy, x0 + 1] = WHITE
                    s.pixels[yy, right] = WHITE
        if self.scrolls:
            self._paint_scrollbar(s)

    def _paint_scrollbar(self, s: Surface) -> None:
        x0, y0, x1, y1 = self.box
        left = x1 - SCROLL_WIDTH
        s.vline(left, y0, y1, BLACK)
        arrow_button(s, (left + 1, y0 + 1, x1 - 1, y0 + ARROW_SIZE), "up", self.held == "up")
        s.hline(left, x1, y0 + ARROW_SIZE + 1, BLACK)
        arrow_button(s, (left + 1, y1 - ARROW_SIZE, x1 - 1, y1 - 1), "down", self.held == "down")
        s.hline(left, x1, y1 - ARROW_SIZE - 1, BLACK)
        top, bottom = self._trough
        s.fill(left + 1, top, x1 - 1, bottom, GREY)
        thumb = self.thumb_y
        s.hline(left, x1, thumb, BLACK)
        s.hline(left, x1, thumb + THUMB_SIZE + 1, BLACK)
        s.fill(left + 1, thumb + 1, x1 - 1, thumb + THUMB_SIZE, GREY)
        s.raised(left + 1, thumb + 1, x1 - 1, thumb + THUMB_SIZE, light=1, shadow=2)


class EditBox:
    """A one-line edit box. It stands in a Dialog's `lists`, ahead of the
    buttons, so a dialog talks to it as it does to a ListBox: keys, press, the
    drag (`hit` then `select`), release, double, paint. `caret` is the gap the
    caret is in, counted in characters, and the selection runs from `anchor`
    to there, so the two are equal when nothing's selected. A new one has all
    its text selected, so typing replaces it."""

    label = ""            # a box's prompt is the dialog's to draw
    greyed = ()
    held = None           # no scrollbar to hold
    enabled = True

    def __init__(self, box: tuple[int, int, int, int], text: str = "", limit: int = EDIT_LIMIT):
        self.box, self.limit = box, limit
        self.text = text[:limit]
        self.left = 0         # the first character showing
        self.caret_on = True  # the blink's state
        self.select_all()

    # -- what's in it ---------------------------------------------------------

    @property
    def selection(self) -> tuple[int, int]:
        return min(self.caret, self.anchor), max(self.caret, self.anchor)

    @property
    def selected_text(self) -> str:
        start, end = self.selection
        return self.text[start:end]

    def select_all(self) -> None:
        self.anchor, self.caret = 0, len(self.text)
        self._moved()

    def insert(self, text: str) -> None:
        """`text` in place of the selection, as much of it as the limit lets in."""
        start, end = self.selection
        text = text[:max(self.limit - len(self.text) + end - start, 0)]
        self.text = self.text[:start] + text + self.text[end:]
        self.caret = self.anchor = start + len(text)
        self._moved()

    def paste(self, text: str) -> None:
        """Clipboard text: its first line, without anything unprintable."""
        line = text.splitlines()[0] if text else ""
        self.insert("".join(c for c in line if c.isprintable()))

    # -- shape ----------------------------------------------------------------

    @property
    def room(self) -> int:
        """The width the text can show in."""
        return self.box[2] - self.box[0] + 1 - 2 * TEXT_INSET

    def _moved(self) -> None:
        """The caret went somewhere: light it, and slide the text so that it's
        in view with no empty room to the right that text could fill."""
        self.caret_on = True
        font = system_font()
        self.left = min(self.left, self.caret)
        while font.measure(self.text[self.left:self.caret]) > self.room:
            self.left += 1
        while self.left and font.measure(self.text[self.left - 1:]) <= self.room:
            self.left -= 1

    def contains(self, x: int, y: int) -> bool:
        x0, y0, x1, y1 = self.box
        return x0 <= x <= x1 and y0 <= y <= y1

    def hit(self, x: int, y: int) -> int:
        """The gap nearest a point, at any height: a drag can leave the box."""
        x -= self.box[0] + TEXT_INSET
        font = system_font()
        for i, (left, width) in enumerate(font.offsets(self.text[self.left:])):
            if x < left + (width + 1) // 2:
                return self.left + i
        return len(self.text)

    # -- keys and the mouse -----------------------------------------------------

    def _go(self, index: int) -> None:
        self.caret = self.anchor = min(max(index, 0), len(self.text))
        self._moved()

    def key(self, keysym: str, char: str = "") -> bool:
        """A key; True if it moved or changed anything."""
        before = self.text, self.caret, self.anchor
        start, end = self.selection
        if keysym == "Left":
            self._go(self.caret - 1 if start == end else start)
        elif keysym == "Right":
            self._go(self.caret + 1 if start == end else end)
        elif keysym == "Home":
            self._go(0)
        elif keysym == "End":
            self._go(len(self.text))
        elif keysym == "BackSpace":
            if start == end:
                self.anchor = max(start - 1, 0)
            self.insert("")
        elif keysym == "Delete":
            if start == end:
                self.anchor = min(end + 1, len(self.text))
            self.insert("")
        elif char == CTRL_A:
            self.select_all()
        elif char and char.isprintable():
            self.insert(char)
        return (self.text, self.caret, self.anchor) != before

    def press(self, x: int, y: int) -> bool:
        """The mouse went down: the caret goes there, selecting nothing."""
        self._go(self.hit(x, y))
        return False

    def select(self, index: int) -> bool:
        """The mouse dragged to this gap: select from the press to here."""
        moved = index != self.caret
        self.caret = index
        self._moved()
        return moved

    def double(self, x: int, y: int) -> bool:
        """A double-click takes the word under it. Unlike on a list, it isn't OK."""
        start = end = self.hit(x, y)
        while start and not self.text[start - 1].isspace():
            start -= 1
        while end < len(self.text) and not self.text[end].isspace():
            end += 1
        self.anchor, self.caret = start, end
        self._moved()
        return False

    def release(self) -> None:
        pass

    def scroll(self, rows: int) -> None:
        """The wheel: one line has nowhere to go."""

    def blink(self) -> bool:
        """The caret's half second is up; True if that changes what's showing."""
        self.caret_on = not self.caret_on
        return self.caret == self.anchor

    # -- pixels -------------------------------------------------------------------

    def paint(self, s: Surface, focused: bool) -> None:
        font = system_font()
        x0, y0, x1, y1 = self.box
        s.fill(x0 + 1, y0 + 1, x1 - 1, y1 - 1, WHITE)
        s.frame(x0, y0, x1, y1, BLACK)
        tx, ty = x0 + TEXT_INSET, y0 + (y1 - y0 + 1 - ROW) // 2
        ink = font.render(self.text[self.left:])[:, :self.room]
        s.mask(tx, ty, ink, BLACK)
        if not focused:  # 3.1 shows neither the caret nor the selection then
            return
        start, end = self.selection
        if start == end:
            if self.caret_on:
                x = tx + font.measure(self.text[self.left:self.caret])
                s.vline(x, ty, ty + ROW - 1, BLACK)
            return
        a = font.measure(self.text[self.left:max(start, self.left)])
        b = min(font.measure(self.text[self.left:end]), ink.shape[1])
        s.fill(tx + a, ty, tx + b - 1, ty + ROW - 1, NAVY)
        s.mask(tx + a, ty, ink[:, a:b], WHITE)
