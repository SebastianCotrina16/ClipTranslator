from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from app.config.store import data_dir
from app.domain.corrections import Correction

log = logging.getLogger(__name__)


class CorrectionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "corrections.json"

    def load(self) -> list[Correction]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("Could not read the remembered corrections: %s", error)
            return []
        items = raw if isinstance(raw, list) else []
        return [
            Correction(item["wrong"], item["right"], item["language"])
            for item in items
            if isinstance(item, dict)
            and all(isinstance(item.get(key), str) for key in ("wrong", "right", "language"))
        ]

    def save(self, corrections: list[Correction]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(correction) for correction in corrections]
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def remember(self, correction: Correction) -> None:
        kept = [known for known in self.load() if not known.matches(correction)]
        self.save([*kept, correction])

    def forget(self, correction: Correction) -> None:
        self.save([known for known in self.load() if known != correction])
