"""The menus: 3.1's popup layout, and the rules for driving them."""

import numpy as np
import pytest

from soundrec import edits
from soundrec.ui.app import build_menus
from soundrec.ui.fonts import fonts_dir
from soundrec.ui.menus import (ARROW, ARROW_RIGHT, ARROW_Y, CASCADE_OVERLAP, SEPARATOR, Item, Menu,
                               Tracker, cascade_at, item_at, layout, paint_popup)
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


def cascading():
    tracks = Menu(None, [Item("Track &1...", "track-1"), Item("Track &2...", "track-2", enabled=False),
                         SEPARATOR, Item("&All Tracks...", "tracks-all")])
    return [Menu("&File", [Item("&New", "new"), Item("Save &Tracks", "tracks", submenu=tracks),
                           Item("&Greyed", "greyed", enabled=False, submenu=Menu(None, [Item("&X", "x")])),
                           SEPARATOR, Item("E&xit", "exit")]),
            Menu("&Help", [Item("&About...", "about")])]


def test_an_item_with_a_cascade_gets_an_arrow_inside_the_margin():
    menu = cascading()[0]
    plain = Menu("&File", [Item(i.label, i.command, enabled=i.enabled) for i in menu.items])
    width, _, tops = layout(menu)
    assert width == layout(plain)[0]  # measured menus stay as they were

    def arrow(s, item):
        x, y = width - ARROW_RIGHT, tops[item] + ARROW_Y
        h, w = ARROW.shape
        return s.pixels[y:y + h, x:x + w][ARROW]

    s = paint_popup(menu)
    assert np.all(arrow(s, 1) == BLACK)
    assert np.all(arrow(s, 2) == GREY)    # a greyed item's arrow is grey too
    assert np.all(arrow(s, 0) == WHITE)   # no cascade, no arrow
    assert np.all(arrow(paint_popup(menu, highlight=1), 1) == WHITE)


def test_a_cascades_first_item_lines_up_with_its_parent():
    x, y = cascade_at(100, 50, 120, 37, 80, 60, 1920, 1080, 2)
    assert x == 100 + (120 - CASCADE_OVERLAP) * 2
    assert y + 1 * 2 == 50 + 37 * 2  # past each popup's own one-pixel top border


def test_a_cascade_stays_on_the_screen():
    x, _ = cascade_at(1700, 50, 100, 19, 80, 60, 1920, 1080, 2)
    assert x == 1700 + (CASCADE_OVERLAP - 80) * 2  # no room on the right: it hangs left
    _, y = cascade_at(100, 1000, 100, 19, 80, 60, 1920, 1080, 2)
    assert y == 1080 - 60 * 2
    assert cascade_at(0, 0, 10, 0, 500, 700, 200, 300, 2) == (0, 0)


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


def test_hovering_opens_a_cascade_and_the_parent_stays_lit():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 0))
    assert t.submenu is None
    t.motion(("item", 1))
    assert t.sub == 1 and t.submenu.items[0].command == "track-1" and t.sub_item is None
    t.motion(("subitem", 0))
    assert t.item == 1 and t.sub_item == 0
    t.motion(("subitem", None))
    assert t.sub_item is None and t.submenu is not None
    t.motion(("item", 1))
    assert t.sub == 1 and t.sub_item is None
    t.press(("item", 1))
    assert t.release(("item", 1)) is None and t.submenu is not None  # a click just keeps it open
    t.motion(("subitem", 0))
    t.press(("subitem", 0))
    assert t.release(("subitem", 0)) == "track-1"
    assert not t.active and t.submenu is None


def test_crossing_the_border_on_the_way_to_a_cascade_keeps_it_open():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 1))
    t.motion(("item", None))
    assert t.item == 1 and t.submenu is not None


def test_hovering_another_item_closes_the_cascade():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 1))
    t.motion(("item", 0))
    assert t.submenu is None and t.item == 0


def test_a_greyed_item_opens_no_cascade():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 2))
    assert t.submenu is None and t.item == 2
    t.press(("item", 2))
    assert t.release(("item", 2)) is None and t.submenu is None and t.opened


def test_dragging_from_the_title_into_a_cascade_chooses():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.motion(("item", 1))
    t.motion(("subitem", 3))
    assert t.release(("subitem", 3)) == "tracks-all"


def test_letting_go_on_a_cascades_greyed_item_or_border_keeps_it_open():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.motion(("item", 1))
    assert t.release(("subitem", 1)) is None and t.submenu is not None
    t.press(("subitem", None))
    assert t.release(("subitem", None)) is None and t.submenu is not None
    t.press(("subitem", 2))  # the separator
    assert t.release(("subitem", 2)) is None and t.submenu is not None


def test_dragging_off_a_cascade_and_letting_go_closes_everything():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.motion(("item", 1))
    t.motion(("subitem", 0))
    t.motion(None)
    assert t.sub_item is None and t.submenu is not None
    assert t.release(None) is None and not t.active


def test_a_click_outside_closes_the_cascade_too():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 1))
    t.press(None)
    assert not t.active and t.submenu is None


def test_moving_to_another_title_closes_the_cascade():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 1))
    t.motion(("title", 1))
    assert t.bar_highlight == 1 and t.submenu is None


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


def test_the_arrows_open_and_close_a_cascade():
    t = Tracker(cascading())
    t.alt_key("f")
    t.key("Right")
    assert t.bar_highlight == 1 and t.submenu is None  # New has no cascade: on to Help
    t.key("Left")
    t.key("Down")
    assert t.item == 1
    t.key("Right")
    assert t.submenu is not None and t.sub_item == 0
    t.key("Down")
    assert t.sub_item == 1  # greyed, still lit
    t.key("Down")
    assert t.sub_item == 3  # over the separator
    t.key("Left")
    assert t.submenu is None and t.item == 1 and t.bar_highlight == 0


def test_right_from_inside_a_cascade_moves_to_the_next_menu():
    t = Tracker(cascading())
    t.alt_key("f")
    t.key("Down")
    t.key("Right")
    t.key("Right")
    assert t.bar_highlight == 1 and t.opened and t.submenu is None


def test_right_steps_into_a_cascade_the_pointer_opened():
    t = Tracker(cascading())
    t.press(("title", 0))
    t.release(("title", 0))
    t.motion(("item", 1))
    assert t.sub_item is None
    t.key("Right")
    assert t.sub_item == 0 and t.bar_highlight == 0


def test_escape_closes_the_cascade_first():
    t = Tracker(cascading())
    t.alt_key("f")
    t.key("Down")
    t.key("Right")
    t.key("Escape")
    assert t.submenu is None and t.opened and t.item == 1
    t.key("Escape")
    assert t.active and not t.opened


def test_enter_and_the_mnemonic_open_a_cascade_and_choose_from_it():
    t = Tracker(cascading())
    t.alt_key("f")
    t.key("Down")
    assert t.key("Return") == (True, None)
    assert t.submenu is not None and t.sub_item == 0
    assert t.key("Return") == (True, "track-1")
    assert not t.active
    t.alt_key("f")
    assert t.key("t", "t") == (True, None) and t.submenu is not None
    assert t.key("2", "2") == (True, None) and t.opened  # Track 2 is greyed
    assert t.key("a", "a") == (True, "tracks-all")


def test_a_greyed_item_ignores_the_right_arrow_and_enter():
    t = Tracker(cascading())
    t.alt_key("f")
    t.key("Down"), t.key("Down")
    assert t.item == 2
    assert t.key("Return") == (True, None) and t.submenu is None
    t.key("Right")
    assert t.bar_highlight == 1 and t.submenu is None


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

    from soundrec.output import Target
    from soundrec.ui import face as F
    from soundrec.ui.app import App
    from soundrec.ui.document import Document
    from soundrec.ui.meter import Meter

    app = App.__new__(App)
    app.menus = build_menus()
    app.face = F.FaceState(menus=tuple(m.title for m in app.menus[1:]))
    app.doc, app.position, app.recorder, app.player = Document(), 0, None, None
    app.devices = types.SimpleNamespace(busy=False, scan=None)
    app.device = types.SimpleNamespace(channels=device_channels) if device_channels else None
    app.meter, app.channels_wanted, app.output = Meter(), None, Target()
    app.custom_echo = edits.ECHO_CUSTOM_MS
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


# -- Edit and Effects through the window's own commands ------------------------------

def _app_with_sound(monkeypatch, data, rate=8000):
    import types

    from soundrec.takes import Take

    app = _app_without_a_window(2)
    take = Take.create(rate, data.shape[1])
    take.write(data)
    take.finish()
    app.doc.take = take
    app.root = types.SimpleNamespace(config=lambda **kw: None, update_idletasks=lambda: None)
    app.said, app.answers, app.zoom = [], [], 1
    monkeypatch.setattr(app, "redraw", lambda: None, raising=False)
    monkeypatch.setattr(app, "message", lambda text, **kw: app.said.append(text), raising=False)
    monkeypatch.setattr(app, "ask", lambda text, buttons, **kw: app.answers.pop(0), raising=False)
    return app


def enabled(app, menu):
    return {i.command for i in app.menus[menu].items if not i.separator and i.enabled}


def tracks_item(app):
    return app.menus[1].item("savetracks")


def test_save_tracks_lists_every_channel_and_all_of_them(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((800, 4), np.float32))
    app._sync()
    item = tracks_item(app)
    assert item.enabled
    assert [(i.label, i.command) for i in item.submenu.items if not i.separator] == [
        ("Track &1...", "track-1"), ("Track &2...", "track-2"), ("Track &3...", "track-3"),
        ("Track &4...", "track-4"), ("&All Tracks...", "tracks-all")]
    assert item.submenu.items[4].separator
    app.doc.close()


def test_tracks_past_nine_have_no_mnemonic():
    from soundrec.ui.app import track_items

    items = [i for i in track_items(12) if not i.separator]
    letters = [i.mnemonic for i in items if i.mnemonic]
    assert len(letters) == len(set(letters)) == 10 and items[9].label == "Track 10..."


def test_save_tracks_is_greyed_without_a_sound_or_for_one_channel(monkeypatch):
    app = _app_without_a_window(2)
    app._sync()
    assert not tracks_item(app).enabled
    mono = _app_with_sound(monkeypatch, np.zeros((800, 1), np.float32))
    mono._sync()
    assert not tracks_item(mono).enabled
    mono.doc.close()


def test_save_tracks_is_greyed_while_recording_or_playing(monkeypatch):
    import types

    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    app._sync()
    assert tracks_item(app).enabled
    app.player = types.SimpleNamespace(position=0)
    app._sync()
    assert not tracks_item(app).enabled
    app.player, app.record_at = None, 0
    app.recorder = types.SimpleNamespace(rate=8000, stats=types.SimpleNamespace(frames_out=0),
                                         recent=lambda n: np.zeros((0, 2), np.float32))
    app._sync()
    assert not tracks_item(app).enabled
    app.recorder = None
    app.doc.close()


def test_the_save_tracks_cascade_works_through_the_real_menus(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    app._sync()
    t = Tracker(app.menus)
    t.alt_key("f")
    assert t.key("t", "t") == (True, None) and t.submenu is tracks_item(app).submenu
    assert t.key("2", "2") == (True, "track-2")
    app.doc.close()


def _save_dialog(monkeypatch, *names):
    """The file dialog, answered with `names` in turn; returns what it was asked."""
    from soundrec.ui import app as app_module

    asked, answers = [], list(names)

    def dialog(**options):
        asked.append(options)
        return str(answers.pop(0))

    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", dialog)
    return asked


def test_a_saved_track_holds_exactly_that_channel(monkeypatch, tmp_path):
    import soundfile as sf

    a = np.random.default_rng(0).uniform(-0.5, 0.5, (800, 4)).astype(np.float32)
    app = _app_with_sound(monkeypatch, a)
    out = tmp_path / "track.wav"
    _save_dialog(monkeypatch, out)
    from soundrec.output import OutputSpec, Target

    app.output = Target(OutputSpec("WAV", "FLOAT"))
    app.command("track-3")
    data, rate = sf.read(str(out), dtype="float32", always_2d=True)
    assert rate == 8000 and data.shape == (800, 1)
    assert np.array_equal(data[:, 0], a[:, 2])
    app.doc.close()


def test_saving_a_track_leaves_the_sound_alone(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.ui.document import Document

    pcm = (np.random.default_rng(1).integers(-32768, 32767, (800, 4)) / 32768).astype(np.float32)
    source = tmp_path / "song.flac"
    sf.write(str(source), pcm, 44100, subtype="PCM_24")
    app = _app_with_sound(monkeypatch, np.zeros((10, 2), np.float32))
    app.doc.close()
    app.doc = Document.open(source)
    app.doc.dirty = True  # an edit not saved yet
    before = (app.doc.take, app.doc.path, app.doc.spec, app.doc.dirty)
    asked = _save_dialog(monkeypatch, tmp_path / "song-2.flac")
    app.save_track(1)
    assert (app.doc.take, app.doc.path, app.doc.spec, app.doc.dirty) == before
    assert np.array_equal(app.doc.read(0, 800), pcm)
    with sf.SoundFile(str(tmp_path / "song-2.flac")) as f:  # the sound's own format and rate
        assert (f.format, f.subtype, f.samplerate, f.channels) == ("FLAC", "PCM_24", 44100, 1)
        assert np.array_equal(f.read(dtype="float32"), pcm[:, 1])
    assert asked[0]["initialfile"] == "song-2.flac" and asked[0]["defaultextension"] == ".flac"
    assert asked[0]["filetypes"][0][1] == "*.flac" and asked[0]["confirmoverwrite"]
    assert not list(tmp_path.glob("*.saving"))
    app.doc.close()


def test_a_new_recordings_track_defaults_to_a_wave_named_untitled(monkeypatch, tmp_path):
    import soundfile as sf

    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    asked = _save_dialog(monkeypatch, tmp_path / "left.flac")
    app.save_track(0)
    assert asked[0]["initialfile"] == "untitled-1.wav"
    assert sf.info(str(tmp_path / "left.flac")).format == "FLAC"  # the name decides
    app.doc.close()


def test_cancelling_the_dialog_writes_nothing(monkeypatch, tmp_path):
    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    _save_dialog(monkeypatch, "")
    app.save_track(0)
    assert not app.said and not list(tmp_path.glob("*.wav"))
    app.doc.close()


def test_a_track_cant_replace_the_sounds_own_file(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.ui.document import Document

    source = tmp_path / "song.wav"
    sf.write(str(source), np.zeros((800, 4), np.float32), 8000, "FLOAT")
    app = _app_with_sound(monkeypatch, np.zeros((10, 2), np.float32))
    app.doc.close()
    app.doc = Document.open(source)
    _save_dialog(monkeypatch, str(source).upper())
    app.save_track(0)
    assert "the file this sound belongs to" in app.said[0]
    assert sf.info(str(source)).channels == 4
    app.doc.close()


def test_all_tracks_writes_name_1_name_2_from_one_dialog(monkeypatch, tmp_path):
    import soundfile as sf

    a = np.random.default_rng(2).uniform(-0.5, 0.5, (800, 3)).astype(np.float32)
    app = _app_with_sound(monkeypatch, a)
    asked = _save_dialog(monkeypatch, tmp_path / "band.flac")
    app.command("tracks-all")
    assert len(asked) == 1 and asked[0]["initialfile"] == "untitled.wav"
    assert not asked[0]["confirmoverwrite"]  # the names it writes aren't the one it would warn of
    for n in range(3):
        data, rate = sf.read(str(tmp_path / f"band-{n + 1}.flac"), dtype="float32")
        assert rate == 8000 and data.ndim == 1
        assert np.abs(data - a[:, n]).max() < 2 / 32768  # 16-bit FLAC, dithered
    assert not (tmp_path / "band.flac").exists() and not app.doc.dirty
    app.doc.close()


def test_all_tracks_asks_before_replacing(monkeypatch, tmp_path):
    a = np.zeros((800, 2), np.float32)
    app = _app_with_sound(monkeypatch, a)
    (tmp_path / "band-2.wav").write_bytes(b"precious")
    _save_dialog(monkeypatch, tmp_path / "band.wav", tmp_path / "band.wav")
    app.answers = ["no"]
    app.cmd_tracks_all()
    assert (tmp_path / "band-2.wav").read_bytes() == b"precious"
    assert not (tmp_path / "band-1.wav").exists()
    app.answers = ["yes"]
    app.cmd_tracks_all()
    assert (tmp_path / "band-1.wav").stat().st_size > 44
    assert (tmp_path / "band-2.wav").read_bytes() != b"precious"
    app.doc.close()


def test_a_failed_all_tracks_writes_nothing_and_says_so(monkeypatch, tmp_path):
    from soundrec import takes

    class DiskFull(takes.Writer):
        def write(self, block):
            if "-2." in self.path.name:
                raise OSError("disk full")
            super().write(block)

    monkeypatch.setattr(takes, "Writer", DiskFull)
    a = np.zeros((800, 2), np.float32)
    app = _app_with_sound(monkeypatch, a)
    (tmp_path / "band-1.wav").write_bytes(b"precious")
    _save_dialog(monkeypatch, tmp_path / "band.wav")
    app.answers = ["yes"]
    app.cmd_tracks_all()
    assert "disk full" in app.said[0]
    assert (tmp_path / "band-1.wav").read_bytes() == b"precious"
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["band-1.wav"]
    app.doc.close()


def test_the_pointer_finds_the_cascade_before_the_popup_under_it():
    import types

    from soundrec.ui.app import App

    menus_ = cascading()
    app = App.__new__(App)
    app.tracker = Tracker(menus_)
    app.tracker.alt_key("f")
    app.tracker.key("Down"), app.tracker.key("Right")
    _, _, tops = layout(app.tracker.submenu)
    hit = lambda on: types.SimpleNamespace(visible=True, contains=lambda x, y: on,
                                           local=lambda x, y: (5, tops[0] + 1))
    app.cascade, app.popup = hit(True), hit(True)
    assert app._where(0, 0) == ("subitem", 0)
    app.cascade = hit(False)
    assert app._where(0, 0) == ("item", 0)


def test_a_track_tells_of_a_rate_its_format_cant_hold(monkeypatch, tmp_path):
    import soundfile as sf

    app = _app_with_sound(monkeypatch, np.zeros((4410, 2), np.float32), rate=44100)
    _save_dialog(monkeypatch, tmp_path / "t.opus")
    app.save_track(0)
    assert sf.info(str(tmp_path / "t.opus")).samplerate == 48000
    assert "44,100" in app.said[0] and "48,000" in app.said[0] and app.doc.rate == 44100
    app.doc.close()


def test_save_as_keeps_the_sound_when_nothing_asks_for_a_change(monkeypatch, tmp_path):
    import soundfile as sf

    app = _app_with_sound(monkeypatch, np.zeros((4410, 2), np.float32), rate=44100)
    asked = _save_dialog(monkeypatch, tmp_path / "a.flac")
    take = app.doc.take
    assert app.cmd_saveas()
    assert asked[0]["initialfile"] == "untitled.wav" and asked[0]["defaultextension"] == ".wav"
    assert app.doc.take is take and app.doc.path == tmp_path / "a.flac"
    assert sf.info(str(tmp_path / "a.flac")).format == "FLAC"
    app.doc.close()


def test_save_as_asks_before_saving_a_copy_for_a_format(monkeypatch, tmp_path):
    import soundfile as sf

    a = np.random.default_rng(2).uniform(-0.5, 0.5, (4410, 4)).astype(np.float32)
    app = _app_with_sound(monkeypatch, a, rate=44100)
    app.position = 2205
    before = (app.doc.take, app.doc.path, app.doc.spec, app.doc.dirty)
    _save_dialog(monkeypatch, tmp_path / "a.mp3", tmp_path / "a.mp3")
    app.answers = ["no"]
    assert not app.cmd_saveas()
    assert not (tmp_path / "a.mp3").exists()
    app.answers = ["yes"]
    assert app.cmd_saveas()  # MP3 stops at two channels
    assert sf.info(str(tmp_path / "a.mp3")).channels == 2
    assert (app.doc.take, app.doc.path, app.doc.spec, app.doc.dirty) == before
    assert (app.doc.rate, app.doc.channels, app.doc.frames) == (44100, 4, 4410)
    assert np.array_equal(app.doc.read(0, 4410), a) and app.position == 2205
    app.doc.close()


def test_a_converted_copy_cant_replace_the_sounds_own_file(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.output import Target
    from soundrec.ui.document import Document

    source = tmp_path / "song.wav"
    sf.write(str(source), np.zeros((800, 4), np.float32), 8000, "FLOAT")
    app = _app_with_sound(monkeypatch, np.zeros((10, 2), np.float32))
    app.doc.close()
    app.doc = Document.open(source)
    app.output = Target(channels=2)
    _save_dialog(monkeypatch, str(source).upper())
    assert not app.cmd_saveas()
    assert "the file this sound belongs to" in app.said[0]
    assert sf.info(str(source)).channels == 4
    app.doc.close()


def test_after_a_copy_the_sound_is_still_unsaved_so_it_asks_again(monkeypatch, tmp_path):
    a = np.zeros((4410, 4), np.float32)
    app = _app_with_sound(monkeypatch, a, rate=44100)
    app.doc.dirty = True
    take = app.doc.take
    _save_dialog(monkeypatch, tmp_path / "a.mp3")
    app.answers = ["yes", "yes", "cancel"]  # save the changes, go on with the copy, then stop
    app.cmd_new()
    assert (tmp_path / "a.mp3").exists() and app.doc.take is take and not app.answers
    app.answers = ["no"]
    app.cmd_new()
    assert app.doc.take is None and not app.answers


def test_save_as_follows_the_output_format(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.output import OutputSpec, Target

    app = _app_with_sound(monkeypatch, np.zeros((4800, 2), np.float32), rate=48000)
    app.output = Target(OutputSpec("FLAC", "PCM_24"), 24000, 1)
    app.position = 4800
    app.answers = ["yes"]
    asked = _save_dialog(monkeypatch, tmp_path / "x.flac")
    assert app.cmd_saveas()
    assert asked[0]["initialfile"] == "untitled.flac" and asked[0]["filetypes"][0][1] == "*.flac"
    with sf.SoundFile(str(tmp_path / "x.flac")) as f:
        assert (f.subtype, f.samplerate, f.channels) == ("PCM_24", 24000, 1)
    assert (app.doc.rate, app.doc.channels) == (48000, 2) and app.position == 4800
    app.doc.close()


def test_a_name_with_another_extension_beats_the_output_format(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.output import OutputSpec, Target

    app = _app_with_sound(monkeypatch, np.zeros((4800, 2), np.float32), rate=48000)
    app.output = Target(OutputSpec("FLAC", "PCM_24"))
    _save_dialog(monkeypatch, tmp_path / "x.wav")
    assert app.cmd_saveas()
    assert sf.info(str(tmp_path / "x.wav")).subtype == "PCM_16"
    app.doc.close()


# -- Effects > Add Echo -----------------------------------------------------------------------

def test_add_echo_offers_its_delays(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    app._sync()
    item = app.menus[3].item("echo")
    assert item.enabled
    items = item.submenu.items
    assert [(i.label, i.command) for i in items[:-2]] == [
        (f"{ms} ms", f"echo-{ms}") for ms in (50, 100, 150, 200, 250, 300, 350, 400, 450, 500)]
    assert items[-2] is SEPARATOR
    assert (items[-1].label, items[-1].command) == ("&Custom...", "custom-echo")
    app.doc.close()


def test_add_echo_is_greyed_with_no_sound():
    app = _app_without_a_window(2)
    app._sync()
    assert not app.menus[3].item("echo").enabled


def test_the_delay_chosen_is_the_delay_of_the_echo(monkeypatch):
    a = np.zeros((4000, 2), np.float32)
    a[100] = [1.0, -1.0]
    app = _app_with_sound(monkeypatch, a)
    app._sync()
    app.position = 1234
    t = Tracker(app.menus)
    t.alt_key("s")
    t.key("a", "a")
    t.key("Down")
    command = t.key("Return")[1]
    assert command == "echo-100"
    app.command(command)
    out = app.doc.read(0, 4000).copy()
    assert np.allclose(out[100], [1.0, -1.0])
    assert np.allclose(out[900], [0.5, -0.5])  # 100 ms at 8000 Hz
    out[100] = out[900] = 0
    assert not out.any() and app.doc.dirty and app.position == 1234
    app.doc.close()


# -- Effects > Add Echo > Custom... -------------------------------------------------------------

def _answering(app, monkeypatch, *keys):
    """The box's window stood in for: types each string, pressing Enter after
    it, and Escape for a None. Keeps what the box opened on, and each refusal."""
    app.boxes, app.opened_on, app.refused = [], [], []

    def show(box):
        app.boxes.append(box)
        app.opened_on.append(box.edit.selected_text)
        box.message = lambda text, kind="info": app.refused.append(text)
        for text in keys:
            if text is None:
                box.key("Escape")
                break
            for c in text:
                box.key(c, c)
            if box.key("Return", "\r"):
                break
        return box.answer

    monkeypatch.setattr(app, "_show", show, raising=False)


def test_custom_is_reached_by_its_mnemonic(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((4000, 2), np.float32))
    app._sync()
    t = Tracker(app.menus)
    t.alt_key("s")
    t.key("a", "a")
    assert t.key("c", "c")[1] == "custom-echo"
    app.doc.close()


def test_a_custom_delay_reaches_the_echo(monkeypatch):
    a = np.zeros((4000, 2), np.float32)
    a[100] = [1.0, -1.0]
    app = _app_with_sound(monkeypatch, a)
    _answering(app, monkeypatch, "137")
    app.command("custom-echo")
    out = app.doc.read(0, 4000).copy()
    assert np.allclose(out[100 + 1096], [0.5, -0.5])  # 137 ms at 8000 Hz
    out[100] = out[100 + 1096] = 0
    assert not out.any() and app.doc.dirty
    app.doc.close()


def test_it_says_why_then_goes_back_for_another_try(monkeypatch):
    a = np.zeros((4000, 2), np.float32)
    a[0] = [1.0, 1.0]
    app = _app_with_sound(monkeypatch, a)
    _answering(app, monkeypatch, "abc", "1.5", "-1", "", "0", "100")
    app.command("custom-echo")
    assert len(app.refused) == 5 and len(app.boxes) == 1
    assert app.custom_echo == 100
    assert np.allclose(app.doc.read(800, 1), [0.5, 0.5])
    app.doc.close()


def test_cancel_leaves_the_sound_alone(monkeypatch):
    a = np.ones((4000, 2), np.float32)
    app = _app_with_sound(monkeypatch, a)
    take = app.doc.take
    monkeypatch.setattr(app, "add_echo", lambda ms: pytest.fail("echoed after Cancel"))
    _answering(app, monkeypatch, None)
    app.command("custom-echo")
    assert app.doc.take is take and not app.doc.dirty and app.custom_echo == 250
    app.doc.close()


def test_a_refused_delay_then_cancel_changes_nothing(monkeypatch):
    app = _app_with_sound(monkeypatch, np.ones((4000, 2), np.float32))
    take = app.doc.take
    _answering(app, monkeypatch, "99999", None)
    app.command("custom-echo")
    assert len(app.refused) == 1 and app.doc.take is take and app.custom_echo == 250
    app.doc.close()


def test_it_starts_on_250_then_the_last_delay_used(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((4000, 2), np.float32))
    _answering(app, monkeypatch, "120")
    app.command("custom-echo")
    assert app.opened_on == ["250"]
    _answering(app, monkeypatch, None)
    app.command("custom-echo")
    assert app.opened_on == ["120"]
    app.command("echo-300")  # a delay off the menu isn't a custom one
    _answering(app, monkeypatch, None)
    app.command("custom-echo")
    assert app.opened_on == ["120"]
    app.doc.close()


def test_custom_needs_a_sound():
    app = _app_without_a_window(2)
    app.root = None
    app.redraw = lambda: None
    app.cmd_custom_echo()  # would need a window if it got as far as asking


@pytest.mark.parametrize("text, words", [
    ("", "Type"), ("abc", "whole number"), ("1.5", "whole number"), ("-5", "whole number"),
    ("٣", "whole number"), ("0", "at least 1 ms"), ("5001", "more than 5000 ms"),
    ("9" * 255, "more than 5000 ms")])
def test_the_delay_check_says_whats_wrong(text, words):
    from soundrec.ui.app import echo_problem

    assert words in echo_problem(text, 10 ** 7, 44100)


@pytest.mark.parametrize("text", ["1", "250", "5000", "0250"])
def test_the_delay_check_passes_these(text):
    from soundrec.ui.app import echo_problem

    assert echo_problem(text, 10 ** 7, 44100) is None


def test_a_delay_the_sound_cant_hold_is_refused_exactly_where_the_echo_would_do_nothing(monkeypatch):
    from soundrec.ui.app import echo_problem

    a = np.ones((800, 1), np.float32)  # 100 ms at 8000 Hz
    app = _app_with_sound(monkeypatch, a)
    assert echo_problem("99", 800, 8000) is None
    assert "only 100 ms long" in echo_problem("100", 800, 8000)
    assert "only 100 ms long" in echo_problem("4000", 800, 8000)
    last = edits.echo(app.doc.take, 0.099)
    assert last.read(0, 800).max() > 1  # the last accepted delay still does something
    last.release()
    none = edits.echo(app.doc.take, 0.100)
    assert np.array_equal(none.read(0, 800), a)  # the first refused one really wouldn't
    none.release()
    app.doc.close()


def test_a_sound_too_short_for_any_delay_says_so():
    from soundrec.ui.app import echo_problem

    assert "only 1 ms long" in echo_problem("1", 8, 8000)  # 1 ms, and a delay of all 8 frames
    assert "only 1 ms long" in echo_problem("1", 2, 8000)  # rounded up, not "0 ms long"


def test_rare_formats_get_a_type_in_the_save_dialog():
    from soundrec.ui.app import save_types

    assert save_types(".flac")[0][1] == "*.flac"
    assert save_types(".voc")[0] == ("VOC files", "*.voc")


# -- the Device dialogs from the menu ---------------------------------------------------------

def _fake_scan():
    import types

    from soundrec.devices import Device

    a = Device("WASAPI", "Mic", 2, 48000, 1, None, True)
    b = Device("WASAPI", "Other", 4, 44100, 2)
    return types.SimpleNamespace(inputs=[a, b], outputs=[], endpoints=[])


def _with_dialogs(monkeypatch, answers):
    """An app whose dialogs run with no window; answers(dialog) says what happens."""
    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    app.root, app.zoom, app.probes = None, 1, {}
    app.devices.probe = lambda device, then: True

    def show(dialog):
        return answers(dialog)

    monkeypatch.setattr(app, "_show", show, raising=False)
    return app


def test_the_device_dialogs_are_greyed_while_busy(monkeypatch):
    import types

    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    device = app.menus[4]
    app._sync()
    assert device.item("format").enabled and not device.item("device").enabled  # no scan yet
    app.devices.scan = _fake_scan()
    app._sync()
    assert device.item("device").enabled
    app.player = types.SimpleNamespace(position=0)
    app._sync()
    assert not device.item("device").enabled and not device.item("format").enabled
    app.player = None
    app.doc.close()


def test_output_format_keeps_the_choice_on_ok_only(monkeypatch):
    from soundrec.output import Target

    def cancel(dialog):
        dialog.formats.select(2)
        dialog.changed(dialog.formats)
        return "cancel"

    app = _with_dialogs(monkeypatch, cancel)
    app.cmd_format()
    assert app.output == Target()
    monkeypatch.setattr(app, "_show", lambda dialog: (cancel(dialog), "ok")[1], raising=False)
    app.cmd_format()
    assert app.output.spec.format == "FLAC"
    app.doc.close()


def test_output_format_tells_the_dialog_about_the_sound(monkeypatch):
    seen = []
    app = _with_dialogs(monkeypatch, lambda dialog: seen.append(dialog.sound) or "cancel")
    app.cmd_format()
    assert seen == [(8000, 2)]
    app.doc.close()


def test_recording_device_changes_the_device_on_ok(monkeypatch):
    def pick_other(dialog):
        dialog.device_list.select(1)
        dialog.changed(dialog.device_list)
        return "ok"

    app = _with_dialogs(monkeypatch, pick_other)
    app.devices.scan = _fake_scan()
    app.device = app.devices.scan.inputs[0]
    app.cmd_device()
    assert app.device.name == "Other" and app.wanted == ("Other", "WASAPI")
    assert app.menus[4].item("channels-all").label == "&All 4 Channels"
    app.doc.close()


def test_recording_device_cancel_leaves_it(monkeypatch):
    app = _with_dialogs(monkeypatch, lambda dialog: "cancel")
    app.devices.scan = _fake_scan()
    first = app.device = app.devices.scan.inputs[0]
    app.wanted = (None, None)
    app.cmd_device()
    assert app.device is first and app.wanted == (None, None)
    app.doc.close()


def test_a_rescan_during_the_dialog_gives_the_latest_devices_copy(monkeypatch):
    import dataclasses

    def replug(dialog):
        dialog.device_list.select(1)
        dialog.changed(dialog.device_list)
        scan = app.devices.scan
        scan.inputs = [dataclasses.replace(d, index=d.index + 10) for d in scan.inputs]
        return "ok"

    app = _with_dialogs(monkeypatch, replug)
    app.device = None
    app.devices.scan = _fake_scan()
    app.cmd_device()
    assert app.device.name == "Other" and app.device.index == 12  # a stale index won't open
    app.doc.close()


def test_a_device_unplugged_during_the_dialog_is_reported(monkeypatch):
    def unplug(dialog):
        dialog.device_list.select(1)
        dialog.changed(dialog.device_list)
        app.devices.scan.inputs = app.devices.scan.inputs[:1]
        return "ok"

    app = _with_dialogs(monkeypatch, unplug)
    app.devices.scan = _fake_scan()
    app.device = app.devices.scan.inputs[0]
    app.cmd_device()
    assert app.device.name == "Mic" and "has gone" in app.said[0]
    app.doc.close()


def test_recording_device_says_so_before_the_first_scan(monkeypatch):
    app = _with_dialogs(monkeypatch, lambda dialog: "ok")
    app.device_problem = None
    app.cmd_device()
    assert "Still looking" in app.said[0]
    app.doc.close()


def test_a_new_sound_records_at_the_output_formats_rate(monkeypatch):
    import sys
    import types

    from soundrec.output import Target

    made = []

    class Recorder:
        def __init__(self, source, rate, channels, pick, meta):
            made.append(rate)

        def start(self):
            pass

    capture = types.SimpleNamespace(CaptureError=RuntimeError, open_capture=lambda *a: None)
    monkeypatch.setitem(sys.modules, "soundrec.capture", capture)
    monkeypatch.setitem(sys.modules, "soundrec.engine", types.SimpleNamespace(Recorder=Recorder))
    app = _app_without_a_window(2)
    monkeypatch.setattr(app, "redraw", lambda: None, raising=False)
    app.device = types.SimpleNamespace(channels=2, api="MME", endpoint=None, default_rate=48000,
                                       key="x", name="x")
    app.meter.reset = lambda: None
    app.output = Target(rate=22050)
    app._sync = lambda: None
    app.start_recording()
    assert made == [22050]


def test_edit_and_effects_are_greyed_without_a_sound(monkeypatch):
    app = _app_without_a_window(2)
    app._sync()
    assert enabled(app, 2) == {"insert", "mix"}
    assert enabled(app, 3) == set()


def test_delete_before_and_after_follow_the_position(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((800, 2), np.float32))
    app._sync()
    assert enabled(app, 2) == {"insert", "mix", "delete-after"}  # at the start
    assert len(enabled(app, 3)) == 6
    app.position = 800
    app._sync()
    assert enabled(app, 2) == {"insert", "mix", "delete-before"}  # at the end
    app.doc.close()


def test_reverse_swaps_in_a_new_take_and_drops_the_old(monkeypatch):
    a = np.random.default_rng(0).uniform(-0.5, 0.5, (800, 2)).astype(np.float32)
    app = _app_with_sound(monkeypatch, a)
    old = app.doc.take.path
    app.cmd_reverse()
    assert np.array_equal(app.doc.read(0, 800), a[::-1])
    assert app.doc.dirty and not old.exists()
    app.doc.close()


def test_faster_keeps_the_position_on_the_same_bit_of_sound(monkeypatch):
    app = _app_with_sound(monkeypatch, np.zeros((8000, 1), np.float32))
    app.position = 6000
    app.cmd_faster()
    assert abs(app.doc.frames - 4000) <= 1 and abs(app.position - 3000) <= 1
    app.doc.close()


def test_delete_asks_first(monkeypatch):
    a = np.arange(1600, dtype=np.float32).reshape(800, 2)
    app = _app_with_sound(monkeypatch, a)
    app.position = 300
    app.answers = ["no"]
    app.cmd_delete_before()
    assert app.doc.frames == 800 and not app.doc.dirty
    app.answers = ["yes"]
    app.cmd_delete_before()
    assert np.array_equal(app.doc.read(0, 800), a[300:]) and app.position == 0
    app.position = 100
    app.answers = ["yes"]
    app.cmd_delete_after()
    assert np.array_equal(app.doc.read(0, 800), a[300:400]) and app.position == 100
    app.doc.close()


def test_a_failed_edit_says_so_and_leaves_the_sound(monkeypatch):
    a = np.zeros((800, 2), np.float32)
    app = _app_with_sound(monkeypatch, a)
    take = app.doc.take

    def broken(t):
        raise OSError("disk full")

    app._edit(broken)
    assert app.doc.take is take and not app.doc.dirty
    assert "disk full" in app.said[0]
    app.doc.close()


def test_insert_file_lands_at_the_position_and_moves_past_it(monkeypatch, tmp_path):
    import soundfile as sf

    from soundrec.ui import app as app_module

    path = tmp_path / "in.wav"
    b = np.full((400, 2), 0.25, np.float32)
    sf.write(path, b, 8000, "FLOAT")
    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **kw: str(path))
    a = np.zeros((800, 2), np.float32)
    app = _app_with_sound(monkeypatch, a)
    app.position = 200
    app.cmd_insert()
    assert app.doc.frames == 1200 and app.position == 600
    assert np.allclose(app.doc.read(200, 400), 0.25) and not app.doc.read(600, 600).any()
    app.cmd_mix()  # at 600: over the silence after the inserted part
    assert app.doc.frames == 1200 and np.allclose(app.doc.read(600, 400), 0.25)
    app.doc.close()


def test_insert_into_no_sound_makes_the_file_the_sound(monkeypatch, tmp_path):
    import types

    import soundfile as sf

    from soundrec.ui import app as app_module

    path = tmp_path / "in.flac"
    sf.write(path, np.full((400, 1), 0.25, np.float32), 22050)
    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **kw: str(path))
    app = _app_without_a_window(2)
    app.root = types.SimpleNamespace(config=lambda **kw: None, update_idletasks=lambda: None)
    monkeypatch.setattr(app, "redraw", lambda: None, raising=False)
    app.cmd_insert()
    assert (app.doc.rate, app.doc.channels, app.doc.frames) == (22050, 1, 400)
    assert app.doc.path is None and app.doc.dirty and app.doc.name == "(Untitled)"
    app.doc.close()
