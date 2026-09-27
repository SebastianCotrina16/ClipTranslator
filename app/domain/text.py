from __future__ import annotations

import re
import unicodedata

from app.domain.models import Word

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CLAUSE_END = (",", ";", ":", "，", "、", "；", "：")
_CLOSING_MARKS = "\"'”»)]"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def ends_with(text: str, marks: tuple[str, ...]) -> bool:
    return text.rstrip().rstrip(_CLOSING_MARKS).endswith(marks)


def ends_sentence(text: str) -> bool:
    return ends_with(text, SENTENCE_END)


def ends_clause(text: str) -> bool:
    return ends_with(text, CLAUSE_END)


def join_words(words: list[Word]) -> str:
    return "".join(word.text for word in words).strip()


def collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def strip_control_characters(text: str) -> str:
    return _CONTROL_CHARACTERS.sub("", text)


def normalize_for_comparison(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    without_punctuation = re.sub(r"[^\w\s]", "", without_accents)
    return collapse_spaces(without_punctuation)
