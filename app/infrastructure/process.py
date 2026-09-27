from __future__ import annotations

import contextlib
import os
import sys

WINDOWS_BELOW_NORMAL_PRIORITY = 0x00004000
UNIX_NICENESS = 5


def lower_current_process_priority() -> None:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), WINDOWS_BELOW_NORMAL_PRIORITY)
        return
    with contextlib.suppress(OSError):
        os.nice(UNIX_NICENESS)


def use_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
