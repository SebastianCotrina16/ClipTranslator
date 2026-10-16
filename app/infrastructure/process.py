from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import Any

WINDOWS_BELOW_NORMAL_PRIORITY = 0x00004000
WINDOWS_NORMAL_PRIORITY = 0x00000020
WINDOWS_DETACHED = 0x00000008 | 0x00000200
WINDOWS_BREAKAWAY_FROM_JOB = 0x01000000
UNIX_NICENESS = 5
HIDDEN_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(command: list[str], **options: Any) -> subprocess.CompletedProcess:
    flags = options.pop("creationflags", 0) | HIDDEN_WINDOW
    return subprocess.run(command, creationflags=flags, **options)


def start_in_background(command: list[str]) -> subprocess.Popen:
    streams: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform != "win32":
        return subprocess.Popen(command, start_new_session=True, **streams)
    flags = WINDOWS_DETACHED | WINDOWS_NORMAL_PRIORITY
    try:
        return subprocess.Popen(
            command, creationflags=flags | WINDOWS_BREAKAWAY_FROM_JOB, **streams
        )
    except OSError:
        return subprocess.Popen(command, creationflags=flags, **streams)


def stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            run_hidden(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=15,
            )
        return
    with contextlib.suppress(OSError):
        process.terminate()


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
