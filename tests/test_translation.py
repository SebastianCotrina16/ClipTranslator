from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.application.ports import LanguageModelError
from app.application.translation import (
    MAX_SEGMENT_CHARS,
    Request,
    Task,
    TranslationService,
    build_user_message,
    validate_response,
)
from app.domain.models import Unit

SPANISH_TO_ENGLISH = Request(Task.TRANSLATE, "es", "en")


def units(count: int) -> list[Unit]:
    return [Unit(id=i, start=i, end=i + 0.5, text=f"line {i}", words=[]) for i in range(count)]


def requested_ids(message: str) -> list[int]:
    payload = message.split("Segments to translate:\n", 1)[1].split("\n\n", 1)[0]
    return [item["id"] for item in json.loads(payload)["segments"]]


class ScriptedModel:
    description = "scripted"

    def __init__(self, behaviours: list[str]) -> None:
        self.behaviours = behaviours
        self.requests: list[list[int]] = []

    def prepare(self, progress: Callable[[float, str], None] | None = None) -> list[str]:
        return []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        ids = requested_ids(user)
        self.requests.append(ids)
        behaviour = self.behaviours.pop(0) if self.behaviours else "ok"
        if behaviour == "error":
            raise LanguageModelError("caído")
        if behaviour == "garbage":
            return {"nope": True}
        if behaviour == "drop_last":
            ids = ids[:-1]
        if behaviour == "extra":
            ids = [*ids, 999]
        return {"translations": [{"id": i, "text": f"línea {i}"} for i in ids]}

    def unload(self) -> None:
        return None


def test_validate_accepts_matching_ids() -> None:
    result = validate_response(
        [0, 1], {"translations": [{"id": 0, "text": "a"}, {"id": 1, "text": "b"}]}
    )
    assert (result.texts, result.missing, result.unexpected) == ({0: "a", 1: "b"}, [], [])


def test_validate_reports_missing_unexpected_and_empty() -> None:
    result = validate_response(
        [0, 1, 2],
        {
            "translations": [
                {"id": "0", "text": "a"},
                {"id": 1, "text": "  "},
                {"id": 7, "text": "x"},
            ]
        },
    )
    assert result.texts == {0: "a"}
    assert result.missing == [1, 2]
    assert result.unexpected == [7]


def test_validate_rejects_wrong_shapes() -> None:
    assert validate_response([0], {"foo": 1}).missing == [0]
    assert validate_response([0], ["x"]).missing == [0]


def test_validate_strips_control_characters_and_limits_length() -> None:
    result = validate_response(
        [0, 1],
        {"translations": [{"id": 0, "text": "ho\x00la\x1b"}, {"id": 1, "text": "x" * 5000}]},
    )
    assert result.texts[0] == "hola"
    assert len(result.texts[1]) == MAX_SEGMENT_CHARS


def test_whole_transcript_in_one_request() -> None:
    model = ScriptedModel(["ok"])
    result, report = TranslationService(model).run(units(5), SPANISH_TO_ENGLISH, "sys")
    assert result == {i: f"línea {i}" for i in range(5)}
    assert report.requests == 1
    assert report.untranslated == []


def test_retry_only_sends_missing_ids() -> None:
    model = ScriptedModel(["drop_last", "ok"])
    result, report = TranslationService(model).run(units(4), SPANISH_TO_ENGLISH, "sys")
    assert len(result) == 4
    assert model.requests == [[0, 1, 2, 3], [3]]
    assert report.full_attempts == 2


def test_falls_back_to_small_batches() -> None:
    model = ScriptedModel(["garbage", "garbage", "garbage", "ok", "ok"])
    result, report = TranslationService(model, batch_size=8).run(
        units(10), SPANISH_TO_ENGLISH, "sys"
    )
    assert len(result) == 10
    assert report.full_attempts == 3
    assert model.requests[3] == list(range(8))
    assert model.requests[4] == [8, 9]


def test_unexpected_ids_are_ignored() -> None:
    result, _ = TranslationService(ScriptedModel(["extra"])).run(units(2), SPANISH_TO_ENGLISH, "s")
    assert set(result) == {0, 1}


def test_model_errors_are_reported_not_raised() -> None:
    result, report = TranslationService(ScriptedModel(["error"] * 20)).run(
        units(3), SPANISH_TO_ENGLISH, "sys"
    )
    assert result == {}
    assert report.untranslated == [0, 1, 2]
    assert report.errors


def test_merged_task_collects_corrections() -> None:
    class MergedModel(ScriptedModel):
        def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            assert "source" in json.dumps(schema)
            return {
                "translations": [
                    {
                        "id": 0,
                        "source": "¿cómo dibujan tan bien?",
                        "text": "how do you draw so well?",
                    },
                    {"id": 1, "source": "hola", "text": "hi"},
                ]
            }

    request = Request(Task.REVIEW_AND_TRANSLATE, "es", "en")
    result, report = TranslationService(MergedModel([])).run(units(2), request, "sys")
    assert result == {0: "how do you draw so well?", 1: "hi"}
    assert report.corrections == {0: "¿cómo dibujan tan bien?", 1: "hola"}


def test_translation_message_names_languages_and_context() -> None:
    message = build_user_message(
        [{"id": 3, "text": "oi"}],
        Request(Task.TRANSLATE, "pt", "en", "an astronaut cat"),
        [{"id": 2, "text": "before"}],
    )
    assert message.startswith("Translate from Portuguese into English.")
    assert "an astronaut cat" in message
    assert "do NOT translate" in message
    assert message.rstrip().endswith("3.")


def test_review_message_keeps_source_language() -> None:
    message = build_user_message([{"id": 0, "text": "x"}], Request(Task.REVIEW, "es", "es"))
    assert message.startswith("Proofread this automatic Latin American Spanish transcript.")
    assert "Segments to proofread:" in message


def test_merged_message_asks_for_corrected_source() -> None:
    message = build_user_message(
        [{"id": 0, "text": "x"}], Request(Task.REVIEW_AND_TRANSLATE, "es", "en")
    )
    assert message.startswith("First proofread this automatic Latin American Spanish transcript")
    assert '"source"' in message
