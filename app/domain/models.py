from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Flag(StrEnum):
    EMPTY = "empty"
    NO_SPEECH = "no_speech"
    LOW_CONFIDENCE = "low_confidence"
    REPETITIVE = "repetitive"
    KNOWN_PHRASE = "known_phrase"
    CORRECTED = "corrected"
    UNTRANSLATED = "untranslated"
    FAST_READING = "fast_reading"
    MODELS_DISAGREE = "models_disagree"
    SECOND_MODEL = "second_model"
    UNCLEAR = "unclear"


REVIEW_FLAGS = frozenset({Flag.MODELS_DISAGREE, Flag.SECOND_MODEL})


@dataclass
class Word:
    start: float
    end: float
    text: str
    probability: float = 1.0


@dataclass
class Reading:
    source: str
    text: str
    translation: str | None = None


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word]
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0
    flags: list[str] = field(default_factory=list)
    versions: list[Reading] = field(default_factory=list)


@dataclass
class Unit:
    id: int
    start: float
    end: float
    text: str
    words: list[Word]
    flags: list[str] = field(default_factory=list)
    translation: str | None = None
    asr_text: str | None = None
    versions: list[Reading] = field(default_factory=list)


@dataclass
class Cue:
    index: int
    start: float
    end: float
    original: str
    translation: str
    unit_id: int
    flags: list[str] = field(default_factory=list)
    versions: list[Reading] = field(default_factory=list)


@dataclass(frozen=True)
class LanguageGuess:
    language: str
    probability: float
    all_probabilities: list[tuple[str, float]]


@dataclass
class LanguageDetection:
    language: str
    probability: float
    windows: list[tuple[float, str, float]]
    top: list[tuple[str, float]]


def to_records(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]


def words_from_records(records: list[dict[str, Any]]) -> list[Word]:
    return [Word(**record) for record in records]


def readings_from_records(records: list[dict[str, Any]]) -> list[Reading]:
    return [Reading(**record) for record in records]


def segments_from_records(records: list[dict[str, Any]]) -> list[Segment]:
    return [
        Segment(
            **{
                **r,
                "words": words_from_records(r["words"]),
                "versions": readings_from_records(r.get("versions", [])),
            }
        )
        for r in records
    ]


def units_from_records(records: list[dict[str, Any]]) -> list[Unit]:
    return [
        Unit(
            **{
                **r,
                "words": words_from_records(r["words"]),
                "versions": readings_from_records(r.get("versions", [])),
            }
        )
        for r in records
    ]


def cues_from_records(records: list[dict[str, Any]]) -> list[Cue]:
    return [Cue(**{**r, "versions": readings_from_records(r.get("versions", []))}) for r in records]


def language_detection_from_record(record: dict[str, Any]) -> LanguageDetection:
    return LanguageDetection(
        language=record["language"],
        probability=record["probability"],
        windows=[tuple(window) for window in record["windows"]],
        top=[tuple(entry) for entry in record["top"]],
    )
