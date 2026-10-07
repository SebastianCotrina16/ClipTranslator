from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.domain.models import Unit

ALWAYS_SPELLED = ("Gevo",)
MIN_FUZZY_LENGTH = 4
WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")
POSSESSIVE = re.compile(r"['’]s$", re.IGNORECASE)
SOUND_ALIKES = (
    (re.compile(r"gu(?=[eiy])"), "g"),
    (re.compile(r"gh"), "g"),
    (re.compile(r"dj"), "j"),
    (re.compile(r"j"), "g"),
    (re.compile(r"w"), "v"),
    (re.compile(r"ph"), "f"),
    (re.compile(r"(eaux|eau|aux|au|ot|oh)$"), "o"),
    (re.compile(r"(.)\1+"), r"\1"),
)


def known_names(extra: str) -> tuple[str, ...]:
    names: list[str] = []
    for name in (*ALWAYS_SPELLED, *re.split(r"[,;\n]", extra)):
        cleaned = " ".join(name.split())
        if cleaned and cleaned.casefold() not in {known.casefold() for known in names}:
            names.append(cleaned)
    return tuple(names)


def sound_key(word: str) -> str:
    plain = unicodedata.normalize("NFKD", word.casefold())
    key = "".join(character for character in plain if character.isalpha() and character.isascii())
    for pattern, replacement in SOUND_ALIKES:
        key = pattern.sub(replacement, key)
    return key


def one_edit_apart(first: str, second: str) -> bool:
    if abs(len(first) - len(second)) > 1 or first == second:
        return False
    if len(first) > len(second):
        first, second = second, first
    for index, (left, right) in enumerate(zip(first, second, strict=False)):
        if left != right:
            skip = 0 if len(first) == len(second) else 1
            return first[index + 1 - skip :] == second[index + 1 :]
    return True


class NameFixer:
    def __init__(self, names: Iterable[str]) -> None:
        self.names = tuple(names)
        self._names = {sound_key(name): name for name in self.names if " " not in name}

    def fix(self, text: str | None) -> str | None:
        if not text or not self._names:
            return text
        return WORD.sub(self._replace, self._join_split_names(text))

    def _join_split_names(self, text: str) -> str:
        def join(match: re.Match[str]) -> str:
            joined = match.group(1) + match.group(2)
            return joined if sound_key(joined) in self._names else match.group(0)

        return re.sub(r"\b([^\W\d_])\s+([^\W\d_]{2,})\b", join, text)

    def _replace(self, match: re.Match[str]) -> str:
        word = match.group(0)
        suffix = ""
        possessive = POSSESSIVE.search(word)
        if possessive and len(word) > 2:
            word, suffix = word[: possessive.start()], possessive.group(0)
        name = self._match(word)
        return name + suffix if name else match.group(0)

    def _match(self, word: str) -> str | None:
        key = sound_key(word)
        if key in self._names:
            return self._names[key]
        if not word[:1].isupper() or len(key) < MIN_FUZZY_LENGTH:
            return None
        close = [name for known, name in self._names.items() if one_edit_apart(key, known)]
        return close[0] if len(close) == 1 else None


def spell_names(units: list[Unit], fixer: NameFixer) -> list[Unit]:
    for unit in units:
        unit.text = fixer.fix(unit.text) or unit.text
        unit.translation = fixer.fix(unit.translation)
        for version in unit.versions:
            version.text = fixer.fix(version.text) or version.text
            version.translation = fixer.fix(version.translation)
    return units
