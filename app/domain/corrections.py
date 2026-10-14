from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.domain.models import Cue

MAX_WRONG_WORDS = 4
MAX_RIGHT_WORDS = 6
MIN_SINGLE_WORD_LETTERS = 4
EDGE_PUNCTUATION = "\"'«»“”‘’¿¡.,!?;:…()[]-–—"


@dataclass(frozen=True)
class Correction:
    wrong: str
    right: str
    language: str

    def matches(self, other: Correction) -> bool:
        return self.language == other.language and self.wrong.lower() == other.wrong.lower()


def _words(text: str) -> list[str]:
    return [word.strip(EDGE_PUNCTUATION) for word in text.split()]


def _phrase(words: list[str]) -> str:
    return " ".join(word for word in words if word)


def learn(before: str, after: str, language: str) -> Correction | None:
    old, new = _words(before), _words(after)
    matcher = SequenceMatcher(None, [w.lower() for w in old], [w.lower() for w in new])
    changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if len(changes) != 1 or changes[0][0] != "replace":
        return None
    _, old_start, old_end, new_start, new_end = changes[0]
    wrong, right = _phrase(old[old_start:old_end]), _phrase(new[new_start:new_end])
    wrong_words, right_words = wrong.split(), right.split()
    if not wrong_words or not right_words or wrong.lower() == right.lower():
        return None
    if len(wrong_words) > MAX_WRONG_WORDS or len(right_words) > MAX_RIGHT_WORDS:
        return None
    if len(wrong_words) == 1 and sum(char.isalpha() for char in wrong) < MIN_SINGLE_WORD_LETTERS:
        return None
    if len(wrong_words) >= len(old) > 1:
        return None
    return Correction(wrong, right, language)


def _pattern(wrong: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(word) for word in wrong.split())
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def _matching_case(found: str, right: str) -> str:
    if found[:1].isupper() and right[:1].islower():
        return right[:1].upper() + right[1:]
    return right


def apply_to_text(text: str, corrections: list[Correction]) -> str:
    for correction in corrections:
        text = _pattern(correction.wrong).sub(
            lambda match, right=correction.right: _matching_case(match.group(0), right), text
        )
    return text


def for_language(corrections: list[Correction], language: str) -> list[Correction]:
    return [correction for correction in corrections if correction.language == language]


def apply_to_cues(cues: list[Cue], corrections: list[Correction], source: str, target: str) -> int:
    original, translated = for_language(corrections, source), for_language(corrections, target)
    changed = 0
    for cue in cues:
        fixed_original = apply_to_text(cue.original, original) if original else cue.original
        fixed_translation = (
            apply_to_text(cue.translation, translated) if translated else cue.translation
        )
        if (fixed_original, fixed_translation) != (cue.original, cue.translation):
            cue.original, cue.translation = fixed_original, fixed_translation
            changed += 1
    return changed
