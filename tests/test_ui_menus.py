"""The menus: 3.1's popup layout, and the rules for driving them."""

import numpy as np
import pytest

from soundrec.ui.app import build_menus
from soundrec.ui.fonts import fonts_dir
from soundrec.ui.menus import SEPARATOR, Item, Menu, Tracker, item_at, layout, paint_popup
from soundrec.ui.raster import BLACK, GREY, NAVY, WHITE

pytestmark = pytest.mark.skipif(not (fonts_dir() / "vgasys.fon").exists(),
                                reason="needs Windows' bitmap fonts")


def menus():
    return [Menu(None, [Item("&Restore", "restore", enabled=False), Item("&Move", "move"),
                        SEPARATOR, Item("&Close", "close", "Alt+F4")]),
            Menu("&File", [Item("&New", "new"), Item("&Open...", "open"),
                           Item("&Save", "save", enabled=False), SEPARATOR, Item("E&xit", "exit")]),
            Menu("&Edit", [Item("&Insert File...", "insert", enabled=False)]),
            Menu("&Help", [Item("&About...", "about")])]


# -- layout and drawing -------------------------------------------------------------

def test_the_control_menu_has_3_1s_measurements():
    control = build_menus()[0]
    width, height, tops = layout(control)
    # Measured from a 3.1 screenshot: 167 x 142, 18-pixel items, 7-pixel separators.
    assert (width, height) == (167, 142)
    assert tops == [1, 19, 37, 55, 73, 91, 98, 116, 123]


def test_a_popup_highlights_and_greys():
    menu = menus()[1]
    s = paint_popup(menu, highlight=0)
    _, _, tops = layout(menu)
    assert tuple(s.pixels[tops[0] + 17, 5]) == NAVY  # the highlight bar fills the item
    assert tuple(s.pixels[0, 0]) == BLACK and tuple(s.pixels[tops[1], 5]) == WHITE
    save = s.pixels[tops[2]:tops[2] + 16, 16:60]
    assert np.all(save == GREY, axis=2).any() and not np.all(save == BLACK, axis=2).any()
    assert np.all(s.pixels[tops[3] + 3] == BLACK)  # the separator spans the border too


def test_item_at():
    menu = menus()[1]
    _, _, tops = layout(menu)
    assert item_at(menu, 10, tops[1] + 5) == 1
    assert item_at(menu, 10, tops[3] + 3) is None  # separator
    assert item_at(menu, 0, tops[1] + 5) is None   # border
    assert item_at(menu, 10, 500) is None


# -- the mouse ------------------------------------------------------------------------

def test_press_drag_release_chooses():
    t = Tracker(menus())
    t.press(("title", 0))
    assert t.opened and t.bar_highlight == 0 and t.item is None
    t.motion(("item", 1))
    assert t.item == 1
    assert t.release(("item", 1)) == "open"
    assert not t.active


def test_click_then_click():
    t = Tracker(menus())
    t.press(("title", 0))
    assert t.release(("title", 0)) is None and t.opened  # stays open
    t.motion(("title", 1))
    assert t.bar_highlight == 1 and t.opened  # moving over another title switches
    t.press(("item", 0))
    assert t.release(("item", 0)) is None and t.opened  # disabled: nothing, stays open
    t.motion(("title", 2))
    t.press(("item", 0))
    assert t.release(("item", 0)) == "about"


def test_clicking_the_open_title_again_closes():
    t = Tracker(menus())
    t.press(("title", 0))
    t.release(("title", 0))
    t.press(("title", 0))
    t.release(("title", 0))
    assert not t.active


def test_a_click_elsewhere_closes_and_a_release_off_the_menu_too():
    t = Tracker(menus())
    t.press(("title", 0))
    t.release(("title", 0))
    t.press(None)
    assert not t.active
    t.press(("title", 0))
    t.motion(None)
    assert t.release(None) is None and not t.active


def test_the_border_and_separators_keep_the_menu_open():
    t = Tracker(menus())
    t.press(("title", 0))
    t.motion(("item", 1))
    t.motion(("item", None))
    assert t.item is None
    assert t.release(("item", None)) is None and t.opened


def test_the_control_box_opens_the_control_menu():
    t = Tracker(menus())
    t.press(("control",))
    assert t.control_open and t.opened and t.bar_highlight is None
    assert t.release(("item", 1)) == "move"


# -- the keyboard ---------------------------------------------------------------------

def test_alt_lights_the_first_title_and_arrows_walk_the_bar():
    t = Tracker(menus())
    t.alt_tap()
    assert t.bar_highlight == 0 and not t.opened
    t.key("Right")
    assert t.bar_highlight == 1
    t.key("Left"), t.key("Left")
    assert t.bar_highlight == 2  # past the control menu, which has no title to light
    t.alt_tap()
    assert not t.active


def test_down_opens_and_enter_chooses():
    t = Tracker(menus())
    t.alt_tap()
    t.key("Down")
    assert t.opened and t.item == 0
    t.key("Down"), t.key("Down")
    assert t.item == 2
    assert t.key("Return") == (True, None) and t.opened  # Save is disabled
    t.key("Down")
    assert t.item == 4  # over the separator
    t.key("Down")
    assert t.item == 0  # and round
    t.key("Up")
    assert t.key("Return") == (True, "exit")


def test_mnemonics():
    t = Tracker(menus())
    assert t.alt_key("f") and t.opened and t.item == 0
    assert t.key("x", "x") == (True, "exit")
    t.alt_tap()
    t.key("e", "e")
    assert t.bar_highlight == 1 and t.opened
    assert not Tracker(menus()).alt_key("q")


def test_escape_backs_out_a_step():
    t = Tracker(menus())
    t.alt_key("f")
    t.key("Escape")
    assert t.active and not t.opened and t.bar_highlight == 0
    t.key("Escape")
    assert not t.active


def test_alt_space_and_left_from_file_reach_the_control_menu():
    t = Tracker(menus())
    assert t.alt_key(" ") and t.control_open and t.item == 0  # Restore: disabled, still lit first
    t.key("Escape")
    assert not t.active  # nothing to fall back to
    t.alt_key("f")
    t.key("Left")
    assert t.control_open and t.opened
    t.key("Right")
    assert t.bar_highlight == 0 and t.opened


def test_the_apps_menus_are_3_1s_plus_device():
    titles = [m.title for m in build_menus()]
    assert titles == [None, "&File", "&Edit", "Effect&s", "&Device", "&Help"]
    for menu in build_menus():
        letters = [i.mnemonic for i in menu.items if not i.separator]
        assert len(letters) == len(set(letters)), menu.title
