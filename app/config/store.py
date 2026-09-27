from __future__ import annotations

import logging
import sys
import tomllib
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import tomli_w
from platformdirs import user_config_dir, user_data_dir

from app.config.settings import SECTION_NAMES, Settings
from app.domain.languages import InvalidLanguageCodeError, parse_language_code

APP_NAME = "ClipTranslator"

log = logging.getLogger(__name__)


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False, roaming=True)) / "config.toml"


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def models_dir() -> Path:
    return data_dir() / "models"


def whisper_models_dir() -> Path:
    return models_dir() / "whisper"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load(self) -> Settings:
        settings = Settings()
        if not self.path.exists():
            return settings
        try:
            raw = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            log.warning("Unreadable settings (%s); using defaults.", error)
            return settings
        for name in SECTION_NAMES:
            if isinstance(raw.get(name), dict):
                _merge_typed(getattr(settings, name), raw[name], name)
        if isinstance(raw.get("work_dir"), str):
            settings.work_dir = raw["work_dir"]
        _validate_language(settings)
        return settings

    def save(self, settings: Settings) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(tomli_w.dumps(asdict(settings)), encoding="utf-8")
        _restrict_to_owner(self.path)
        return self.path


def _merge_typed(section: Any, raw: dict[str, Any], section_name: str) -> None:
    defaults = {f.name: getattr(section, f.name) for f in fields(section)}
    for key, value in raw.items():
        if key not in defaults:
            continue
        expected = type(defaults[key])
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            log.warning("Ignoring %s.%s: expected %s.", section_name, key, expected.__name__)
            continue
        setattr(section, key, value)


def _validate_language(settings: Settings) -> None:
    try:
        settings.translation.target_language = parse_language_code(
            settings.translation.target_language
        )
    except InvalidLanguageCodeError as error:
        log.warning("%s Using Spanish.", error)
        settings.translation.target_language = "es"


def _restrict_to_owner(path: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        path.chmod(0o600)
    except OSError:
        log.warning("Could not restrict the permissions of %s.", path)
