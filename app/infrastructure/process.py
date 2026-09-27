from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import Any

WINDOWS_BELOW_NORMAL_PRIORITY = 0x00004000
UNIX_NICENESS = 5
HIDDEN_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(command: list[str], **options: Any) -> subprocess.CompletedProcess:
    flags = options.pop("creationflags", 0) | HIDDEN_WINDOW
    return subprocess.run(command, creationflags=flags, **options)


def start_hidden(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=HIDDEN_WINDOW,
    )


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
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
