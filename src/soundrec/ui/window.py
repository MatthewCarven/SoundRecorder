"""Tk windows that show a painted Surface, and the Win32 calls they need.

The app window is `overrideredirect`, so Windows draws no frame and we draw
3.1's. That costs what Windows' frame gave for free: Tk turns such a window
into a tool window, which has no taskbar button, isn't in Alt+Tab and can't
be minimized. Win32 styles put those back (WS_EX_APPWINDOW in place of
WS_EX_TOOLWINDOW, WS_MINIMIZEBOX), and the window is minimized with ShowWindow.

Dragging the caption moves the window ourselves, a SetWindowPos per mouse
move. Handing the drag to Windows (WM_NCLBUTTONDOWN on HTCAPTION) crashed
the app: Windows' move loop ran inside that call, Tk serviced its timers
during it, and tkinter, called back while Python was already in a callback,
aborted ("PyEval_RestoreThread ... thread state is NULL"). Never start a
Windows modal loop synchronously from a Tk callback; PostMessage it instead,
so it runs from Tk's own event loop (the control menu's Move does).

Menus open in a second, borderless window that should never take the focus
(WS_EX_NOACTIVATE), so the app's caption stays active and its keys keep
coming while a menu is down, as in 3.1. Tk maps it once (Tk activates any
window it maps); after that Windows shows and hides it, behind Tk's back,
and a hidden window can't be handed the activation. On Matthew's laptop the
popup still ended up the active window once, and the app hands it back
whenever that happens (App._check_active).
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_MINIMIZEBOX = 0x00020000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_SYSCOMMAND = 0x0112
SC_MOVE = 0xF010
SM_YVIRTUALSCREEN = 77
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
SWP_SHOWWINDOW = 0x40

HWND_TOPMOST = wintypes.HWND(-1)
OFF_SCREEN = -20000

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetParent.restype = wintypes.HWND
_user32.GetParent.argtypes = [wintypes.HWND]
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def foreground() -> int:
    """The window Windows has active (keyboard input goes there)."""
    return _user32.GetForegroundWindow() or 0


def activate(hwnd: int) -> None:
    _user32.SetForegroundWindow(hwnd)


def dpi_aware() -> None:
    """Draw at the screen's real pixels: without this a 150% screen gets the
    window stretched by 1.5, smearing every pixel. Call before Tk starts."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per monitor
    except (AttributeError, OSError):
        try:
            _user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def screen_dpi() -> int:
    try:
        return _user32.GetDpiForSystem()
    except AttributeError:
        return 96


def default_zoom(dpi: int | None = None) -> int:
    """Whole-number scaling: 2 at 100% (96 dpi), Matthew's pick (3.1's own
    317 x 169 is small on a 1080p screen); 3 at 150%, 4 at 200%."""
    return max(1, round(2 * (dpi or screen_dpi()) / 96))


class PixelWindow:
    """A borderless Tk toplevel showing a Surface at `zoom`."""

    def __init__(self, top: tk.Misc, zoom: int):
        self.top = top
        self.zoom = zoom
        top.overrideredirect(True)
        self.photo = tk.PhotoImage(master=top)
        self.label = tk.Label(top, image=self.photo, borderwidth=0, highlightthickness=0)
        self.label.pack()
        self.size = (0, 0)

    def show(self, surface) -> None:
        self.photo.configure(data=surface.ppm(self.zoom), format="PPM")
        self.size = (surface.width, surface.height)

    @property
    def hwnd(self) -> int:
        """The frame Windows knows, around Tk's own child window."""
        return _user32.GetParent(self.top.winfo_id())

    def local(self, x_root: int, y_root: int) -> tuple[int, int]:
        """Screen pixels to the surface's (unzoomed) pixels."""
        return ((x_root - self.top.winfo_rootx()) // self.zoom,
                (y_root - self.top.winfo_rooty()) // self.zoom)

    def contains(self, x_root: int, y_root: int) -> bool:
        x, y = self.local(x_root, y_root)
        return 0 <= x < self.size[0] and 0 <= y < self.size[1]

    def move_to(self, x_root: int, y_root: int) -> None:
        """Put the window's top-left corner here, keeping the caption below the
        top of the screen so it can always be grabbed again."""
        top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        _user32.SetWindowPos(self.hwnd, None, x_root, max(y_root, top), 0, 0,
                             SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _style(self, index: int, add: int = 0, remove: int = 0) -> None:
        hwnd = self.hwnd
        old = _user32.GetWindowLongPtrW(hwnd, index)
        _user32.SetWindowLongPtrW(hwnd, index, (old & ~remove) | add)
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
                             | SWP_NOACTIVATE | SWP_FRAMECHANGED)


class AppWindow(PixelWindow):
    """The main window: on the taskbar and in Alt+Tab, minimizable, movable."""

    def __init__(self, top: tk.Tk, zoom: int):
        super().__init__(top, zoom)
        self._fixed = False

    def make_app_window(self) -> None:
        """Once the window is mapped: give back its taskbar button. The
        taskbar only looks at a window's styles when it appears, so it is
        hidden and shown again."""
        if self._fixed:
            return
        self._fixed = True
        self._style(GWL_EXSTYLE, add=WS_EX_APPWINDOW, remove=WS_EX_TOOLWINDOW)
        self._style(GWL_STYLE, add=WS_MINIMIZEBOX)
        self.top.withdraw()
        self.top.after(10, self._reshow)

    def _reshow(self) -> None:
        self.top.deiconify()
        self.top.focus_force()

    def minimize(self) -> None:
        _user32.ShowWindow(self.hwnd, SW_MINIMIZE)

    @property
    def minimized(self) -> bool:
        return bool(_user32.IsIconic(self.hwnd))

    def keyboard_move(self) -> None:
        """The control menu's Move: the arrow keys move the window, Enter ends it."""
        _user32.PostMessageW(self.hwnd, WM_SYSCOMMAND, SC_MOVE, 0)


class PopupWindow(PixelWindow):
    """A menu: never activated, above everything, hidden by moving it away."""

    def __init__(self, master: tk.Misc, zoom: int):
        top = tk.Toplevel(master)
        super().__init__(top, zoom)
        top.attributes("-topmost", True)
        top.geometry(f"1x1+{OFF_SCREEN}+{OFF_SCREEN}")
        self.visible = False
        self._styled = False

    def prepare(self) -> None:
        """Once it exists (after update_idletasks): never let it be activated,
        and hide it until a menu opens."""
        if not self._styled:
            self._style(GWL_EXSTYLE, add=WS_EX_NOACTIVATE)
            self._styled = True
            _user32.ShowWindow(self.hwnd, SW_HIDE)

    def place(self, surface, x_root: int, y_root: int) -> None:
        if not self._styled:
            self.top.update_idletasks()
            self.prepare()
        self.show(surface)
        # Tk sizes the window; Windows moves and shows it. Inside the app, Tk's
        # first `wm geometry` move of this window was dropped (the size took,
        # the off-screen position stayed), so the move bypasses Tk.
        self.top.geometry(f"{surface.width * self.zoom}x{surface.height * self.zoom}")
        self.top.update_idletasks()
        _user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x_root, y_root, 0, 0,
                             SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self.visible = True

    def hide(self) -> None:
        if self.visible:
            _user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False
