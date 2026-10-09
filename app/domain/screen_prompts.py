from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

Box = tuple[float, float, float, float]

ALBUM_WORDS = ("ALBUM", "АЛЬБОМ")
PLAYERS_WORDS = {
    "PLAYERS",
    "JUGADORES",
    "JOGADORES",
    "JOUEURS",
    "SPIELER",
    "GIOCATORI",
    "ИГРОКИ",
    "GRACZE",
    "OYUNCULAR",
    "SPELERS",
}
BUTTON_WORDS = {
    "BACK",
    "NEXT",
    "CONTINUE",
    "HOME",
    "VOLVER",
    "SEGUIR",
    "INICIO",
    "ZURUCK",
    "WEITER",
    "STARTSEITE",
    "RETOUR",
    "SUIVANT",
    "ACCUEIL",
    "VOLTAR",
    "PROXIMO",
    "AVANTI",
    "INDIETRO",
    "НАЗАД",
    "ДАЛЕЕ",
    "ДАЛЬШЕ",
    "ГЛАВНАЯ",
}
LATIN_TWINS = str.maketrans("AOMBEHKPCTXY", "АОМВЕНКРСТХУ")
MIN_LETTERS = 2
LINE_GAP = 0.9
LINE_OVERLAP = 0.4
SIMILAR_READING = 0.9


class PromptStyle(StrEnum):
    WIDEN = "widen"
    FIT = "fit"


@dataclass(frozen=True)
class Detection:
    frame: int
    box: tuple[int, int, int, int]
    text: str
    lines: int = 1


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.upper())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def is_album_title(text: str) -> bool:
    words = plain(text)
    return any(word in words or word in words.translate(LATIN_TWINS) for word in ALBUM_WORDS)


def is_players_title(text: str) -> bool:
    words = plain(text)
    return words in PLAYERS_WORDS or words.translate(LATIN_TWINS) in PLAYERS_WORDS


def is_button(text: str) -> bool:
    words = plain(text)
    if words in BUTTON_WORDS:
        return True
    return len(words) >= 4 and any(button.startswith(words) for button in BUTTON_WORDS)


def is_readable(text: str) -> bool:
    return sum(character.isalpha() for character in text) >= MIN_LETTERS


def prompt_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def cut_from(short: str, long: str) -> bool:
    if short == long:
        return False
    at = long.find(short)
    if at >= 0:
        before = long[at - 1] if at > 0 else " "
        after = long[at + len(short)] if at + len(short) < len(long) else " "
        return before.isalnum() or after.isalnum()
    similar = difflib.SequenceMatcher(None, short, long).ratio() >= SIMILAR_READING
    return abs(len(short) - len(long)) <= 2 and similar


def canonical_keys(keys: Iterable[str]) -> dict[str, str]:
    ordered = sorted(set(keys), key=lambda key: (-len(key), key))
    mapping: dict[str, str] = {}
    for key in ordered:
        mapping[key] = next(
            (
                other
                for other in ordered
                if other != key
                and len(other) >= len(key)
                and mapping.get(other) == other
                and cut_from(key, other)
            ),
            key,
        )
    return mapping


def group_lines(boxes: Iterable[Box], inside_card: Callable[[Box], bool]) -> list[list[Box]]:
    groups: list[list[Box]] = []
    for box in sorted(boxes, key=lambda found: found[1]):
        height = box[3] - box[1]
        joined = False
        if inside_card(box):
            for group in groups:
                last = group[-1]
                overlap = min(last[2], box[2]) - max(last[0], box[0])
                narrower = min(last[2] - last[0], box[2] - box[0])
                close = -LINE_OVERLAP * height <= box[1] - last[3] < LINE_GAP * height
                if close and overlap > 0.3 * narrower and inside_card(last):
                    group.append(box)
                    joined = True
                    break
        if not joined:
            groups.append([box])
    return groups


def union(boxes: list[Box]) -> Box:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


@dataclass
class PromptScan:
    width: int
    height: int
    fps: float
    detections: list[Detection]
    templates: list[Any]
