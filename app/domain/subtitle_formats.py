from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import Cue
from app.domain.subtitles import CueRules, format_for_screen
from app.domain.text import collapse_spaces


class Track(StrEnum):
    TRANSLATION = "translation"
    ORIGINAL = "original"
    BILINGUAL = "bilingual"


@dataclass(frozen=True)
class OutputVocabulary:
    bilingual: str
    transcript: str
    untranslated: str
    review: str


_VOCABULARY = {
    "es": OutputVocabulary("bilingue", "transcripcion", "(sin traducción)", "revisar"),
    "en": OutputVocabulary("bilingual", "transcript", "(not translated)", "check"),
}


def vocabulary_for(target_language: str) -> OutputVocabulary:
    return _VOCABULARY.get(target_language, _VOCABULARY["en"])


def timestamp(seconds: float, separator: str = ",") -> str:
    millis = max(round(seconds * 1000), 0)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def clock(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def cue_text(cue: Cue, track: Track, rules: CueRules) -> str:
    if track is Track.TRANSLATION:
        return format_for_screen(cue.translation, rules)
    if track is Track.ORIGINAL:
        return format_for_screen(cue.original, rules)
    parts = (format_for_screen(cue.original, rules), format_for_screen(cue.translation, rules))
    return "\n".join(part for part in parts if part)


def _visible(cues: list[Cue], track: Track, rules: CueRules) -> list[tuple[Cue, str]]:
    entries = [(cue, cue_text(cue, track, rules)) for cue in cues]
    return [(cue, text) for cue, text in entries if text.strip()]


def to_srt(cues: list[Cue], track: Track = Track.TRANSLATION, rules: CueRules | None = None) -> str:
    rules = rules or CueRules()
    blocks = [
        f"{number}\n{timestamp(cue.start)} --> {timestamp(cue.end)}\n{text}\n"
        for number, (cue, text) in enumerate(_visible(cues, track, rules), start=1)
    ]
    return "\n".join(blocks)


def to_vtt(cues: list[Cue], track: Track = Track.TRANSLATION, rules: CueRules | None = None) -> str:
    rules = rules or CueRules()
    blocks = ["WEBVTT\n"]
    for cue, text in _visible(cues, track, rules):
        blocks.append(f"{timestamp(cue.start, '.')} --> {timestamp(cue.end, '.')}\n{text}\n")
    return "\n".join(blocks)


def to_transcript(cues: list[Cue], source_language: str, target_language: str = "es") -> str:
    vocabulary = vocabulary_for(target_language)
    blocks = []
    for group in _group_by_unit(cues):
        original = " ".join(collapse_spaces(cue.original) for cue in group)
        translation = " ".join(collapse_spaces(cue.translation) for cue in group).strip()
        lines = [f"[{clock(group[0].start)} - {clock(group[-1].end)}]"]
        if source_language == target_language:
            lines.append(f"  {original}")
        else:
            lines.append(f"  {source_language.upper()}: {original}")
            lines.append(f"  {target_language.upper()}: {translation or vocabulary.untranslated}")
        flags = sorted({flag for cue in group for flag in cue.flags})
        if flags:
            lines.append(f"  ⚠ {vocabulary.review}: {', '.join(flags)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _group_by_unit(cues: list[Cue]) -> list[list[Cue]]:
    groups: list[list[Cue]] = []
    for cue in cues:
        if groups and groups[-1][-1].unit_id == cue.unit_id:
            groups[-1].append(cue)
        else:
            groups.append([cue])
    return groups
