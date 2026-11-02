"""The window's drawing: fonts from Windows' .fon files, the pixel surface,
and the face, checked against what the 3.1 Sound Recorder measured."""

import numpy as np
import pytest

from soundrec.ui import face as F
from soundrec.ui.fonts import fonts_dir, sans_serif, system_font
from soundrec.ui.raster import BLACK, DARK, GREEN, GREY, NAVY, WHITE, Surface, bitmap

pytestmark = pytest.mark.skipif(not (fonts_dir() / "vgasys.fon").exists(),
                                reason="needs Windows' bitmap fonts")


def rows(ink):
    return ["".join("#" if v else "." for v in row) for row in ink]


# -- fonts ------------------------------------------------------------------------

def test_the_system_font_is_3_1s():
    font = system_font()
    assert (font.face, font.height, font.ascent, font.weight) == ("System", 16, 13, 700)
    assert [font.measure(t) for t in ("File", "Edit", "Effects", "Help")] == [24, 25, 44, 30]
    assert rows(font.render("F"))[3:5] == [".#######", ".##....."]


def test_ms_sans_serif_and_its_made_up_bold():
    regular, bold = sans_serif(8), sans_serif(8, bold=True)
    assert (regular.height, regular.ascent) == (13, 11)
    assert bold.measure("Stopped") == regular.measure("Stopped") + 7  # a pixel more a character
    # The bold "S" is the regular one drawn twice, a pixel apart.
    r = regular.render("S")
    twice = np.zeros((r.shape[0], r.shape[1] + 1), bool)
    twice[:, :-1] |= r
    twice[:, 1:] |= r
    assert np.array_equal(bold.render("S"), twice)
    assert rows(bold.render("Stopped"))[2] == "..####.......................................##"


def test_characters_a_font_lacks_draw_its_default():
    font = system_font()
    assert font.measure("☃") == font.measure(chr(font.default))


# -- the surface --------------------------------------------------------------------

def test_raised_edges_own_their_corners_as_3_1_did():
    s = Surface(6, 5)
    s.raised(0, 0, 5, 4, light=1, shadow=2)  # scroll arrows: the shadow wins
    assert tuple(s.pixels[4, 0]) == DARK and tuple(s.pixels[0, 5]) == DARK
    assert tuple(s.pixels[3, 0]) == WHITE and tuple(s.pixels[0, 4]) == WHITE
    s = Surface(6, 5)
    s.raised(0, 0, 5, 4, light=2, shadow=2, light_wins=True)  # push buttons: the light wins
    assert tuple(s.pixels[4, 0]) == WHITE and tuple(s.pixels[0, 5]) == WHITE
    assert tuple(s.pixels[4, 1]) == DARK and tuple(s.pixels[3, 1]) == WHITE


def test_invert_uses_the_sixteen_colour_palette():
    s = Surface(3, 1)
    s.pixels[0] = [GREY, WHITE, NAVY]
    s.invert(0, 0, 2, 0)
    assert [tuple(p) for p in s.pixels[0]] == [DARK, BLACK, (255, 255, 0)]


def test_checker_counts_from_its_origin():
    ink = np.ones((2, 2), bool)
    for origin, lit in (((0, 0), [(0, 0), (1, 1)]), ((1, 0), [(0, 1), (1, 0)])):
        s = Surface(2, 2, WHITE)
        s.mask(0, 0, ink, BLACK, checker=origin)
        assert sorted(zip(*np.nonzero(np.all(s.pixels == BLACK, axis=2)))) == lit


def test_png_and_ppm_carry_the_pixels():
    s = Surface(3, 2, NAVY)
    assert s.ppm(2).startswith(b"P6\n6 4\n255\n") and len(s.ppm(2)) == 11 + 6 * 4 * 3
    assert s.png().startswith(b"\x89PNG\r\n\x1a\n")


# -- the face -----------------------------------------------------------------------

def test_the_window_has_3_1s_size_and_frame():
    s = F.paint(F.FaceState())
    assert (s.width, s.height) == (317, 169)
    px = s.pixels
    assert all(tuple(px[y, x]) == BLACK for x, y in ((0, 0), (316, 168), (0, 100), (200, 19), (200, 38)))
    assert tuple(px[10, 100]) == NAVY and tuple(px[30, 200]) == WHITE  # caption, menu bar
    assert tuple(F.paint(F.FaceState(active=False)).pixels[10, 100]) == WHITE


def test_the_panels_are_where_3_1_put_them():
    px = F.paint(F.FaceState()).pixels
    for x0, y0, x1, y1 in (F.STATUS, F.POSITION, F.LENGTH):
        assert tuple(px[y0, x0 + 5]) == DARK and tuple(px[y1, x0 + 5]) == WHITE  # sunken
    assert all(tuple(px[93, x]) == GREEN for x in range(93, 224))  # the flat trace
    assert tuple(px[92, 100]) == BLACK


def test_a_trace_draws_a_connected_line():
    trace = np.sin(np.linspace(0, 4 * np.pi, 131))
    px = F.paint(F.FaceState(trace=trace)).pixels
    green = np.all(px[76:111, 93:224] == GREEN, axis=2)
    assert green.any(axis=0).all()  # every column has some line
    assert green[0].any() and green[-1].any()  # it reaches the top and the bottom


def test_disabled_glyphs_are_greyed_by_the_pattern_of_their_own_button():
    px = F.paint(F.FaceState()).pixels
    for name in ("rewind", "forward", "play", "stop"):
        x0, y0, x1, y1 = F.BUTTONS[name]
        ink = np.all(px[y0 + 3:y1 - 2, x0 + 3:x1 - 2] == BLACK, axis=2)
        ys, xs = np.nonzero(ink)
        assert len(ys) and set(((xs + 3) + (ys + 3)) % 2) == {0}, name
    x0, y0, _, _ = F.BUTTONS["record"]
    glyph = F.GLYPHS["record"]
    region = np.all(px[y0 + 3:y0 + 20, x0 + 3:x0 + 53] == BLACK, axis=2)
    assert np.array_equal(region, glyph)  # enabled: solid


def test_the_glyphs_are_3_1s():
    assert F.GLYPHS["play"][8, 20:31].all() and F.GLYPHS["play"][3, 20] and not F.GLYPHS["play"][3, 21]
    assert F.GLYPHS["stop"].sum() == 13 * 9
    # Forward is rewind mirrored, a pixel further left (columns 13-34 against 14-35).
    assert np.array_equal(F.GLYPHS["forward"], np.roll(F.GLYPHS["rewind"][:, ::-1], -1, axis=1))


def test_menu_titles_sit_where_3_1_put_them():
    titles = F.menu_titles(("&File", "&Edit", "Effect&s", "&Help"))
    assert [t[0] for t in titles] == [9, 49, 90, 150]
    assert [t[3] for t in titles] == [0, 0, 6, 0]
    assert F.title_box(("&File", "&Edit"), 1) == (41, 20, 81, 37)


@pytest.mark.parametrize("label, expected", [
    ("E&xit", ("Exit", 1)), ("&File", ("File", 0)), ("Plain", ("Plain", None)),
    ("Salt && &Pepper", ("Salt & Pepper", 7))])
def test_strip_mnemonic(label, expected):
    assert F.strip_mnemonic(label) == expected


@pytest.mark.parametrize("seconds, text", [(0, "0.00 sec."), (1.239, "1.23 sec."),
                                           (0.29, "0.29 sec."), (3600.999, "3600.99 sec."),
                                           (-0.001, "0.00 sec.")])
def test_seconds_text(seconds, text):
    assert F.seconds_text(seconds) == text


def test_hits():
    state = F.FaceState(menus=("&File", "&Edit"), thumb=0.5)
    assert F.hit(5, 5, state) == ("control", None)
    assert F.hit(305, 5, state) == ("minimize", None)
    assert F.hit(150, 10, state) == ("caption", None)
    assert F.hit(10, 25, state) == ("menu", 0) and F.hit(60, 25, state) == ("menu", 1)
    assert F.hit(200, 25, state) is None
    assert F.hit(20, 150, state) == ("button", "rewind") and F.hit(300, 150, state) == ("button", "record")
    assert F.hit(68, 150, state) is None  # between buttons
    left = F.thumb_left(0.5)
    assert F.hit(20, 127, state) == ("scroll", "left") and F.hit(295, 127, state) == ("scroll", "right")
    assert F.hit(left + 8, 127, state) == ("scroll", "thumb")
    assert F.hit(left - 5, 127, state) == ("scroll", "page-left")
    assert F.hit(left + 25, 127, state) == ("scroll", "page-right")
    assert F.fraction_at(F.thumb_left(0.37)) == pytest.approx(0.37, abs=1 / 245)


def test_bitmap():
    assert bitmap("#.", ".#").tolist() == [[True, False], [False, True]]


def test_the_default_zoom_doubles_at_100_percent():
    from soundrec.ui.window import default_zoom

    assert [default_zoom(dpi) for dpi in (96, 120, 144, 192)] == [2, 2, 3, 4]


# -- the level meter ----------------------------------------------------------------

def test_the_meter_jumps_up_falls_back_and_holds():
    from soundrec.ui.meter import FLOOR_DB, Meter, pair

    m = Meter()
    m.update([0.5, 0.25], 0.0)
    (left, right), (left_hold, _) = m.reading
    assert left == pytest.approx(-6.02, abs=0.01) and right == pytest.approx(-12.04, abs=0.01)
    m.update([0.0, 0.0], 0.5)  # silence: falls 20 dB a second, the hold stays
    (left, _), (left_hold, _) = m.reading
    assert left == pytest.approx(-16.02, abs=0.01) and left_hold == pytest.approx(-6.02, abs=0.01)
    m.update([0.0, 0.0], 2.0)  # past the hold time: the hold follows the bar down
    (left, _), (left_hold, _) = m.reading
    assert left == pytest.approx(-46.02, abs=0.01) and left_hold == left
    m.update([0.0, 0.0], 4.0)
    assert m.reading == ((FLOOR_DB, FLOOR_DB), (FLOOR_DB, FLOOR_DB))
    assert pair([0.3]) == (0.3, 0.3) and pair([0.1, 0.2, 0.4, 0.3]) == (0.4, 0.3)


def test_the_meter_bars_light_green_yellow_red_under_the_trace():
    from soundrec.ui.raster import RED, YELLOW

    state = F.FaceState(meter=((-1.0, -30.0), (-0.5, -20.0)))
    px = F.paint(state).pixels
    top, bottom = px[76:79, 93:224], px[108:111, 93:224]
    # -12 dBFS is column 105 of 131, -3 is 124; -1 lights 129 columns.
    assert tuple(top[0, 104]) == GREEN and tuple(top[0, 105]) == YELLOW and tuple(top[0, 124]) == RED
    assert tuple(top[0, 128]) == RED and tuple(top[0, 129]) == RED  # the bar's end, then its hold mark
    assert tuple(top[0, 130]) == BLACK
    assert F.meter_column(-1.0, 131) == 129 and F.meter_column(-0.5, 131) == 130
    lit = np.any(bottom[1] != BLACK, axis=1)
    bar_end, mark = F.meter_column(-30.0, 131), F.meter_column(-20.0, 131) - 1
    assert lit[:bar_end].all() and not lit[bar_end:mark].any() and lit[mark]
    assert tuple(bottom[1, F.meter_column(-20.0, 131) - 1]) == GREEN  # its hold mark
    assert tuple(px[93, 150]) == GREEN  # the trace still runs through the middle
    assert tuple(F.paint(F.FaceState()).pixels[77, 100]) == BLACK  # no bars when stopped
