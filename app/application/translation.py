from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.application.ports import FractionCallback, LanguageModel, LanguageModelError
from app.domain.languages import english_name
from app.domain.models import Unit
from app.domain.text import strip_control_characters

log = logging.getLogger(__name__)

MAX_SEGMENT_CHARS = 2000


class Task(StrEnum):
    TRANSLATE = "translate"
    REVIEW = "review"
    REVIEW_AND_TRANSLATE = "review_translate"


def _response_schema(with_source: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {"id": {"type": "integer"}}
    if with_source:
        properties["source"] = {"type": "string"}
    properties["text"] = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["translations"],
        "additionalProperties": False,
    }


RESPONSE_SCHEMAS = {
    Task.TRANSLATE: _response_schema(with_source=False),
    Task.REVIEW: _response_schema(with_source=False),
    Task.REVIEW_AND_TRANSLATE: _response_schema(with_source=True),
}


@dataclass(frozen=True)
class Request:
    task: Task
    source_language: str
    target_language: str
    clip_context: str = ""
    names: tuple[str, ...] = ()


@dataclass
class TranslationReport:
    requests: int = 0
    full_attempts: int = 0
    batch_requests: int = 0
    untranslated: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    corrections: dict[int, str] = field(default_factory=dict)


@dataclass
class ValidatedResponse:
    texts: dict[int, str]
    missing: list[int]
    unexpected: list[Any]
    sources: dict[int, str] = field(default_factory=dict)


def build_user_message(
    items: list[dict[str, Any]],
    request: Request,
    surrounding: list[dict[str, Any]] | None = None,
) -> str:
    source = english_name(request.source_language)
    target = english_name(request.target_language)
    answer = '{"translations": [{"id": ..., "text": ...}]}'
    if request.task is Task.REVIEW:
        target = source
        parts = [
            f"Proofread this automatic {source} transcript. Keep it in {source}: do NOT "
            "translate it."
        ]
        header = "Segments to proofread:\n"
    elif request.task is Task.REVIEW_AND_TRANSLATE:
        parts = [
            f"First proofread this automatic {source} transcript, then translate the "
            f"corrected text from {source} into {target}."
        ]
        header = "Segments to translate:\n"
        answer = (
            '{"translations": [{"id": ..., "source": <corrected ' + source + " segment, "
            'identical if it had no error>, "text": <translation>}]}'
        )
    else:
        parts = [f"Translate from {source} into {target}."]
        header = "Segments to translate:\n"
    if request.names:
        parts.append(
            "Names that appear in this clip. Write them exactly like this and never "
            f"translate them: {', '.join(request.names)}."
        )
    if request.clip_context.strip():
        parts.append(f"Clip context (what is on screen): {request.clip_context.strip()}")
    if surrounding:
        parts.append(
            "Conversation context (do NOT translate it, only use it to understand):\n"
            + json.dumps(surrounding, ensure_ascii=False)
        )
    parts.append(header + json.dumps({"segments": items}, ensure_ascii=False))
    ids = ", ".join(str(item["id"]) for item in items)
    parts.append(
        f"Answer with {answer} in {target}, with exactly these ids, one per segment, in the "
        f"same order: {ids}."
    )
    return "\n\n".join(parts)


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = strip_control_characters(value).strip()
    return cleaned[:MAX_SEGMENT_CHARS] if cleaned else None


def validate_response(expected_ids: list[int], response: Any) -> ValidatedResponse:
    entries = response.get("translations") if isinstance(response, dict) else None
    if not isinstance(entries, list):
        return ValidatedResponse({}, list(expected_ids), [])
    expected = set(expected_ids)
    texts: dict[int, str] = {}
    sources: dict[int, str] = {}
    unexpected: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            unexpected.append(raw_id)
            continue
        if item_id not in expected:
            unexpected.append(item_id)
            continue
        text = _clean(entry.get("text"))
        if text and item_id not in texts:
            texts[item_id] = text
            source = _clean(entry.get("source"))
            if source:
                sources[item_id] = source
    missing = [item_id for item_id in expected_ids if item_id not in texts]
    return ValidatedResponse(texts, missing, unexpected, sources)


class TranslationService:
    def __init__(
        self,
        model: LanguageModel,
        retries: int = 2,
        batch_size: int = 8,
        neighbours: int = 4,
    ) -> None:
        self._model = model
        self._retries = retries
        self._batch_size = batch_size
        self._neighbours = neighbours

    def run(
        self,
        units: list[Unit],
        request: Request,
        system_prompt: str,
        progress: FractionCallback | None = None,
    ) -> tuple[dict[int, str], TranslationReport]:
        report = TranslationReport()
        items = [{"id": unit.id, "text": unit.text} for unit in units]
        result: dict[int, str] = {}
        self._whole_transcript_passes(items, request, system_prompt, result, report, progress)
        self._missing_in_batches(units, request, system_prompt, result, report, progress)
        report.untranslated = [item["id"] for item in items if item["id"] not in result]
        return result, report

    def _whole_transcript_passes(
        self,
        items: list[dict[str, Any]],
        request: Request,
        system_prompt: str,
        result: dict[int, str],
        report: TranslationReport,
        progress: FractionCallback | None,
    ) -> None:
        for _ in range(1 + self._retries):
            pending = [item for item in items if item["id"] not in result]
            if not pending:
                return
            report.full_attempts += 1
            done = [
                {"id": item["id"], "text": item["text"], "translation": result[item["id"]]}
                for item in items
                if item["id"] in result
            ]
            result.update(self._ask(pending, request, system_prompt, done or None, report))
            _notify(progress, len(result), len(items))

    def _missing_in_batches(
        self,
        units: list[Unit],
        request: Request,
        system_prompt: str,
        result: dict[int, str],
        report: TranslationReport,
        progress: FractionCallback | None,
    ) -> None:
        order = [unit.id for unit in units]
        text_by_id = {unit.id: unit.text for unit in units}
        missing = [unit_id for unit_id in order if unit_id not in result]
        for start in range(0, len(missing), self._batch_size):
            batch_ids = missing[start : start + self._batch_size]
            positions = [order.index(unit_id) for unit_id in batch_ids]
            low = max(min(positions) - self._neighbours, 0)
            high = min(max(positions) + self._neighbours + 1, len(order))
            surrounding = [
                {"id": uid, "text": text_by_id[uid], "translation": result.get(uid, "")}
                for uid in order[low:high]
                if uid not in batch_ids
            ]
            batch = [{"id": uid, "text": text_by_id[uid]} for uid in batch_ids]
            for _ in range(2):
                report.batch_requests += 1
                result.update(self._ask(batch, request, system_prompt, surrounding, report))
                batch = [item for item in batch if item["id"] not in result]
                if not batch:
                    break
            _notify(progress, len(result), len(order))

    def translate_one(
        self,
        item: dict[str, Any],
        request: Request,
        system_prompt: str,
        surrounding: list[dict[str, Any]],
    ) -> str | None:
        report = TranslationReport()
        for _ in range(1 + self._retries):
            result = self._ask([item], request, system_prompt, surrounding, report)
            if item["id"] in result:
                return result[item["id"]]
        return None

    def _ask(
        self,
        items: list[dict[str, Any]],
        request: Request,
        system_prompt: str,
        surrounding: list[dict[str, Any]] | None,
        report: TranslationReport,
    ) -> dict[int, str]:
        report.requests += 1
        message = build_user_message(items, request, surrounding)
        try:
            response = self._model.complete(system_prompt, message, RESPONSE_SCHEMAS[request.task])
        except LanguageModelError as error:
            report.errors.append(str(error))
            log.warning("Model request failed: %s", error)
            return {}
        validated = validate_response([item["id"] for item in items], response)
        if validated.missing or validated.unexpected:
            log.info(
                "Incomplete response: %d ids missing, %d unexpected",
                len(validated.missing),
                len(validated.unexpected),
            )
        if request.task is Task.REVIEW_AND_TRANSLATE:
            report.corrections.update(validated.sources)
        return validated.texts


def _notify(progress: Callable[[float], None] | None, done: int, total: int) -> None:
    if progress:
        progress(done / max(total, 1))


VERSION_NEIGHBOURS = 3


def translate_versions(
    service: TranslationService,
    units: list[Unit],
    translations: dict[int, str],
    request: Request,
    system_prompt: str,
) -> dict[int, list[str | None]]:
    result: dict[int, list[str | None]] = {}
    for position, unit in enumerate(units):
        if len(unit.versions) < 2:
            continue
        nearby = units[max(position - VERSION_NEIGHBOURS, 0) : position + VERSION_NEIGHBOURS + 1]
        surrounding = [
            {"id": other.id, "text": other.text, "translation": translations[other.id]}
            for other in nearby
            if other is not unit and other.id in translations
        ]
        result[unit.id] = [None] + [
            service.translate_one(
                {"id": unit.id, "text": version.text}, request, system_prompt, surrounding
            )
            for version in unit.versions[1:]
        ]
    return result


def fill_versions(unit: Unit, translations: list[str | None]) -> None:
    for position, version in enumerate(unit.versions):
        if position == 0:
            version.text, version.translation = unit.text, unit.translation
        elif position < len(translations):
            version.translation = translations[position]
