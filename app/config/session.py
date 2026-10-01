from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config.store import data_dir

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedClip:
    path: str
    status: str


@dataclass(frozen=True)
class Session:
    clips: list[SavedClip] = field(default_factory=list)
    current: str = ""
    source_language: str = ""
    context: str = ""


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "session.json"

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(session), ensure_ascii=False), encoding="utf-8")

    def take(self) -> Session | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("Could not read the saved session: %s", error)
            raw = None
        self.path.unlink(missing_ok=True)
        return _session_from(raw) if isinstance(raw, dict) else None


def _session_from(raw: dict) -> Session:
    items = raw.get("clips")
    clips = [
        SavedClip(item["path"], item["status"])
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("status"), str)
    ]
    return Session(
        clips=clips,
        current=_text(raw.get("current")),
        source_language=_text(raw.get("source_language")),
        context=_text(raw.get("context")),
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
