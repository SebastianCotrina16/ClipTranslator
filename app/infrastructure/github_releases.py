from __future__ import annotations

import logging
from importlib import metadata

import httpx

from app.application.updates import Release

log = logging.getLogger(__name__)

REPOSITORY = "SebastianCotrina16/ClipTranslator"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/"
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
        return Release(version=tag, url=url, notes=notes[:MAX_NOTES_CHARS])
