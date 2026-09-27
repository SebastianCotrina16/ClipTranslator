from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import Cue, cues_from_records, to_records

EDITS_FILE = "edits.json"


class EditStore:
    def __init__(self, directory: Path) -> None:
        self.path = directory / EDITS_FILE

    def save(self, cues_key: str, cues: list[Cue]) -> None:
        payload = {"cues_key": cues_key, "cues": to_records(cues)}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def load(self, cues_key: str) -> list[Cue] | None:
        if not self.path.exists():
            return None
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(stored, dict) or stored.get("cues_key") != cues_key:
                return None
            return cues_from_records(stored["cues"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)
