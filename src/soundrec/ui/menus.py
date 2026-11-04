"""Menus as Windows 3.1 drew and drove them, without Tk.

Windows 11 draws Tk's native menus in its own style, so these are ours: the
titles live in the window's menu bar (face.py draws them), and an open menu
is a white popup with a black border, 18-pixel items with the text at the
top, and 7-pixel separators, measured from a 3.1 screenshot. No shadow:
3.1's menus had none. An item can open a cascade, a second popup beside it,
marked with a right-pointing arrow; one level is all this window needs.

The Tracker follows 3.1's rules. Mouse: press a title to open its menu,
drag to an item and let go to choose it, or click and then click again;
clicking the open menu's title again closes it. Keyboard: Alt or F10 lights
the first title, the arrows move, Enter or a mnemonic opens and chooses,
Escape backs out a step; Alt+letter opens a menu straight away, Alt+Space
the control menu, which sits left of File. Cascades open as soon as the
pointer rests on their item, or by click, Enter, the Right arrow or the
mnemonic; Left and Escape close them, and Right from inside one moves on to
the next menu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .face import strip_mnemonic
from .fonts import system_font
from .raster import BLACK, GREY, NAVY, WHITE, Surface

ITEM_HEIGHT = 18
SEPARATOR_HEIGHT = 7
TEXT_X = 16       # from the popup's left edge, border included
ACCEL_GAP = 8     # between the widest label and the accelerator column
RIGHT_MARGIN = 15  # after the widest text, border included
CHECK_X, CHECK_Y = 4, 5  # the tick's top-left, from the item's
ARROW_RIGHT = 10   # the cascade arrow's left edge, in from the popup's right edge
ARROW_Y = 5        # its top, from the item's
CASCADE_OVERLAP = 3  # a cascade's left edge sits this far inside its parent's right edge
CHECK = np.array([[c == "#" for c in row] for row in (
    "......#",
    ".....##",
    "#...###",
    "##.###.",
    "#####..",
    ".###...",
    "..#....")])
ARROW = np.array([[c == "#" for c in row] for row in (
    "#...",
    "##..",
    "###.",
    "####",
    "###.",
    "##..",
    "#...")])


@dataclass
class Item:
    label: str                  # '&' marks the mnemonic
    command: str | None = None  # None makes a separator
    accel: str = ""             # shown, not bound: the app binds its own keys
    enabled: bool = True
    checked: bool = False       # a tick in the left margin
    submenu: Menu | None = None  # a cascade: choosing the item opens it

    @property
    def separator(self) -> bool:
        return self.command is None

    @property
    def mnemonic(self) -> str | None:
        text, index = strip_mnemonic(self.label)
        return None if index is None else text[index].lower()


SEPARATOR = Item("")


@dataclass
class Menu:
    title: str | None           # None: the control menu, which has no title in the bar
    items: list[Item] = field(default_factory=list)

    @property
    def mnemonic(self) -> str | None:
        if self.title is None:
            return None
        text, index = strip_mnemonic(self.title)
        return None if index is None else text[index].lower()

    def item(self, command: str) -> Item:
        for item in self.items:
            if item.command == command:
                return item
        raise KeyError(command)


# -- drawing ----------------------------------------------------------------------

def layout(menu: Menu) -> tuple[int, int, list[int]]:
    """(width, height, top of each item) of the popup, border included."""
    font = system_font()
    labels = [font.measure(strip_mnemonic(i.label)[0]) for i in menu.items if not i.separator]
    accels = [font.measure(i.accel) for i in menu.items if i.accel]
    width = TEXT_X + max(labels, default=0) + RIGHT_MARGIN
    if accels:
        width += ACCEL_GAP + max(accels)
    tops, y = [], 1
    for item in menu.items:
        tops.append(y)
        y += SEPARATOR_HEIGHT if item.separator else ITEM_HEIGHT
    return width, y + 1, tops


def paint_popup(menu: Menu, highlight: int | None = None) -> Surface:
    font = system_font()
    width, height, tops = layout(menu)
    labels = [font.measure(strip_mnemonic(i.label)[0]) for i in menu.items if not i.separator]
    accel_x = TEXT_X + max(labels, default=0) + ACCEL_GAP
    s = Surface(width, height, WHITE)
    s.frame(0, 0, width - 1, height - 1, BLACK)
    for i, (item, top) in enumerate(zip(menu.items, tops)):
        if item.separator:
            s.hline(0, width - 1, top + SEPARATOR_HEIGHT // 2, BLACK)
            continue
        ink = BLACK if item.enabled else GREY
        if i == highlight:
            s.fill(1, top, width - 2, top + ITEM_HEIGHT - 1, NAVY)
            ink = WHITE if item.enabled else GREY
        if item.checked:
            s.mask(CHECK_X, top + CHECK_Y, CHECK, ink)
        text, mnemonic = strip_mnemonic(item.label)
        s.text(font, TEXT_X, top, text, ink, underline=mnemonic, underline_shift=-1)
        if item.accel:
            s.text(font, accel_x, top, item.accel, ink)
        if item.submenu is not None:
            s.mask(width - ARROW_RIGHT, top + ARROW_Y, ARROW, ink)
    return s


def item_at(menu: Menu, x: int, y: int) -> int | None:
    """The item under a point in the popup's own coordinates; None off the
    items (separators and the border included)."""
    width, height, tops = layout(menu)
    if not (1 <= x <= width - 2):
        return None
    for i, (item, top) in enumerate(zip(menu.items, tops)):
        size = SEPARATOR_HEIGHT if item.separator else ITEM_HEIGHT
        if top <= y < top + size:
            return None if item.separator else i
    return None


def cascade_at(parent_x: int, parent_y: int, parent_width: int, item_top: int, width: int,
               height: int, screen_width: int, screen_height: int, zoom: int) -> tuple[int, int]:
    """Where a cascade's popup goes on the screen, given its parent popup's
    corner in screen pixels; parent_width, item_top, width and height are in
    the popups' own pixels. Its first item lines up with the item it hangs
    from, and it hangs to the left when the screen has no room on the right."""
    x = parent_x + (parent_width - CASCADE_OVERLAP) * zoom
    if x + width * zoom > screen_width:
        x = parent_x + (CASCADE_OVERLAP - width) * zoom
    y = min(parent_y + (item_top - 1) * zoom, screen_height - height * zoom)
    return max(x, 0), max(y, 0)


# -- tracking ---------------------------------------------------------------------

class Tracker:
    """Which menu is lit or open and which item is highlighted.

    `menus` in Left/Right order: the control menu (title None), if any, then
    the bar's menus. Events say where the pointer is: ("title", n) for the
    bar's nth title, ("control",) for the control-menu box, ("item", n) for an
    item of the open popup (n None: on the popup but not on an item),
    ("subitem", n) the same for an open cascade, or None for anywhere else.
    Methods that can choose an item return its command.
    """

    def __init__(self, menus: list[Menu]):
        self.menus = menus
        self.current: int | None = None  # the lit menu
        self.opened = False              # its popup is showing
        self.item: int | None = None
        self.sub: int | None = None      # the open menu's item whose cascade is showing
        self.sub_item: int | None = None  # the highlighted item in the cascade
        self.tracking = False            # the mouse button is down
        self._close_on_release = False   # the press was on the open menu's title

    # -- what to draw ---------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.current is not None

    @property
    def popup(self) -> Menu | None:
        return self.menus[self.current] if self.opened else None

    @property
    def submenu(self) -> Menu | None:
        return None if self.sub is None else self.menus[self.current].items[self.sub].submenu

    @property
    def state(self) -> tuple:
        """Everything that changes what's drawn: compare it to see if anything did."""
        return self.current, self.opened, self.item, self.sub, self.sub_item

    @property
    def bar_highlight(self) -> int | None:
        """The lit title's index among the bar's menus."""
        if self.current is None or self.menus[self.current].title is None:
            return None
        return self.current - self._first_bar

    @property
    def control_open(self) -> bool:
        return self.current is not None and self.menus[self.current].title is None

    @property
    def _first_bar(self) -> int:
        return 1 if self.menus and self.menus[0].title is None else 0

    def _index(self, where) -> int | None:
        if where is None:
            return None
        if where[0] == "title":
            return where[1] + self._first_bar
        if where[0] == "control" and self._first_bar:
            return 0
        return None

    # -- changing it ----------------------------------------------------------

    def close(self) -> None:
        self.current, self.opened, self.item = None, False, None
        self.sub = self.sub_item = None
        self.tracking = self._close_on_release = False

    def _open(self, index: int, first_item: bool) -> None:
        self.current, self.opened = index, True
        self.sub = self.sub_item = None
        self.item = self._step(self.menus[index], -1, 1) if first_item else None

    def _cascade(self, item: int, first_item: bool) -> bool:
        """Open an item's cascade. False if it has none or it's greyed."""
        menu = self.menus[self.current].items[item]
        if menu.submenu is None or not menu.enabled:
            return False
        self.sub = item
        self.sub_item = self._step(menu.submenu, -1, 1) if first_item else None
        return True

    def _pointing_at(self, item: int | None) -> None:
        """The pointer is on an item of the open menu, or (None) on its border
        or a separator."""
        if item is None and self.sub is not None:
            return  # on its way across the border to the cascade: leave it open
        self.item, self.sub_item = item, None
        if item != self.sub:
            self.sub = None
            if item is not None:
                self._cascade(item, first_item=False)

    def _step(self, menu: Menu, start: int | None, step: int) -> int | None:
        items = menu.items
        n = len(items)
        i = start if start is not None else (-1 if step > 0 else n)
        for _ in range(n):
            i = (i + step) % n
            if not items[i].separator:
                return i
        return None

    def _choose(self, menu: Menu, item: int | None) -> str | None:
        if item is None:
            return None
        chosen = menu.items[item]
        if chosen.separator or not chosen.enabled:
            return None
        if chosen.submenu is not None:
            if self.sub != item:
                self._cascade(item, first_item=True)
            return None
        self.close()
        return chosen.command

    # -- mouse ------------------------------------------------------------------

    def press(self, where) -> str | None:
        index = self._index(where)
        if index is not None:
            self._close_on_release = self.opened and self.current == index
            if not self._close_on_release:
                self._open(index, first_item=False)
            self.tracking = True
        elif where is not None and where[0] == "item" and self.opened:
            self._pointing_at(where[1])
            self.tracking = True
        elif where is not None and where[0] == "subitem" and self.sub is not None:
            self.sub_item = where[1]
            self.tracking = True
        else:
            self.close()  # a click anywhere else just closes the menus
        return None

    def motion(self, where) -> None:
        if not (self.opened or self.tracking):
            return
        index = self._index(where)
        if index is not None:
            if index != self.current or not self.opened:
                self._open(index, first_item=False)
                self._close_on_release = False
            elif self.tracking:
                self.item = self.sub = self.sub_item = None
        elif where is not None and where[0] == "item" and self.opened:
            self._pointing_at(where[1])
        elif where is not None and where[0] == "subitem" and self.sub is not None:
            self.sub_item = where[1]
        elif self.tracking:
            if self.sub is not None:
                self.sub_item = None
            else:
                self.item = None

    def release(self, where) -> str | None:
        if not self.tracking:
            return None
        self.tracking = False
        if where is not None and where[0] == "subitem" and self.sub is not None:
            return self._choose(self.submenu, where[1])
        if where is not None and where[0] == "item" and self.opened:
            # On a disabled item, a separator or the border, the menu stays open.
            return self._choose(self.menus[self.current], where[1])
        index = self._index(where)
        if index is not None:
            if self._close_on_release:
                self.close()
            return None
        self.close()
        return None

    # -- keyboard -------------------------------------------------------------

    def alt_tap(self) -> None:
        """Alt pressed and let go with nothing between, or F10."""
        if self.current is None:
            if len(self.menus) > self._first_bar:
                self.current, self.opened, self.item = self._first_bar, False, None
        else:
            self.close()

    def alt_key(self, char: str) -> bool:
        """Alt+letter (Alt+space for the control menu): open that menu. False if none has it."""
        char = char.lower()
        for i, menu in enumerate(self.menus):
            if (char == " " and menu.title is None) or (menu.mnemonic and menu.mnemonic == char):
                self._open(i, first_item=True)
                return True
        return False

    def key(self, keysym: str, char: str = "") -> tuple[bool, str | None]:
        """A key while the menus are active: (handled, command chosen)."""
        if self.current is None:
            return False, None
        n = len(self.menus)
        if keysym == "Escape":
            if self.sub is not None:
                self.sub = self.sub_item = None
            elif self.opened:
                if self.menus[self.current].title is None:
                    self.close()  # the control menu has no title to fall back to
                else:
                    self.opened, self.item = False, None
            else:
                self.close()
            return True, None
        if keysym in ("Left", "Right"):
            if keysym == "Left" and self.sub is not None:
                self.sub = self.sub_item = None
                return True, None
            if keysym == "Right" and self.sub is not None and self.sub_item is None:
                self.sub_item = self._step(self.submenu, -1, 1)  # the pointer opened it
                return True, None
            if keysym == "Right" and self.opened and self.sub is None and self.item is not None \
                    and self._cascade(self.item, first_item=True):
                return True, None
            index = (self.current + (1 if keysym == "Right" else -1)) % n
            if self.opened:
                self._open(index, first_item=True)
            else:
                index = index if self.menus[index].title is not None else \
                    (index + (1 if keysym == "Right" else -1)) % n
                self.current = index
            return True, None
        if not self.opened:
            if keysym in ("Down", "Up", "Return", "KP_Enter"):
                self._open(self.current, first_item=True)
                return True, None
            if char and char.isprintable():
                for i, menu in enumerate(self.menus):
                    if menu.mnemonic == char.lower():
                        self._open(i, first_item=True)
                        return True, None
            return True, None  # swallowed, as 3.1 did (with a beep)
        step = 1 if keysym == "Down" else -1
        if self.sub is not None:  # the keys go to the cascade while it's open
            if keysym in ("Down", "Up"):
                self.sub_item = self._step(self.submenu, self.sub_item, step)
                return True, None
            if keysym in ("Return", "KP_Enter"):
                return True, self._choose(self.submenu, self.sub_item)
            if char and char.isprintable():
                for i, item in enumerate(self.submenu.items):
                    if item.mnemonic == char.lower():
                        self.sub_item = i
                        return True, self._choose(self.submenu, i)
            return True, None
        menu = self.menus[self.current]
        if keysym in ("Down", "Up"):
            self.item = self._step(menu, self.item, step)
            return True, None
        if keysym in ("Return", "KP_Enter"):
            return True, self._choose(menu, self.item)
        if char and char.isprintable():
            for i, item in enumerate(menu.items):
                if item.mnemonic == char.lower():
                    self.item = i
                    return True, self._choose(menu, i)
        return True, None
