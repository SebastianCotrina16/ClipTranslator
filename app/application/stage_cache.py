from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def cache_key(params: dict[str, Any], upstream: str = "") -> str:
    payload = json.dumps({"params": params, "upstream": upstream}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CachedResult:
    data: Any
    key: str
    from_cache: bool


class StageCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def path(self, stage: str) -> Path:
        return self.directory / f"{stage}.json"

    def invalidate(self, stage: str) -> None:
        self.path(stage).unlink(missing_ok=True)

    def get_or_compute(
        self,
        stage: str,
        params: dict[str, Any],
        compute: Callable[[], Any],
        upstream: str = "",
        force: bool = False,
    ) -> CachedResult:
        key = cache_key(params, upstream)
        if not force:
            stored = self._read(stage, key)
            if stored is not None:
                return CachedResult(stored, key, True)
        data = compute()
        self._write(stage, key, data)
        return CachedResult(data, key, False)

    def _read(self, stage: str, key: str) -> Any | None:
        path = self.path(stage)
        if not path.exists():
            return None
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(stored, dict) or stored.get("key") != key:
            return None
        return stored.get("data")

    def _write(self, stage: str, key: str, data: Any) -> None:
        temporary = self.path(stage).with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"key": key, "data": data}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        temporary.replace(self.path(stage))
