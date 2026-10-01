from __future__ import annotations

import logging
import re
from importlib import metadata
from typing import Any

import httpx

from app.application.updates import Installer, Release

log = logging.getLogger(__name__)

REPOSITORY = "SebastianCotrina16/ClipTranslator"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/"
DOWNLOADS = f"{RELEASES_PAGE}download/"
INSTALLER_NAME = re.compile(r"^ClipTranslator-Setup-\d+\.\d+\.\d+\.exe$")
SHA256_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
MAX_INSTALLER_BYTES = 500 * 1024 * 1024
REQUEST_TIMEOUT = 5.0
MAX_NOTES_CHARS = 600


def installed_version() -> str:
    try:
        return metadata.version("cliptranslator")
    except metadata.PackageNotFoundError:
        return "0.0.0"


class GitHubReleases:
    def latest(self) -> Release | None:
        try:
            response = httpx.get(
                LATEST_RELEASE_API,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/vnd.github+json"},
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            log.info("Could not check for updates: %s", error)
            return None
        tag = data.get("tag_name")
        url = data.get("html_url")
        if not isinstance(tag, str) or not isinstance(url, str):
            return None
        if not url.startswith(RELEASES_PAGE):
            log.warning("Ignoring an update link outside the project: %s", url)
            return None
        notes = data.get("body") if isinstance(data.get("body"), str) else ""
        return Release(
            version=tag,
            url=url,
            notes=notes[:MAX_NOTES_CHARS],
            installer=installer_from(data.get("assets")),
        )


def installer_from(assets: Any) -> Installer | None:
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        size, digest = asset.get("size"), asset.get("digest")
        if not isinstance(name, str) or not INSTALLER_NAME.match(name):
            continue
        valid = (
            isinstance(url, str)
            and url.startswith(DOWNLOADS)
            and isinstance(size, int)
            and 0 < size <= MAX_INSTALLER_BYTES
            and isinstance(digest, str)
            and SHA256_DIGEST.match(digest)
        )
        if not valid:
            log.warning("Ignoring an installer without a trusted link or checksum: %s", name)
            return None
        return Installer(name=name, url=url, size=size, sha256=digest.removeprefix("sha256:"))
    return None
