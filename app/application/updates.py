from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Installer:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    notes: str = ""
    installer: Installer | None = None


class ReleaseSource(Protocol):
    def latest(self) -> Release | None: ...


def version_key(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.match(version.strip())
    if not match:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def newer_release(current: str, source: ReleaseSource) -> Release | None:
    current_key = version_key(current)
    if current_key is None:
        return None
    release = source.latest()
    if release is None:
        return None
    latest_key = version_key(release.version)
    if latest_key is None or latest_key <= current_key:
        return None
    return release
