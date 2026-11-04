"""The list and edit boxes and the dialogs, driven with no window, as the Tracker is."""

import numpy as np
import pytest

from soundrec.devices import Device, Scan
from soundrec.endpoints import Endpoint, WaveFormat
from soundrec.output import OutputSpec, Target, default_quality, qualities
from soundrec.probe import Probe
from soundrec.ui.controls import EDIT_HEIGHT, ROW, TEXT_INSET, EditBox, ListBox, height_for
from soundrec.ui.dialog import Dialog, MessageBox
from soundrec.ui.dialogs import (BY_NAME, InputBox, OutputFormatDialog, RecordingDeviceDialog,
                                 advice, channel_names, describe, is_touchy, is_whole_number)
from soundrec.ui.fonts import fonts_dir, system_font
from soundrec.ui.raster import BLACK, GREY, NAVY, WHITE, Surface

pytestmark = pytest.mark.skipif(not (fonts_dir() / "vgasys.fon").exists(),
                                reason="needs Windows' bitmap fonts")


def row_y(box, row):
    return box.box[1] + 1 + (row - box.top) * ROW + 8


# -- the list box --------------------------------------------------------------------

def listbox(rows=20, visible=5):
    box = ListBox((10, 30, 150, 30 + height_for(visible) - 1), "&Things:")
    box.fill([f"row {i}" for i in range(rows)])
    return box


def test_keys_walk_the_list_and_scroll_to_keep_up():
    box = listbox()
    assert box.selected == 0 and box.visible == 5
    for _ in range(6):
        box.key("Down")
    assert box.selected == 6 and box.top == 2
    box.key("Home")
    assert box.selected == 0 and box.top == 0
    box.key("End")
    assert box.selected == 19 and box.top == 15
    assert not box.key("Down")  # nothing below the last row
    box.key("Prior")
    assert box.selected == 15
    box.key("Next")
    assert box.selected == 19


def test_a_letter_finds_the_next_row_starting_with_it():
    box = ListBox((0, 17, 100, 17 + height_for(4) - 1))
    box.fill(["Apple", "Banana", "Avocado", "Cherry"])
    assert box.key("a", "a") and box.selected == 2
    assert box.key("a", "a") and box.selected == 0
    assert not box.key("z", "z")


def test_greyed_rows_are_skipped_and_cant_be_clicked():
    box = ListBox((0, 17, 100, 17 + height_for(4) - 1))
    box.fill(["a", "b", "c", "d"], 0, greyed=[1, 3])
    box.key("Down")
    assert box.selected == 2
    assert not box.key("Down") and box.selected == 2  # only a greyed row below
    assert not box.press(5, row_y(box, 3))
    assert box.selected == 2


def test_clicking_a_row_selects_it():
    box = listbox()
    assert box.press(20, row_y(box, 3)) and box.selected == 3


def test_the_scrollbar_arrows_trough_and_thumb():
    box = listbox()
    x = box.box[2] - 5
    assert box.hit(x, box.box[1] + 3) == "up" and box.hit(x, box.box[3] - 3) == "down"
    box.press(x, box.box[3] - 3)
    assert box.top == 1 and box.held == "down"
    assert box.repeat() and box.top == 2
    box.release()
    assert box.held is None and not box.repeat()
    box.press(x, box.box[3] - 20)  # the trough, below the thumb
    assert box.hit(x, box.thumb_y + 5) == "thumb"
    assert box.top == 7
    box.release()
    box.press(x, box.thumb_y + 5)
    assert box.held == "thumb"
    assert box.drag(box.box[3])
    assert box.top == box.last_top
    box.release()
    assert box.selected == 0  # scrolling doesn't move the selection


def test_the_wheel_stays_in_range():
    box = listbox()
    box.scroll(-3)
    assert box.top == 0
    box.scroll(300)
    assert box.top == box.last_top


def test_no_scrollbar_when_the_rows_fit():
    box = listbox(rows=3)
    assert not box.scrolls and box.last_top == 0
    assert box.hit(box.box[2] - 5, row_y(box, 1)) == 1
    assert box.hit(20, row_y(box, 4)) is None  # past the last row


def test_a_list_paints_its_selection_frame_and_label():
    box = listbox()
    s = Surface(200, 200, WHITE)
    box.paint(s, focused=False)
    x0, y0, x1, y1 = box.box
    assert tuple(s.pixels[y0, x0 + 5]) == BLACK and tuple(s.pixels[y1, x0 + 5]) == BLACK
    assert tuple(s.pixels[y0 + 2, x0 + 1]) == NAVY  # the selected row
    assert tuple(s.pixels[y0 + 1 + ROW + 2, x0 + 1]) == WHITE
    assert np.all(s.pixels[y0 + 20:y0 + 30, x1 - 5] != 0)  # the scrollbar's in there
    label = s.pixels[y0 - 17:y0, x0:x0 + 50]
    assert np.all(label == BLACK, axis=2).any()
    assert tuple(s.pixels[y0 + 2, x1 - 20]) == NAVY  # up to the scrollbar


def test_long_rows_stop_at_the_scrollbar():
    box = ListBox((0, 17, 60, 17 + height_for(2) - 1))
    box.fill(["x" * 100, "y", "z"], 1)
    s = Surface(200, 80, WHITE)
    box.paint(s, focused=False)
    assert np.all(s.pixels[18:50, 62:] == 255)  # nothing past the frame


def test_a_disabled_list_is_grey_and_takes_no_key():
    box = listbox(rows=3)
    box.enabled = False
    assert not box.key("Down")
    s = Surface(200, 200, WHITE)
    box.paint(s, focused=True)
    assert not np.all(s.pixels == NAVY, axis=2).any()


# -- the base dialog, through MessageBox ---------------------------------------------------

def test_a_message_box_still_answers_as_it_did():
    box = MessageBox(None, 1, "Sound Recorder", "Save?", [("&Yes", "yes"), ("&No", "no"),
                                                          ("Cancel", "cancel")])
    assert box.key("Escape") and box.answer == "cancel"
    box.key("Tab")
    assert box.focused_button == 1
    box.key("ISO_Left_Tab"), box.key("Left")
    assert box.focused_button == 2
    assert box.key("space") and box.answer == "cancel"
    assert box.key("y", "y") and box.answer == "yes"


def test_a_button_needs_the_mouse_to_come_up_on_it():
    box = MessageBox(None, 1, "t", "Save?", [("&Yes", "yes"), ("&No", "no")])
    x0, y0, x1, y1 = box.boxes[1]
    box.press(x0 + 3, y0 + 3)
    assert box.pressed == 1
    assert box.motion(0, 0) and box.pressed is None  # off it: up
    assert box.motion(x0 + 3, y0 + 3) and box.pressed == 1  # back on: down
    box.motion(0, 0)
    assert not box.release(0, 0)
    box.press(x0 + 3, y0 + 3)
    assert box.release(x0 + 3, y0 + 3) and box.answer == "no"


# -- Output Format ----------------------------------------------------------------------------

def pick(dialog, box, text):
    box.select(box.rows.index(text))
    dialog.changed(box)


def format_row(dialog, name):
    return dialog.format_keys.index(name)


def test_it_starts_by_leaving_the_format_to_the_name():
    d = OutputFormatDialog(None, 1)
    assert d.formats.rows[0] == BY_NAME and d.formats.selected == 0
    assert d.result == Target()
    assert not d.encodings.enabled and not d.quality.enabled
    assert "name" in d.summary()


def test_the_common_formats_come_first_and_every_other_follows():
    d = OutputFormatDialog(None, 1)
    assert d.format_keys[1:6] == ["WAV", "FLAC", "MP3", "OGG", "M4A"]
    assert {"AIFF", "CAF", "VOC", "W64", "RF64"} <= set(d.format_keys)


def test_choosing_a_format_fills_encoding_quality_and_rate():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "MP3"))
    d.changed(d.formats)
    assert d.encoding == "MPEG_LAYER_III" and d.encodings.rows == ["MPEG Layer III"]
    assert d.quality.enabled
    assert d.quality.rows[d.quality.selected] == "Constant 192 kbit/s"
    assert d.rate_keys[1:] == [8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000]


def test_flac_offers_compression_levels_and_wav_no_quality():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "FLAC"))
    d.changed(d.formats)
    assert d.quality.rows[d.quality.selected] == "Level 5"
    assert 96000 in d.rate_keys
    d.formats.select(format_row(d, "WAV"))
    d.changed(d.formats)
    assert not d.quality.enabled and d.result.spec == OutputSpec("WAV", "PCM_16")


def test_choosing_the_encoding_changes_the_lists_after_it():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "OGG"))
    d.changed(d.formats)
    assert d.encoding == "VORBIS"
    d.rates.select(d.rate_keys.index(44100))
    d.encodings.select(d.encoding_keys.index("OPUS"))
    d.changed(d.encodings)
    assert d.encoding == "OPUS" and d.rate is None  # 44.1 kHz isn't Opus's to offer
    assert d.quality.rows[d.quality.selected] == "64 kbit/s a channel"


def test_a_rate_the_new_format_also_takes_stays_chosen():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "FLAC"))
    d.changed(d.formats)
    d.rates.select(d.rate_keys.index(44100))
    d.formats.select(format_row(d, "MP3"))
    d.changed(d.formats)
    assert d.rate == 44100


def test_it_opens_on_the_choice_already_made():
    spec = OutputSpec("FLAC", "PCM_24", next(q for q in qualities(OutputSpec("FLAC", "PCM_24"))
                                             if q.label.startswith("Level 8")))
    target = Target(spec, 22050, 1)
    d = OutputFormatDialog(None, 1, target)
    assert d.result == target
    assert "FLAC 24-bit, Level 8 (smallest) at 22,050 Hz, mono" in d.summary()


def test_the_dialog_answers_with_its_target():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "M4A"))
    d.changed(d.formats)
    d.channels.select(2)
    assert d.key("Return") and d.answer == "ok"
    assert d.result == Target(OutputSpec("M4A", "AAC", default_quality(OutputSpec("M4A", "AAC"))),
                              None, 2)


def test_escape_cancels():
    d = OutputFormatDialog(None, 1)
    assert d.key("Escape") and d.answer == "cancel"


def test_tab_skips_the_lists_that_are_empty():
    d = OutputFormatDialog(None, 1)
    d.key("Tab")
    assert d.focused_list is d.rates
    d.key("Tab")
    assert d.focused_list is d.channels
    d.key("Tab")
    assert d.focused_button == 0
    d.key("Tab"), d.key("Tab")
    assert d.focused_list is d.formats


def test_alt_and_a_mnemonic_reach_a_list():
    d = OutputFormatDialog(None, 1)
    d.formats.select(format_row(d, "MP3"))
    d.changed(d.formats)
    d.key("r", "r", alt=True)
    assert d.focused_list is d.rates
    d.key("q", "q", alt=True)
    assert d.focused_list is d.quality


def test_a_mouse_click_on_a_format_refills_the_rest():
    d = OutputFormatDialog(None, 1)
    box = d.formats
    d.press(box.box[0] + 10, row_y(box, 2))
    d.release(box.box[0] + 10, row_y(box, 2))
    assert d.format == "FLAC" and d.focused_list is d.formats and d.encodings.enabled


def test_a_double_click_on_a_row_is_ok():
    d = OutputFormatDialog(None, 1)
    box = d.formats
    assert d.double(box.box[0] + 10, row_y(box, 1)) and d.answer == "ok"


def test_the_wheel_scrolls_the_list_under_the_pointer():
    d = OutputFormatDialog(None, 1)
    box = d.formats
    d.wheel(box.box[0] + 5, box.box[1] + 5, -1)
    assert box.top == 3


def test_mp3_is_called_mp3_on_the_list():
    d = OutputFormatDialog(None, 1)
    assert d.formats.rows[format_row(d, "MP3")].startswith("MP3")


def test_it_says_when_save_as_would_make_a_copy():
    d = OutputFormatDialog(None, 1, sound=(44100, 2))
    assert "a copy" not in d.summary()
    d.formats.select(format_row(d, "OGG"))
    d.changed(d.formats)
    d.encodings.select(d.encoding_keys.index("OPUS"))
    d.changed(d.encodings)
    assert "a copy at 48,000 Hz stereo; this sound stays as it is" in d.summary()


def test_it_says_a_format_will_fold_channels():
    d = OutputFormatDialog(None, 1, sound=(44100, 4))
    d.formats.select(format_row(d, "MP3"))
    d.changed(d.formats)
    assert "a copy at 44,100 Hz stereo" in d.summary()


def test_it_says_nothing_of_a_sound_with_no_sound():
    d = OutputFormatDialog(None, 1)
    d.channels.select(1)
    assert "a copy" not in d.summary() and "mono" in d.summary()


def test_it_paints_at_3_1s_frame():
    d = OutputFormatDialog(None, 1)
    s = d.paint()
    assert (s.width, s.height) == (d.width, d.height)
    assert tuple(s.pixels[0, 0]) == BLACK and tuple(s.pixels[2, 2]) == NAVY
    x0, y0, _, _ = d.boxes[0]
    assert tuple(s.pixels[y0 + 12, x0 + 4]) == GREY
    assert tuple(s.pixels[d.formats.box[1] + 2, d.formats.box[0] + 1]) == NAVY


# -- Recording Device ---------------------------------------------------------------------------

ENGINE = WaveFormat(44100, 2, 24, 24, False)


def endpoint(name, state="active", hidden=False):
    return Endpoint("id-" + name, "capture", name, "", state, hidden, "microphone", "USB", ENGINE)


def device(api, name, channels=2, default=False, end=None):
    return Device(api, name, channels, 44100, 0, end, default)


def scan():
    mic = endpoint("Microphone (H2n)")
    inputs = [device("WASAPI", "Microphone Array", 2, True), device("WASAPI", "Microphone (H2n)", 4, end=mic),
              device("ASIO", "ZOOM H and F Series ASIO", 2, True), device("ASIO", "FL Studio ASIO", 2),
              device("WDM-KS", "PC Speaker (Realtek)", 2),
              device("MME", "Microphone (H2n)", 4, end=mic)]
    return Scan(inputs, [], [mic, endpoint("Line In", "unplugged"), endpoint("Internal AUX", "unplugged", True),
                             Endpoint("x", "render", "Speakers", "", "unplugged", False, "", "", None)])


def dialog(current=None, probes=None, start_probe=None):
    return RecordingDeviceDialog(None, 1, scan(), current, {} if probes is None else probes, start_probe)


def test_it_lists_the_apis_there_are_most_direct_first():
    d = dialog()
    assert d.api_list.rows == ["WASAPI", "ASIO", "WDM-KS", "MME"]


def test_it_starts_on_the_current_device():
    s = scan()
    d = dialog(s.inputs[1])
    assert d.api == "WASAPI" and d.device.key == "WASAPI: Microphone (H2n)"
    d = dialog(s.inputs[3])
    assert d.api == "ASIO" and d.device.name == "FL Studio ASIO"


def test_it_starts_on_the_apis_default_with_nothing_chosen():
    d = dialog()
    assert d.device.name == "Microphone Array"
    assert d.device_list.rows[0] == "Microphone Array (default)"


def test_unplugged_endpoints_show_greyed_and_cant_be_picked():
    d = dialog()
    rows = d.device_list.rows
    assert "Line In (unplugged)" in rows
    assert not any("Internal AUX" in row for row in rows)  # hidden
    assert not any("Speakers" in row for row in rows)      # not a capture endpoint
    greyed = rows.index("Line In (unplugged)")
    assert greyed in d.device_list.greyed
    d.device_list.key("End")
    assert d.device.name == "Microphone (H2n)"


def test_changing_the_api_refills_the_devices():
    d = dialog()
    d.api_list.select(d.apis.index("ASIO"))
    d.changed(d.api_list)
    assert d.device.name == "ZOOM H and F Series ASIO"
    assert not d.device_list.greyed


def test_choosing_a_device_asks_nothing_of_it():
    asked = []
    d = dialog(start_probe=lambda device, done: asked.append(device))
    d.device_list.key("Down")
    d.changed(d.device_list)
    d.api_list.key("Down")
    d.changed(d.api_list)
    assert asked == []
    assert "press Probe" in " ".join(d.details())


def test_converted_apis_answer_without_asking_and_grey_probe():
    d = dialog()
    d.api_list.select(d.apis.index("MME"))
    d.changed(d.api_list)
    assert 2 in d.dead
    assert any("Takes anything, converted by Windows from" in line for line in d.details())


def test_probe_warns_about_the_h2n_and_stops_at_no():
    asked = []
    s = scan()
    d = dialog(s.inputs[1], start_probe=lambda device, done: asked.append(device) or True)
    said = []

    def answer(text, buttons=(), kind="info"):
        said.append(text)
        return "no"

    d.message = answer
    assert not d.key("p", "p", alt=True)
    assert "wrong sample rate" in said[0] and asked == []
    d.message = lambda *a, **k: "yes"
    d.key("p", "p", alt=True)
    assert len(asked) == 1


def test_a_probe_shows_while_it_runs_and_when_its_done():
    s = scan()
    pending, probes = [], {}
    d = dialog(s.inputs[0], probes, lambda device, done: pending.append(done) or True)
    d.key("p", "p", alt=True)
    assert "Asking the device..." in d.details() and 2 in d.dead
    pending[0](Probe(True, rates=(44100, 48000), sample_types=("int16",), channels=(2,)), None)
    assert d.asking is None and 2 not in d.dead
    assert any(line.startswith("Native: 44.1, 48 kHz; 16-bit; stereo") for line in d.details())
    assert s.inputs[0].key in probes


def test_a_failed_probe_says_why():
    s = scan()
    pending = []
    d = dialog(s.inputs[0], start_probe=lambda device, done: pending.append(done) or True)
    d.key("p", "p", alt=True)
    pending[0](None, RuntimeError("driver said no"))
    assert any("Couldn't ask it: driver said no" in line for line in d.details())


def test_a_busy_device_list_says_so():
    s = scan()
    d = dialog(s.inputs[0], start_probe=lambda device, done: False)
    d.key("p", "p", alt=True)
    assert d.asking is None and any("busy" in line for line in d.details())


def test_answers_already_had_are_shown_at_once():
    s = scan()
    probes = {s.inputs[0].key: Probe(True, rates=(48000,), sample_types=("int24",), channels=(2,))}
    d = dialog(s.inputs[0], probes)
    assert any("Native: 48 kHz" in line for line in d.details())


def test_ok_answers_with_the_device_and_cancel_doesnt_change_it():
    s = scan()
    d = dialog(s.inputs[0])
    d.device_list.select(1)
    d.changed(d.device_list)
    assert d.key("Return") and d.answer == "ok" and d.device.name == "Microphone (H2n)"
    d = dialog(s.inputs[0])
    assert d.key("Escape") and d.answer == "cancel"


def test_exclusive_mode_is_nowhere_on_offer():
    d = dialog()
    assert not any("xclusive" in label for label, _ in d.buttons)
    assert not any("xclusive" in row for row in d.api_list.rows + d.device_list.rows)


def test_advice_is_for_the_devices_we_learnt_it_on():
    assert "WASAPI" in advice(device("ASIO", "ZOOM H and F Series ASIO"))[0]
    assert advice(device("ASIO", "FL Studio ASIO")) == []
    assert advice(device("WASAPI", "Microphone (H2n)")) == []
    assert "reference pin" in advice(device("WDM-KS", "PC Speaker (Realtek)"))[0]


def test_only_zooms_count_as_touchy():
    assert is_touchy(device("WASAPI", "Microphone (H2n)"))
    assert is_touchy(device("ASIO", "ZOOM H and F Series ASIO"))
    assert not is_touchy(device("WASAPI", "Microphone Array"))


def test_channel_names_come_from_asio_when_it_gave_them():
    d = device("ASIO", "x", 2)
    assert channel_names(d, None) == "Left, Right"
    assert channel_names(d, Probe(True, channel_names=("In 1", "In 2"))) == "In 1, In 2"
    assert channel_names(device("WASAPI", "y", 1), None) == "Mono"
    assert channel_names(device("WASAPI", "y", 4), None) == "1, 2, 3, 4"


def test_the_details_say_what_windows_runs_it_at():
    d = device("WASAPI", "Microphone (H2n)", 4, end=endpoint("Microphone (H2n)"))
    lines = describe(d, None)
    assert lines[0] == "Windows runs it at 44,100 Hz, 24-bit, stereo (microphone, USB)."
    assert lines[1] == "Channels: 1, 2, 3, 4."


def test_it_paints():
    d = dialog()
    s = d.paint()
    assert (s.width, s.height) == (d.width, d.height)
    assert tuple(s.pixels[d.api_list.box[1] + 2, d.api_list.box[0] + 1]) == NAVY


# -- the edit box ------------------------------------------------------------------------------

def editbox(text="hello", width=200):
    return EditBox((10, 30, 10 + width - 1, 30 + EDIT_HEIGHT - 1), text)


def typed(box, text):
    for c in text:
        box.key(c, c)


def gap_x(box, gap):
    """The dialog x of a gap between characters."""
    return box.box[0] + TEXT_INSET + system_font().measure(box.text[box.left:gap])


def test_a_new_edit_box_is_all_selected_so_typing_replaces_it():
    box = editbox()
    assert box.selected_text == "hello" and box.caret == 5
    typed(box, "x")
    assert box.text == "x" and box.caret == 1 and box.selected_text == ""


def test_the_caret_keys():
    box = editbox()
    box.key("Home")
    assert box.caret == 0 and box.selected_text == ""
    assert not box.key("Left")  # the start already
    assert box.key("Right") and box.key("Right") and box.caret == 2
    typed(box, "X")
    assert box.text == "heXllo" and box.caret == 3
    assert box.key("End") and box.caret == 6
    assert not box.key("Right")
    box.key("Left")
    assert box.caret == 5


def test_left_and_right_leave_a_selection_at_its_ends():
    box = editbox()
    box.key("Left")
    assert box.caret == 0 and box.selected_text == ""
    box.select_all()
    box.key("Right")
    assert box.caret == 5 and box.selected_text == ""


def test_backspace_and_delete():
    box = editbox()
    box.key("End")
    assert box.key("BackSpace", "\x08") and box.text == "hell" and box.caret == 4
    assert not box.key("Delete", "\x7f")  # nothing after the caret
    box.key("Home")
    assert not box.key("BackSpace", "\x08")  # nothing before it
    assert box.key("Delete", "\x7f") and box.text == "ell" and box.caret == 0
    box.select_all()
    assert box.key("BackSpace", "\x08") and box.text == ""
    assert not box.key("Delete", "\x7f") and not box.key("BackSpace", "\x08")  # an empty box


def test_delete_takes_a_selection_and_stays_at_its_start():
    box = editbox()
    box.anchor, box.caret = 1, 3
    box.key("Delete", "\x7f")
    assert box.text == "hlo" and box.caret == 1


def test_anything_printable_goes_in_and_control_characters_dont():
    box = editbox("")
    typed(box, "a -1.٣")
    assert box.text == "a -1.٣"
    for key, char in (("v", "\x16"), ("Return", "\r"), ("F1", ""), ("Shift_L", "")):
        assert not box.key(key, char)
    assert box.text == "a -1.٣"


def test_ctrl_a_selects_everything():
    box = editbox()
    box.key("End")
    assert box.key("a", "\x01") and box.selected_text == "hello"


def test_a_click_puts_the_caret_in_the_nearest_gap():
    box = editbox()
    y = box.box[1] + 5
    box.press(gap_x(box, 2), y)
    assert box.caret == 2 and box.selected_text == ""
    box.press(gap_x(box, 2) + 1, y)
    assert box.caret == 2
    box.press(gap_x(box, 3) - 1, y)
    assert box.caret == 3
    box.press(box.box[2] - 1, y)  # past the end of the text
    assert box.caret == 5
    box.press(box.box[0] + 1, y)
    assert box.caret == 0


def test_a_drag_selects_even_off_the_box():
    box = editbox()
    box.press(gap_x(box, 1), 40)
    assert box.select(box.hit(gap_x(box, 4), 40)) and box.selected_text == "ell"
    assert box.select(box.hit(gap_x(box, 0), 500)) and box.selected_text == "h"
    assert not box.select(0)  # no further to go


def test_a_double_click_takes_the_word_and_isnt_ok():
    box = editbox("one two three")
    assert not box.double(gap_x(box, 5), 40)
    assert box.selected_text == "two"


def test_the_text_has_a_limit():
    box = EditBox((0, 0, 100, EDIT_HEIGHT - 1), "x" * 20, limit=10)
    assert box.text == "x" * 10
    box.key("End")
    typed(box, "y")
    assert box.text == "x" * 10
    box.key("BackSpace", "\x08")
    box.insert("abcdef")
    assert box.text == "x" * 9 + "a"
    box.select_all()
    box.insert("z" * 20)
    assert box.text == "z" * 10


def test_a_paste_takes_the_first_line_and_only_whats_printable():
    box = editbox()
    box.paste("one\ttwo\nthree")
    assert box.text == "onetwo"
    box.paste("")
    assert box.text == "onetwo"


def test_long_text_slides_to_keep_the_caret_in_view():
    font = system_font()
    box = editbox("", width=60)
    typed(box, "0123456789" * 4)
    assert box.left > 0 and font.measure(box.text[box.left:box.caret]) <= box.room
    box.key("Home")
    assert box.left == 0
    box.key("End")
    far = box.left
    assert far > 0
    box.key("BackSpace", "\x08")
    box.key("BackSpace", "\x08")
    assert box.left < far  # back along as it shortens, leaving no empty room
    box.select_all()
    box.key("BackSpace", "\x08")
    assert box.left == 0


def test_clicking_in_slid_text_counts_from_whats_showing():
    box = editbox("0123456789" * 4, width=60)
    box.press(gap_x(box, box.left + 2), 40)
    assert box.caret == box.left + 2


def test_an_edit_box_paints_its_frame_and_selection():
    box = editbox()
    s = Surface(300, 80, WHITE)
    box.paint(s, focused=True)
    x0, y0, x1, y1 = box.box
    assert tuple(s.pixels[y0, x0 + 5]) == BLACK and tuple(s.pixels[y1, x1 - 5]) == BLACK
    assert tuple(s.pixels[y0 + 3, x0 + TEXT_INSET]) == NAVY
    text = s.pixels[y0 + 3:y1 - 2, x0 + TEXT_INSET:gap_x(box, 5)]
    assert np.all(text == WHITE, axis=2).any()  # the ink, white on the navy
    assert tuple(s.pixels[y0 + 3, gap_x(box, 5) + 1]) == WHITE  # it stops with the text


def test_the_caret_shows_only_with_the_focus_and_no_selection():
    def column(box, focused):
        s = Surface(300, 80, WHITE)
        box.paint(s, focused)
        return s.pixels[box.box[1] + 3:box.box[3] - 2, gap_x(box, box.caret)]

    box = editbox()
    box.key("End")
    assert np.all(column(box, True) == BLACK)
    assert not np.all(column(box, False) == BLACK)
    box.blink()
    assert not np.all(column(box, True) == BLACK)  # the off half
    box.key("Left")
    assert np.all(column(box, True) == BLACK)  # any movement lights it again


def test_a_lost_focus_hides_the_selection():
    s = Surface(300, 80, WHITE)
    editbox().paint(s, focused=False)
    assert not np.all(s.pixels == NAVY, axis=2).any()


def test_a_blink_needs_a_repaint_only_if_there_is_a_caret():
    box = editbox()
    assert not box.blink()  # all selected: no caret
    box.key("End")
    assert box.blink()


def test_long_text_stays_inside_the_frame():
    box = editbox("W" * 100, width=60)
    s = Surface(300, 80, WHITE)
    box.paint(s, focused=False)
    assert np.all(s.pixels[:, box.box[2] + 1:] == 255)


# -- an edit box in a dialog --------------------------------------------------------------------

def dialog_with_edit():
    d = Dialog(None, 1, "t", 200, 100, [("&Yes", "yes"), ("&No", "no")], "no")
    d.boxes = [(120, 60, 180, 80), (120, 90, 180, 110)]
    d.lists = [EditBox((20, 40, 100, 40 + EDIT_HEIGHT - 1), "")]
    return d


def test_with_the_focus_a_letter_is_typed_and_presses_nothing():
    d = dialog_with_edit()
    assert not d.key("y", "y") and not d.key("space", " ") and not d.key("n", "n")
    assert d.lists[0].text == "y n"
    assert d.answer == "no"


def test_without_the_focus_a_letter_is_a_mnemonic_again():
    d = dialog_with_edit()
    d.key("Tab")
    assert d.focused_button == 0
    assert d.key("y", "y") and d.answer == "yes"
    assert d.lists[0].text == ""


def test_alt_still_reaches_a_button_from_the_edit_box():
    d = dialog_with_edit()
    assert d.key("y", "y", alt=True) and d.answer == "yes"
    assert d.lists[0].text == ""


def test_a_double_click_in_the_edit_box_doesnt_press_the_default_button():
    d = dialog_with_edit()
    d.lists[0].insert("two words")
    x, y = d.lists[0].box[0] + TEXT_INSET + 1, d.lists[0].box[1] + 5
    assert not d.double(x, y)
    assert d.lists[0].selected_text == "two"


def test_the_mouse_works_an_edit_box_through_the_dialog():
    d = dialog_with_edit()
    box = d.lists[0]
    box.insert("hello")
    d.focus = 1
    y = box.box[1] + 5
    d.press(gap_x(box, 1), y)
    assert d.focused_list is box and box.caret == 1
    assert d.motion(gap_x(box, 3), y) and box.selected_text == "el"
    assert not d.motion(gap_x(box, 3), y)
    assert not d.release(gap_x(box, 3), y)
    assert d.held is None and box.selected_text == "el"
    assert not d.motion(gap_x(box, 5), y)  # the button's up: no more dragging


def test_the_wheel_over_an_edit_box_does_nothing():
    d = dialog_with_edit()
    d.wheel(30, 45, 2)
    assert d.lists[0].left == 0


def test_only_a_focused_edit_box_blinks():
    d = dialog_with_edit()
    assert d.blink()
    d.key("Tab")
    assert not d.blink()
    assert not OutputFormatDialog(None, 1).blink()  # a list has no caret


# -- the input box ------------------------------------------------------------------------------

def inputbox(text="250", check=None, prompt="Delay in milliseconds (1 to 5000):"):
    return InputBox(None, 1, "Add Echo", prompt, text, check)


def test_it_lays_out_as_visual_basics_did():
    d = inputbox()
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = d.boxes
    ex0, ey0, ex1, ey1 = d.edit.box
    px, py = d.prompt_at
    assert (ax0, ax1) == (bx0, bx1) and ay1 < by0  # OK above Cancel, the same width
    assert px < ax0 and py <= ay0  # the prompt to their left, from the top
    assert ey0 > by1 and ex0 == px and ex1 == ax1  # the edit box under them all, across
    assert ey1 < d.height - 5 and ax1 < d.width - 5  # inside the frame


def test_a_long_prompt_wraps_beside_the_buttons_and_pushes_the_edit_box_down():
    short = inputbox()
    d = inputbox(prompt="word " * 80)
    assert len(d.prompt) > 3
    assert all(system_font().measure(line) <= d.PROMPT_W for line in d.prompt)
    assert d.edit.box[1] >= d.prompt_at[1] + 16 * len(d.prompt)
    assert d.height > short.height


def test_it_opens_on_the_edit_box_with_the_text_selected():
    d = inputbox()
    assert d.focused_list is d.edit and d.edit.selected_text == "250"
    assert d.answer == "cancel" and d.result is None


def test_enter_is_ok_and_gives_the_text():
    d = inputbox()
    typed(d.edit, "750")
    assert d.key("Return", "\r") and d.answer == "ok" and d.result == "750"


def test_esc_is_cancel_and_gives_none():
    d = inputbox()
    typed(d.edit, "750")
    assert d.key("Escape") and d.result is None


def test_the_buttons_work_with_the_mouse():
    for button, result in ((0, "250"), (1, None)):
        d = inputbox()
        x0, y0, _, _ = d.boxes[button]
        d.press(x0 + 3, y0 + 3)
        assert d.release(x0 + 3, y0 + 3) and d.result == result


def test_tab_goes_round_and_back_into_the_edit_box_selects_it():
    d = inputbox()
    d.edit.key("End")
    d.key("Tab")
    assert d.focused_button == 0
    d.key("Tab")
    assert d.focused_button == 1
    d.key("Tab")
    assert d.focused_list is d.edit and d.edit.selected_text == "250"
    d.key("ISO_Left_Tab")
    assert d.focused_button == 1


def test_enter_on_cancel_cancels():
    d = inputbox()
    d.key("Tab"), d.key("Tab")
    assert d.key("Return", "\r") and d.result is None


def test_a_check_that_passes_answers():
    seen = []
    d = inputbox(check=lambda text: seen.append(text))
    typed(d.edit, "42")
    assert d.key("Return", "\r") and d.result == "42" and seen == ["42"]


def test_a_refusal_says_why_then_comes_back_with_the_text_selected():
    said = []
    d = inputbox(check=lambda text: None if text == "7" else "Not that one.")
    d.message = lambda text, kind="info": said.append((text, kind))
    typed(d.edit, "12")
    d.edit.key("Left")
    assert not d.key("Return", "\r")
    assert said == [("Not that one.", "warning")]
    assert d.focused_list is d.edit and d.edit.selected_text == "12" and d.answer == "cancel"
    typed(d.edit, "7")  # it replaces the refused text
    assert d.key("Return", "\r") and d.result == "7"


def test_a_refusal_after_clicking_ok_gives_the_focus_back_to_the_edit_box():
    d = inputbox(check=lambda text: "No.")
    d.message = lambda text, kind="info": None
    x0, y0, _, _ = d.boxes[0]
    d.press(x0 + 3, y0 + 3)
    assert d.focused_button == 0
    assert not d.release(x0 + 3, y0 + 3)
    assert d.focused_list is d.edit and d.edit.selected_text == "250" and d.result is None


def test_cancel_doesnt_check():
    def never(text):
        raise AssertionError("cancel ran the check")

    d = inputbox(check=never)
    assert d.key("Escape") and d.result is None
    d = inputbox(check=never)
    x0, y0, _, _ = d.boxes[1]
    d.press(x0 + 3, y0 + 3)
    assert d.release(x0 + 3, y0 + 3) and d.result is None


def test_cut_copy_and_paste():
    d = inputbox()
    board = []
    d.to_clipboard = board.append
    d.clipboard = lambda: "99\nignored"
    assert not d.key("c", "\x03")
    assert board == ["250"] and d.edit.text == "250"
    assert not d.key("x", "\x18")
    assert board == ["250", "250"] and d.edit.text == ""
    assert not d.key("v", "\x16")
    assert d.edit.text == "99"
    assert not d.key("c", "\x03") and len(board) == 2  # nothing selected, nothing copied


def test_the_clipboard_keys_belong_to_the_edit_box():
    d = inputbox()
    d.to_clipboard = d.clipboard = None  # calling either from a button would fail
    d.key("Tab")
    assert not d.key("v", "\x16") and not d.key("c", "\x03")
    assert d.edit.text == "250"


def test_the_input_box_paints():
    d = inputbox()
    s = d.paint()
    assert (s.width, s.height) == (d.width, d.height)
    x, y = d.prompt_at
    assert np.all(s.pixels[y:y + 16, x:x + d.PROMPT_W] == BLACK, axis=2).any()  # the prompt
    x0, y0, x1, y1 = d.edit.box
    assert tuple(s.pixels[y0, x0]) == BLACK and tuple(s.pixels[y1, x1]) == BLACK
    assert tuple(s.pixels[y0 + 3, x0 + TEXT_INSET]) == NAVY  # selected on opening
    ax0, ay0, ax1, ay1 = d.boxes[0]
    assert tuple(s.pixels[ay0 + 3, ax0 - 1]) == BLACK  # OK's the default, with its doubled border


# -- the number check ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["0", "7", "250", "5000", "007", "12345678901234567890"])
def test_digits_are_a_whole_number(text):
    assert is_whole_number(text)


@pytest.mark.parametrize("text", ["", " ", "-5", "+5", "1.5", "1,000", "1e3", "0x10", " 5", "5 ",
                                  "12a", "٣", "۳", "३", "１２", "²",
                                  "½", "12٣"])
def test_nothing_else_is(text):
    assert not is_whole_number(text)
