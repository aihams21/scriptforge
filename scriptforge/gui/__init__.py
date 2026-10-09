"""Qt desktop front end for ScriptForge.

Runs on bare-metal Kali, Kali in a VM and Windows 11 from one code path: PySide6
ships the same binaries everywhere, so there is no GTK/MSVC split and no
platform-specific widget code.

The window never touches stdio for its own operation. Textual is still there for
terminals, but the desktop entry points here, where a missing TTY is not a
fatal condition.
"""

from .main_window import MainWindow, run

__all__ = ["MainWindow", "run"]