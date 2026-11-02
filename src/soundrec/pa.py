"""PortAudio through sounddevice, with every Windows host API switched on.

sounddevice picks its PortAudio DLL on first import, and only the ASIO build
lists ASIO drivers, so the switch has to be set before anything imports it:
import sounddevice from here, never directly.

PortAudio also sets up COM on the importing thread as a single-threaded
apartment, which ASIO drivers need. soundcard asks for a multithreaded one when
it is imported, and quietly accepts whatever is already there, so importing
this module first keeps the thread single-threaded.
"""

import os

os.environ.setdefault("SD_ENABLE_ASIO", "1")

import sounddevice as sd  # noqa: E402


def rescan() -> None:
    """Have PortAudio list the devices again; it only looks when initialised.

    Terminating PortAudio closes every stream, so none may be open.
    """
    sd._terminate()
    sd._initialize()
