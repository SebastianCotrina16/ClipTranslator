from __future__ import annotations

from pathlib import Path

import pytest

from app.application.stage_cache import StageCache
from app.config.prompts import SPANISH_TRANSLATION_PROMPT
from app.config.settings import PerformanceSettings, Settings, TranslationSettings, redacted
from app.config.store import SettingsStore
from app.domain.languages import InvalidLanguageCodeError, parse_language_code


def test_cache_reuses_and_invalidates(tmp_path: Path) -> None:
    cache = StageCache(tmp_path)
    calls: list[int] = []

    def compute() -> list[int]:
        calls.append(1)
        return [1, 2]

    first = cache.get_or_compute("stage", {"a": 1}, compute)
    assert (first.data, first.from_cache) == ([1, 2], False)
    second = cache.get_or_compute("stage", {"a": 1}, compute)
    assert second.from_cache and second.key == first.key
    assert not cache.get_or_compute("stage", {"a": 2}, compute).from_cache
    assert not cache.get_or_compute("stage", {"a": 2}, compute, upstream="other").from_cache
    assert not cache.get_or_compute("stage", {"a": 2}, compute, "other", force=True).from_cache
    assert len(calls) == 4


def test_cache_ignores_corrupted_file(tmp_path: Path) -> None:
    cache = StageCache(tmp_path)
    cache.path("stage").write_text("{not json", encoding="utf-8")
    assert not cache.get_or_compute("stage", {}, lambda: 1).from_cache


def test_prompt_follows_target_language() -> None:
    assert TranslationSettings(target_language="es").effective_system_prompt() == (
        SPANISH_TRANSLATION_PROMPT
    )
    english = TranslationSettings(target_language="en").effective_system_prompt()
    assert "natural, casual English" in english
    assert TranslationSettings(system_prompt="mine").effective_system_prompt() == "mine"


def test_low_impact_uses_half_the_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 32)
    assert PerformanceSettings().threads() == 16
    assert PerformanceSettings(low_impact=False).threads() == 32
    assert PerformanceSettings(low_impact=False).thread_limit() == 0
    assert PerformanceSettings(cpu_threads=6).threads() == 6
    monkeypatch.setattr("os.cpu_count", lambda: 2)
    assert PerformanceSettings().threads() == 2


def test_api_keys_come_from_environment_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert TranslationSettings(anthropic_api_key="from-file").anthropic_key() == "from-env"


def test_api_keys_are_hidden_from_repr_and_logs() -> None:
    settings = Settings()
    settings.translation.anthropic_api_key = "secret-value"
    assert "secret-value" not in repr(settings)
    assert "secret-value" not in str(redacted(settings))


def test_store_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.toml")
    settings = Settings()
    settings.translation.target_language = "en"
    settings.performance.cpu_threads = 4
    store.save(settings)
    loaded = store.load()
    assert loaded.translation.target_language == "en"
    assert loaded.performance.cpu_threads == 4


def test_store_ignores_values_of_the_wrong_type(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[subtitles]\nmax_cps = "fast"\nmax_line_chars = 40\ngap = 1\n'
        '[performance]\nlow_impact = "yes"\n',
        encoding="utf-8",
    )
    loaded = SettingsStore(path).load()
    assert loaded.subtitles.max_cps == 20.0
    assert loaded.subtitles.max_line_chars == 40
    assert loaded.subtitles.gap == 1.0
    assert loaded.performance.low_impact is True


def test_store_rejects_unsafe_target_language(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[translation]\ntarget_language = "../../evil"\n', encoding="utf-8")
    assert SettingsStore(path).load().translation.target_language == "es"


def test_store_survives_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("not = [valid", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def test_language_codes_are_validated() -> None:
    assert parse_language_code(" EN ") == "en"
    assert parse_language_code("haw") == "haw"
    for bad in ("", "english", "e1", "../x", "es-ES"):
        with pytest.raises(InvalidLanguageCodeError):
            parse_language_code(bad)
