"""Sound Recorder's window: 3.1's face and menus on the Phase 2 engine.

The App owns the Tk root and everything shown in it, and turns mouse and
keyboard into commands: the five buttons, the scrollbar, the menus. Audio
work stays off the UI thread (device scans, capture, playback each run on
their own), and what those threads report comes back through an inbox that
the UI drains on its tick, since Tk may only be touched from its own thread.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from .. import __version__
from . import face as F
from .audio import DeviceList, PlaybackError, Player
from .dialog import MessageBox
from .document import Document
from .menus import SEPARATOR, Item, Menu, Tracker, item_at, paint_popup
from .window import AppWindow, PopupWindow, default_zoom, dpi_aware

TRACE_SECONDS = 0.012  # the stretch of sound the wave box shows
STEP_SECONDS = 0.1     # one click on a scroll arrow
PAGE_SECONDS = 1.0     # one click in the scrollbar's trough
TICK_MS = 40           # redraws while recording or playing
IDLE_TICK_MS = 100
REPEAT_DELAY_MS, REPEAT_MS = 400, 60
GIL_SWITCH_SECONDS = 0.0005

OPEN_TYPES = [("Sounds", "*.wav *.flac *.mp3 *.ogg *.oga *.opus *.aif *.aiff *.aifc *.au *.snd "
                         "*.caf *.w64 *.rf64 *.voc"), ("All files", "*.*")]
SAVE_TYPES = [("Wave files", "*.wav"), ("FLAC", "*.flac"), ("MP3", "*.mp3"),
              ("Ogg Vorbis", "*.ogg"), ("Opus", "*.opus"), ("AIFF", "*.aiff"),
              ("All files", "*.*")]


def build_menus() -> list[Menu]:
    """The control menu, then the menu bar's, as in 3.1 plus our Device menu.
    Edit and Effects come in Phase 4, the Device dialogs in Phase 5."""
    return [
        Menu(None, [Item("&Restore", "restore", enabled=False), Item("&Move", "move"),
                    Item("&Size", "size", enabled=False), Item("Mi&nimize", "minimize"),
                    Item("Ma&ximize", "maximize", enabled=False), SEPARATOR,
                    Item("&Close", "close", "Alt+F4"), SEPARATOR,
                    Item("S&witch To...", "switch", "Ctrl+Esc")]),
        Menu("&File", [Item("&New", "new"), Item("&Open...", "open"), Item("&Save", "save"),
                       Item("Save &As...", "saveas"), Item("&Revert...", "revert"), SEPARATOR,
                       Item("E&xit", "exit")]),
        Menu("&Edit", [Item("&Insert File...", "insert", enabled=False),
                       Item("&Mix with File...", "mix", enabled=False), SEPARATOR,
                       Item("Delete &Before Current Position", "delete-before", enabled=False),
                       Item("Delete &After Current Position", "delete-after", enabled=False)]),
        Menu("Effect&s", [Item("&Increase Volume (by 25%)", "louder", enabled=False),
                          Item("&Decrease Volume", "quieter", enabled=False), SEPARATOR,
                          Item("Increase &Speed (by 100%)", "faster", enabled=False),
                          Item("Decrease S&peed", "slower", enabled=False), SEPARATOR,
                          Item("&Add Echo", "echo", enabled=False),
                          Item("&Reverse", "reverse", enabled=False)]),
        Menu("&Device", [Item("&Recording Device...", "device", enabled=False),
                         Item("&Output Format...", "format", enabled=False), SEPARATOR,
                         Item("Re&fresh Devices", "refresh")]),
        Menu("&Help", [Item("&About Sound Recorder...", "about")]),
    ]


class App:
    def __init__(self, zoom: int | None = None, device: str | None = None, api: str | None = None):
        # Capture callbacks need the GIL, the H2n's over ASIO every 1.3 ms, and
        # Python lets a busy thread keep it for 5 ms. Painting at 25 fps made a
        # stand-in callback up to 2.6 ms late; asking every 0.5 ms, 1.5 at worst.
        sys.setswitchinterval(GIL_SWITCH_SECONDS)
        dpi_aware()
        self.root = root = tk.Tk()
        root.withdraw()
        root.title("Sound Recorder")
        self.zoom = zoom or default_zoom()
        self.window = AppWindow(root, self.zoom)
        self.popup = PopupWindow(root, self.zoom)
        self.menus = build_menus()
        self.tracker = Tracker(self.menus)
        self.face = F.FaceState(menus=tuple(m.title for m in self.menus[1:]))
        self.doc = Document()
        self.position = 0          # frames, while stopped
        self.recorder = None
        self.record_at = 0         # where the running recording goes in the sound
        self.player: Player | None = None
        self.wanted = (device, api)
        self.device = None         # the capture device recordings come from
        self.device_problem: str | None = None
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self.devices = DeviceList(self._inbox.put)
        self._rescan_when_idle = False
        self._watcher = None
        self._held = None          # ("button", name), ("minimize",), ("scroll", what) or ("thumb", grab)
        self._repeat = None
        self._alt_down = self._alt_used = False
        self._redraw_pending = False
        self._closing = False

        self._bind()
        self._sync()
        self._render()
        root.update_idletasks()
        self.popup.prepare()  # mapped off screen before the main window, which then ends up active
        w, h = F.WIDTH * self.zoom, F.HEIGHT * self.zoom
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", lambda: self.command("exit"))
        root.deiconify()
        root.update_idletasks()
        self.window.make_app_window()
        self.devices.refresh(then=self._devices_found)
        self._start_watcher()
        root.after(TICK_MS, self._tick)

    def run(self) -> None:
        self.root.mainloop()

    # -- state to pixels ----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self.recorder is not None or self.player is not None

    def _sync(self) -> None:
        """Bring the face and the menus up to date with the sound and what's running."""
        f, doc = self.face, self.doc
        rate = doc.rate or 1
        if self.recorder is not None:
            rate = self.recorder.rate
            at = self.record_at + self.recorder.stats.frames_out
            length = max(doc.frames, at)
        elif self.player is not None:
            at, length = self.player.position, doc.frames
        else:
            at, length = self.position, doc.frames
        f.position, f.length = at / rate, length / rate
        f.thumb = at / length if length else 0.0
        f.title = f"Sound Recorder - {doc.name}"
        if self.recorder is not None:
            f.status = "Recording"
        elif self.player is not None:
            f.status = "Playing"
        elif self.device is None and self.devices.busy:
            f.status = "Finding devices..."
        else:
            f.status = "Stopped"
        idle = not self.busy
        f.enabled = {"rewind": idle and at > 0, "forward": idle and at < length,
                     "play": idle and length > 0, "stop": not idle,
                     "record": idle and (self.device is not None or not self.devices.busy)}
        f.trace = self._trace(at)
        file_menu, device_menu = self.menus[1], self.menus[4]
        file_menu.item("save").enabled = file_menu.item("saveas").enabled = doc.take is not None
        file_menu.item("revert").enabled = doc.path is not None and doc.dirty
        device_menu.item("refresh").enabled = idle and not self.devices.busy

    def _trace(self, at: int):
        """What the wave box shows: the sound at the position, or what's coming in."""
        columns = F.WAVE[2] - F.WAVE[0] - 1
        if self.recorder is not None:
            step = max(1, round(self.recorder.rate * TRACE_SECONDS / columns))
            data = self.recorder.recent(columns * step)
        elif self.doc.take is not None:
            step = max(1, round(self.doc.rate * TRACE_SECONDS / columns))
            data = self.doc.read(at, columns * step)
        else:
            return None
        if not len(data):
            return None
        return data.mean(axis=1)[::step][:columns]

    def redraw(self) -> None:
        if not self._redraw_pending:
            self._redraw_pending = True
            self.root.after_idle(self._render)

    def _render(self) -> None:
        self._redraw_pending = False
        if self._closing:
            return
        self.face.menu_highlight = self.tracker.bar_highlight
        self.face.control_box_down = self.tracker.control_open and self.tracker.opened
        self.window.show(F.paint(self.face))
        menu = self.tracker.popup
        if menu is None:
            self.popup.hide()
            return
        surface = paint_popup(menu, self.tracker.item)
        if self.tracker.control_open:
            ax, ay = F.CONTROL_BOX[0] - 1, F.CAPTION[3] + 1
        else:
            ax, ay = F.title_box(self.face.menus, self.tracker.bar_highlight)[0], F.MENU_BAR[3] + 1
        z = self.zoom
        x = self.root.winfo_rootx() + ax * z
        y = self.root.winfo_rooty() + ay * z
        x = min(x, self.root.winfo_screenwidth() - surface.width * z)
        self.popup.place(surface, max(x, 0), y)

    # -- the tick: what other threads said, and running displays ---------------------

    def _tick(self) -> None:
        if self._closing:
            return
        while True:
            try:
                job = self._inbox.get_nowait()
            except queue.Empty:
                break
            job()
        if self.recorder is not None:
            rec = self.recorder
            if rec.failure is not None or rec.stats.clock_problem():
                self.stop()
        if self.player is not None and self.player.finished.is_set():
            self._stop_playing()
        if self.busy:
            self._sync()
            self._render()
        self.root.after(TICK_MS if self.busy else IDLE_TICK_MS, self._tick)

    # -- devices --------------------------------------------------------------------

    def _devices_found(self) -> None:
        from ..cli import choose_device

        if self.devices.error is not None:
            self.device, self.device_problem = None, f"Couldn't list the devices: {self.devices.error}"
        else:
            text, api = self.wanted
            try:
                self.device, self.device_problem = choose_device(self.devices.scan.inputs, text, api), None
            except ValueError as e:
                self.device, self.device_problem = None, str(e)
        self._sync()
        self.redraw()

    def _start_watcher(self) -> None:
        try:
            from ..hotplug import DeviceWatcher

            self._watcher = DeviceWatcher(lambda change: self._inbox.put(self._hotplug))
            self._watcher.start()
        except OSError:
            self._watcher = None  # no hot-plug: Refresh Devices still works

    def _hotplug(self) -> None:
        if self.busy:
            self._rescan_when_idle = True  # PortAudio can't rescan with a stream open
        else:
            self.devices.refresh(rescan=True, then=self._devices_found)

    # -- recording and playback -------------------------------------------------------

    def start_recording(self) -> None:
        if self.busy:
            return
        if self.device is None:
            self.message(self.device_problem or "Still looking for devices: try again in a moment.",
                         kind="warning")
            return
        from ..capture import CaptureError, open_capture
        from ..cli import native_rate, plan_channels
        from ..engine import Recorder

        try:
            capture_rate = native_rate(self.device)
            capture_channels, channels, pick = plan_channels(self.device.channels, self.doc.channels)
            rec = Recorder(open_capture(self.device, capture_rate, capture_channels),
                           self.doc.rate or capture_rate, channels, pick,
                           meta={"device": self.device.key,
                                 "target": str(self.doc.path) if self.doc.path else None})
            rec.start()
        except (CaptureError, ValueError, OSError, RuntimeError) as e:
            self.message(f"Can't record from {self.device.name}.\n\n{e}", kind="warning")
            return
        self.recorder, self.record_at = rec, self.position
        self._sync()
        self.redraw()

    def _stop_recording(self) -> None:
        rec, self.recorder = self.recorder, None
        take = rec.stop()
        s = rec.stats
        frames = take.frames
        try:
            self.doc.splice(self.record_at, take)
        except (OSError, ValueError) as e:
            take.release()
            self.message(f"The recording couldn't be added to the sound: {e}\n\n"
                         "It's kept: `sound-recorder recover` lists it.", kind="warning")
        else:
            self.position = self.record_at + frames
        problems = []
        if rec.failure is not None:
            problems.append(f"Recording stopped: {rec.failure}")
        clock = s.clock_problem()
        if clock:
            problems.append(f"Recording stopped: {clock}.")
        lost = s.overflows + s.discontinuities
        if lost:
            problems.append(f"Audio was lost {lost} time{'s' if lost > 1 else ''} while recording "
                            f"({s.overflows} overflows, {s.discontinuities} gaps).")
        if problems:
            self.message("\n\n".join(problems), kind="warning")
        if self._rescan_when_idle:
            self._rescan_when_idle = False
            self.devices.refresh(rescan=True, then=self._devices_found)

    def start_playing(self) -> None:
        if self.busy or self.doc.take is None or not self.doc.frames:
            return
        out = self.devices.default_output()
        if out is None:
            self.message("No playback device found.", kind="warning")
            return
        if self.position >= self.doc.frames:
            self.position = 0
        player = Player(self.doc.take, out, self.position)
        try:
            player.start()
        except PlaybackError as e:
            self.message(str(e), kind="warning")
            return
        self.player = player
        self._sync()
        self.redraw()

    def _stop_playing(self) -> None:
        player, self.player = self.player, None
        player.stop()
        self.position = self.doc.frames if player.sent >= player.end else player.position
        if player.failure is not None:
            self.message(f"Playback stopped: {player.failure}", kind="warning")
        if self._rescan_when_idle:
            self._rescan_when_idle = False
            self.devices.refresh(rescan=True, then=self._devices_found)
        self._sync()
        self.redraw()

    def stop(self) -> None:
        if self.recorder is not None:
            self._stop_recording()
        if self.player is not None:
            self._stop_playing()
        self._sync()
        self.redraw()

    def seek(self, frame: float) -> None:
        if self.busy:
            return
        self.position = int(min(max(frame, 0), self.doc.frames))
        self._sync()
        self.redraw()

    def press_button(self, name: str) -> None:
        {"rewind": lambda: self.seek(0), "forward": lambda: self.seek(self.doc.frames),
         "play": self.start_playing, "stop": self.stop, "record": self.start_recording}[name]()

    # -- commands -------------------------------------------------------------------

    def command(self, name: str) -> None:
        handler = getattr(self, "cmd_" + name.replace("-", "_"), None)
        if handler is not None:
            handler()

    def message(self, text: str, kind: str = "info", title: str = "Sound Recorder") -> None:
        self.ask(text, [("OK", "ok")], kind=kind, title=title)

    def ask(self, text: str, buttons, kind: str = "question", title: str = "Sound Recorder",
            cancel: str | None = None) -> str:
        self.tracker.close()
        self.redraw()
        r = self.root
        box = MessageBox(r, self.zoom, title, text, buttons, kind=kind, cancel=cancel)
        return box.run((r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()))

    def _save_changes(self) -> bool:
        """Offer to save a changed sound. False if the user cancels."""
        if not self.doc.dirty or self.doc.take is None:
            return True
        answer = self.ask(f"Do you want to save the changes to {self.doc.name}?",
                          [("&Yes", "yes"), ("&No", "no"), ("Cancel", "cancel")])
        if answer == "yes":
            return self.cmd_save()
        return answer == "no"

    def _replace(self, doc: Document) -> None:
        self.doc.close()
        self.doc, self.position = doc, 0
        self._sync()
        self.redraw()

    def cmd_new(self) -> None:
        self.stop()
        if self._save_changes():
            self._replace(Document())

    def cmd_open(self) -> None:
        self.stop()
        if not self._save_changes():
            return
        name = filedialog.askopenfilename(parent=self.root, title="Open", filetypes=OPEN_TYPES)
        if not name:
            return
        try:
            doc = Document.open(name)
        except Exception as e:  # libsndfile says why in its own words
            self.message(f"Can't open {Path(name).name}.\n\n{e}", kind="warning")
            return
        self._replace(doc)

    def cmd_save(self) -> bool:
        self.stop()
        if self.doc.take is None:
            return True
        if self.doc.path is None or self.doc.spec is None:
            return self.cmd_saveas()
        return self._write(self.doc.path, self.doc.spec)

    def cmd_saveas(self) -> bool:
        from ..output import spec_for

        self.stop()
        if self.doc.take is None:
            return True
        start = self.doc.path
        name = filedialog.asksaveasfilename(
            parent=self.root, title="Save As", filetypes=SAVE_TYPES, defaultextension=".wav",
            initialdir=str(start.parent) if start else None,
            initialfile=start.name if start else "untitled.wav")
        if not name:
            return False
        try:
            spec = spec_for(name)
        except ValueError as e:
            self.message(f"Can't save {Path(name).name}: {e}.", kind="warning")
            return False
        return self._write(Path(name), spec)

    def _write(self, path: Path, spec) -> bool:
        try:
            self.doc.save(path, spec)
        except Exception as e:  # the encoder's reason: MP3 can't go past 48 kHz, and so on
            self.message(f"Can't save {path.name}.\n\n{e}", kind="warning")
            return False
        self._sync()
        self.redraw()
        return True

    def cmd_revert(self) -> None:
        self.stop()
        if self.doc.path is None or not self.doc.dirty:
            return
        answer = self.ask(f"Go back to the saved {self.doc.name}, and lose the changes since?",
                          [("&Yes", "yes"), ("&No", "no")], kind="question")
        if answer != "yes":
            return
        try:
            doc = Document.open(self.doc.path)
        except Exception as e:
            self.message(f"Can't open {self.doc.name}.\n\n{e}", kind="warning")
            return
        self._replace(doc)

    def cmd_exit(self) -> None:
        if self._closing:
            return
        self.stop()
        if not self._save_changes():
            return
        self._closing = True
        self.doc.close()
        self.devices.stop()
        if self._watcher is not None:
            self._watcher.stop()
        self.root.destroy()

    cmd_close = cmd_exit

    def cmd_refresh(self) -> None:
        if not self.busy:
            self.devices.refresh(rescan=True, then=self._devices_found)
            self._sync()
            self.redraw()

    def cmd_about(self) -> None:
        source = self.device.key if self.device is not None else "no device yet"
        self.message(f"Sound Recorder {__version__}\n\nA Windows 3.1 sound recorder, "
                     f"modernized.\n\nRecording from {source}.",
                     title="About Sound Recorder", kind="info")

    def cmd_move(self) -> None:
        self.window.keyboard_move()

    def cmd_minimize(self) -> None:
        self.window.minimize()

    def cmd_switch(self) -> None:
        os.startfile("shell:::{3080F90E-D7AD-11D9-BD98-0000947B0257}")  # Task View

    # -- mouse ------------------------------------------------------------------------

    def _bind(self) -> None:
        for label in (self.window.label, self.popup.label):
            label.bind("<ButtonPress-1>", self._press)
            label.bind("<Double-Button-1>", self._double)
            label.bind("<Motion>", self._motion)
            label.bind("<B1-Motion>", self._motion)
            label.bind("<ButtonRelease-1>", self._release)
        self.root.bind("<KeyPress>", self._key)
        self.root.bind("<KeyRelease>", self._key_up)
        self.root.bind("<FocusIn>", lambda e: self.root.after(1, self._check_active))
        self.root.bind("<FocusOut>", lambda e: self.root.after(1, self._check_active))

    def _check_active(self) -> None:
        if self._closing:
            return
        try:
            focus = self.root.focus_get()  # None while another program has the focus
            active = focus is not None and focus.winfo_toplevel() is self.root
        except (KeyError, tk.TclError):
            active = False
        if active != self.face.active:
            self.face.active = active
            if not active:
                self.tracker.close()
            self.redraw()

    def _where(self, x_root: int, y_root: int):
        """For the menus: what's under the pointer."""
        if self.tracker.opened and self.popup.visible and self.popup.contains(x_root, y_root):
            x, y = self.popup.local(x_root, y_root)
            return ("item", item_at(self.tracker.popup, x, y))
        if self.window.contains(x_root, y_root):
            hit = F.hit(*self.window.local(x_root, y_root), self.face)
            if hit is not None and hit[0] == "menu":
                return ("title", hit[1])
            if hit is not None and hit[0] == "control":
                return ("control",)
        return None

    def _face_hit(self, e):
        if not self.window.contains(e.x_root, e.y_root):
            return None, None
        x, y = self.window.local(e.x_root, e.y_root)
        return F.hit(x, y, self.face), x

    def _press(self, e) -> None:
        self._alt_used = True
        where = self._where(e.x_root, e.y_root)
        if self.tracker.active or (where is not None and where[0] in ("title", "control")):
            self.tracker.press(where)
            self.redraw()
            return
        hit, x = self._face_hit(e)
        if hit is None:
            return
        kind, what = hit
        if kind == "caption":
            # Where on the window the caption was grabbed; _motion moves it.
            self._held = ("drag", e.x_root - self.root.winfo_rootx(),
                          e.y_root - self.root.winfo_rooty())
        elif kind == "minimize":
            self._held = ("minimize",)
            self.face.minimize_down = True
        elif kind == "button" and self.face.enabled.get(what):
            self._held = ("button", what)
            self.face.pressed = what
        elif kind == "scroll" and not self.busy and self.doc.frames:
            if what == "thumb":
                self._held = ("thumb", x - F.thumb_left(self.face.thumb))
            else:
                self._held = ("scroll", what)
                self.face.scroll_down = what if what in ("left", "right") else None
                self._scroll(what)
                self._repeat = self.root.after(REPEAT_DELAY_MS, self._scroll_again)
        self.redraw()

    def _double(self, e) -> None:
        hit, _ = self._face_hit(e)
        if hit is not None and hit[0] == "control":
            self.tracker.close()
            self.command("close")  # 3.1: double-click the control-menu box to close
        else:
            self._press(e)

    def _motion(self, e) -> None:
        if self.tracker.opened or self.tracker.tracking:
            before = (self.tracker.current, self.tracker.item, self.tracker.opened)
            self.tracker.motion(self._where(e.x_root, e.y_root))
            if before != (self.tracker.current, self.tracker.item, self.tracker.opened):
                self.redraw()
            return
        if self._held is None:
            return
        if self._held[0] == "drag":
            self.window.move_to(e.x_root - self._held[1], e.y_root - self._held[2])
            return
        hit, x = self._face_hit(e)
        if self._held[0] == "button":
            down = self._held[1] if hit == ("button", self._held[1]) else None
            if down != self.face.pressed:
                self.face.pressed = down
                self.redraw()
        elif self._held[0] == "minimize":
            down = hit == ("minimize", None)
            if down != self.face.minimize_down:
                self.face.minimize_down = down
                self.redraw()
        elif self._held[0] == "thumb" and x is not None:
            self.seek(F.fraction_at(x - self._held[1]) * self.doc.frames)

    def _release(self, e) -> None:
        if self.tracker.tracking:
            command = self.tracker.release(self._where(e.x_root, e.y_root))
            self.redraw()
            if command:
                self.command(command)
            return
        held, self._held = self._held, None
        if held is None:
            return
        hit, _ = self._face_hit(e)
        if held[0] == "button":
            self.face.pressed = None
            if hit == ("button", held[1]):
                self.press_button(held[1])
        elif held[0] == "minimize":
            self.face.minimize_down = False
            if hit == ("minimize", None):
                self.window.minimize()
        elif held[0] == "scroll":
            self.face.scroll_down = None
            if self._repeat is not None:
                self.root.after_cancel(self._repeat)
                self._repeat = None
        self.redraw()

    def _scroll(self, what: str) -> None:
        if not self.doc.rate:
            return
        seconds = {"left": -STEP_SECONDS, "right": STEP_SECONDS,
                   "page-left": -PAGE_SECONDS, "page-right": PAGE_SECONDS}[what]
        self.seek(self.position + seconds * self.doc.rate)

    def _scroll_again(self) -> None:
        if self._held is not None and self._held[0] == "scroll":
            self._scroll(self._held[1])
            self._repeat = self.root.after(REPEAT_MS, self._scroll_again)

    # -- keyboard ---------------------------------------------------------------------

    def _key(self, e):
        sym = e.keysym
        if sym in ("Alt_L", "Alt_R"):
            if not self._alt_down:
                self._alt_down, self._alt_used = True, False
            return "break"
        if self._alt_down:
            self._alt_used = True
            if sym == "F4":
                self.command("close")
            elif self.tracker.alt_key(" " if sym == "space" else e.char):
                self.redraw()
            return "break"
        if sym == "F10":
            self.tracker.alt_tap()
            self.redraw()
            return "break"
        if self.tracker.active:
            _, command = self.tracker.key(sym, e.char)
            self.redraw()
            if command:
                self.command(command)
            return "break"
        if sym in ("Tab", "ISO_Left_Tab"):
            self._move_focus(-1 if sym == "ISO_Left_Tab" or e.state & 1 else 1)
            return "break"
        if sym in ("space", "Return") and self.face.focus and self.face.enabled.get(self.face.focus):
            self.press_button(self.face.focus)
            return "break"
        if sym == "Escape" and self.busy:
            self.stop()
            return "break"
        return None

    def _key_up(self, e):
        if e.keysym in ("Alt_L", "Alt_R"):
            if self._alt_down and not self._alt_used:
                self.tracker.alt_tap()
                self.redraw()
            self._alt_down = False
            return "break"
        return None

    def _move_focus(self, step: int) -> None:
        names = F.BUTTON_NAMES
        start = names.index(self.face.focus) if self.face.focus in names else (-1 if step > 0 else 0)
        for i in range(1, len(names) + 1):
            name = names[(start + step * i) % len(names)]
            if self.face.enabled.get(name):
                self.face.focus = name
                break
        self.redraw()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sound-recorder gui",
                                     description="The Sound Recorder window.")
    parser.add_argument("--zoom", type=int, choices=(1, 2, 3, 4),
                        help="pixel size (default: 1 at 100%% display scaling, 2 from 150%%)")
    parser.add_argument("--device", metavar="TEXT",
                        help="record from the device whose name contains TEXT "
                             "(default: Windows' default recording device)")
    parser.add_argument("--api", help="WASAPI, Loopback, ASIO, WDM-KS, DirectSound or MME")
    args = parser.parse_args(argv)
    App(args.zoom, args.device, args.api).run()
    return 0
