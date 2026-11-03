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


def test_a_checked_item_gets_a_tick_in_the_margin():
    from soundrec.ui.menus import CHECK, CHECK_X, CHECK_Y

    menu = Menu("&Device", [Item("&Mono", "mono"), Item("&Stereo", "stereo", checked=True)])
    s = paint_popup(menu)
    _, _, tops = layout(menu)
    h, w = CHECK.shape
    for top, ticked in zip(tops, (False, True)):
        box = s.pixels[top + CHECK_Y:top + CHECK_Y + h, CHECK_X:CHECK_X + w]
        assert (np.all(box[CHECK] == BLACK, axis=-1).all() if ticked
                else np.all(box == WHITE, axis=-1).all())
    lit = paint_popup(menu, highlight=1)  # white on the highlight, like the text
    box = lit.pixels[tops[1] + CHECK_Y:tops[1] + CHECK_Y + h, CHECK_X:CHECK_X + w]
    assert np.all(box[CHECK] == WHITE, axis=-1).all()


def test_the_device_menu_offers_mono_stereo_or_every_channel():
    device = build_menus()[4]
    commands = [i.command for i in device.items if not i.separator]
    assert commands == ["device", "format", "channels-mono", "channels-stereo", "channels-all",
                        "refresh"]


def _app_without_a_window(device_channels):
    """Just enough of the App for _sync: no Tk, no devices."""
    import types

    from soundrec.ui import face as F
    from soundrec.ui.app import App
    from soundrec.ui.document import Document
    from soundrec.ui.meter import Meter

    app = App.__new__(App)
    app.menus = build_menus()
    app.face = F.FaceState(menus=tuple(m.title for m in app.menus[1:]))
    app.doc, app.position, app.recorder, app.player = Document(), 0, None, None
    app.devices = types.SimpleNamespace(busy=False)
    app.device = types.SimpleNamespace(channels=device_channels) if device_channels else None
    app.meter, app.channels_wanted = Meter(), None
    return app


def ticked(app):
    return [i.command for i in app.menus[4].items if i.checked]


def test_channel_ticks_start_from_the_device():
    assert ticked(_app_without_a_window(1)) == []  # nothing until _sync
    for channels, choice in ((1, "channels-mono"), (2, "channels-stereo"), (4, "channels-stereo")):
        app = _app_without_a_window(channels)
        app._sync()
        assert ticked(app) == [choice]
    app._sync()
    assert app.menus[4].item("channels-all").label == "&All 4 Channels"
    assert app.menus[4].item("channels-all").enabled


def test_all_channels_is_greyed_for_a_stereo_device():
    app = _app_without_a_window(2)
    app._sync()
    item = app.menus[4].item("channels-all")
    assert item.label == "&All Channels" and not item.enabled


def test_picking_channels_moves_the_tick_until_theres_a_sound(monkeypatch):
    import types

    app = _app_without_a_window(4)
    monkeypatch.setattr(app, "redraw", lambda: None, raising=False)
    app.cmd_channels_all()
    assert ticked(app) == ["channels-all"] and app.channel_choice == "all"
    app.doc.take = types.SimpleNamespace(rate=48000, channels=4, frames=0,
                                         read=lambda start, count: np.zeros((0, 4), np.float32))
    app._sync()  # a sound fixes the channels: the choices go grey, the tick stays
    assert ticked(app) == ["channels-all"]
    assert not any(app.menus[4].item("channels-" + n).enabled for n in ("mono", "stereo", "all"))
