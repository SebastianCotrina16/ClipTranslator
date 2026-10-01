from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from app.application.updates import Installer

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
CHUNK_BYTES = 1024 * 1024
UNINSTALLER = "unins000.exe"
SILENT_INSTALL = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RESTARTAPP=1"]
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class UpdateError(RuntimeError):
    pass


def install_folder() -> Path:
    return Path(sys.prefix).parent


def can_update_itself() -> bool:
    return sys.platform == "win32" and (install_folder() / UNINSTALLER).is_file()


def update_folder() -> Path:
    return Path(tempfile.gettempdir()) / "ClipTranslator-update"


def download_installer(
    installer: Installer,
    folder: Path | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    folder = folder or update_folder()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / f"{installer.name}.part"
    digest = hashlib.sha256()
    received = 0
    try:
        with (
            httpx.stream(
                "GET", installer.url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True
            ) as response,
            partial.open("wb") as file,
        ):
            response.raise_for_status()
            for chunk in response.iter_bytes(CHUNK_BYTES):
                received += len(chunk)
                if received > installer.size:
                    raise UpdateError("The update is larger than expected.")
                digest.update(chunk)
                file.write(chunk)
                if progress:
                    progress(received / installer.size)
    except httpx.HTTPError as error:
        raise UpdateError(f"The update could not be downloaded: {error}") from error
    if received != installer.size or digest.hexdigest() != installer.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("The downloaded update is damaged. Try again later.")
    return partial.replace(folder / installer.name)


def launch_installer(installer: Path) -> None:
    command = [str(installer), *SILENT_INSTALL]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
    except OSError:
        log.info("Starting the installer outside the launcher's job is not allowed; retrying.")
        subprocess.Popen(command, creationflags=flags, close_fds=True)
