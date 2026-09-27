from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.models import Cue, Flag, Unit, Word
from app.domain.text import collapse_spaces, ends_clause, ends_sentence, join_words


@dataclass(frozen=True)
class CueRules:
    max_line_chars: int = 42
    max_lines: int = 2
    min_duration: float = 1.0
    max_duration: float = 7.0
    max_cps: float = 20.0
    gap: float = 0.08
    lead_in: float = 0.1

    @property
    def max_chars(self) -> int:
        return self.max_line_chars * self.max_lines


@dataclass
class _CuePart:
    start: float
    end: float
    original: str
    translation: str


MIN_CUE_SECONDS = 0.2


def wrap_lines(text: str, max_line_chars: int = 42) -> list[str]:
    text = collapse_spaces(text)
    if len(text) <= max_line_chars:
        return [text] if text else []
    balanced = _balanced_two_lines(text.split(" "), max_line_chars)
    return balanced if balanced is not None else _greedy_lines(text.split(" "), max_line_chars)


def fits_on_screen(text: str, rules: CueRules) -> bool:
    lines = wrap_lines(text, rules.max_line_chars)
    return len(lines) <= rules.max_lines and all(
        len(line) <= rules.max_line_chars for line in lines
    )


def format_for_screen(text: str, rules: CueRules) -> str:
    return "\n".join(wrap_lines(text, rules.max_line_chars))


def _balanced_two_lines(tokens: list[str], max_line_chars: int) -> list[str] | None:
    best: tuple[float, list[str]] | None = None
    for index in range(1, len(tokens)):
        first, second = " ".join(tokens[:index]), " ".join(tokens[index:])
        if len(first) > max_line_chars or len(second) > max_line_chars:
            continue
        score = _line_break_score(first, second)
        if best is None or score < best[0]:
            best = (score, [first, second])
    return best[1] if best else None


def _line_break_score(first: str, second: str) -> float:
    score = float(max(len(first), len(second)))
    if ends_sentence(first):
        score -= 8
    elif ends_clause(first):
        score -= 5
    return score


def _greedy_lines(tokens: list[str], max_line_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current} {token}".strip()
        if current and len(candidate) > max_line_chars:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _punctuation_bonus(previous_token: str) -> float:
    if ends_sentence(previous_token):
        return 0.2
    if ends_clause(previous_token):
        return 0.12
    return 0.0


def _cumulative(lengths: list[int]) -> list[int]:
    totals = [0]
    for length in lengths:
        totals.append(totals[-1] + length)
    return totals


def _choose_word_cuts(lengths: list[int], parts: int, bonus: list[float]) -> list[int]:
    total = sum(lengths) or 1
    cumulative = _cumulative(lengths)
    cuts: list[int] = []
    last = 0
    for part in range(1, parts):
        target = total * part / parts
        best_index, best_score = None, float("inf")
        for index in range(last + 1, len(lengths) - (parts - part) + 1):
            score = abs(cumulative[index] - target) / total - bonus[index]
            if score < best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        cuts.append(best_index)
        last = best_index
    return cuts


def split_text_at_fractions(text: str, fractions: list[float]) -> list[str]:
    tokens = text.split()
    if not fractions:
        return [" ".join(tokens)]
    cumulative = _cumulative([len(token) + 1 for token in tokens])
    total = cumulative[-1] or 1
    cuts: list[int] = []
    last = 0
    for position, fraction in enumerate(fractions, start=1):
        remaining = len(fractions) - position + 1
        best_index, best_score = None, float("inf")
        for index in range(last + 1, len(tokens) - remaining + 1):
            score = abs(cumulative[index] / total - fraction) - _punctuation_bonus(
                tokens[index - 1]
            )
            if score < best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        cuts.append(best_index)
        last = best_index
    bounds = [0, *cuts, len(tokens)]
    return [" ".join(tokens[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)]


class CueBuilder:
    def __init__(self, rules: CueRules | None = None) -> None:
        self.rules = rules or CueRules()

    def build(self, units: list[Unit]) -> list[Cue]:
        cues: list[Cue] = []
        for unit in units:
            translated = unit.translation is not None
            flags = list(unit.flags)
            if not translated and Flag.UNTRANSLATED not in flags:
                flags.append(Flag.UNTRANSLATED)
            for part in self._split_unit(unit, unit.translation or unit.text):
                cues.append(
                    Cue(
                        index=len(cues) + 1,
                        start=part.start,
                        end=part.end,
                        original=part.original,
                        translation=part.translation if translated else "",
                        unit_id=unit.id,
                        flags=list(flags),
                    )
                )
        self._adjust_timing(cues)
        return cues

    def _split_unit(self, unit: Unit, translation: str) -> list[_CuePart]:
        rules = self.rules
        longest = max(len(unit.text), len(translation))
        parts = max(
            1,
            math.ceil((unit.end - unit.start) / rules.max_duration),
            math.ceil(longest / rules.max_chars),
            math.ceil(len(translation) / (rules.max_cps * rules.max_duration)),
        )
        max_parts = max(len(unit.words), 1)
        while True:
            pieces = self._split_into(unit, translation, parts)
            readable = all(
                fits_on_screen(p.original, rules) and fits_on_screen(p.translation, rules)
                for p in pieces
            )
            if readable or parts >= max_parts or len(pieces) < parts:
                return pieces
            parts += 1

    @staticmethod
    def _split_into(unit: Unit, translation: str, parts: int) -> list[_CuePart]:
        words: list[Word] = [w for w in unit.words if w.text.strip()] or unit.words
        parts = min(parts, len(words), max(len(translation.split()), 1))
        if parts <= 1:
            return [_CuePart(unit.start, unit.end, unit.text, translation)]
        lengths = [len(word.text) for word in words]
        bonus = [0.0] * (len(words) + 1)
        for index in range(1, len(words)):
            pause = max(words[index].start - words[index - 1].end, 0.0)
            bonus[index] = _punctuation_bonus(words[index - 1].text) + min(pause, 1.0) * 0.15
        cuts = _choose_word_cuts(lengths, parts, bonus)
        total = sum(lengths) or 1
        fractions = [sum(lengths[:cut]) / total for cut in cuts]
        translated = split_text_at_fractions(translation, fractions)
        corrected_by_review = collapse_spaces(unit.text) != collapse_spaces(join_words(words))
        originals = split_text_at_fractions(unit.text, fractions) if corrected_by_review else None
        bounds = [0, *cuts, len(words)]
        pieces: list[_CuePart] = []
        for position, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False)):
            chunk = words[a:b]
            if originals is None:
                original = join_words(chunk)
            else:
                original = originals[position] if position < len(originals) else ""
            pieces.append(
                _CuePart(
                    start=unit.start if position == 0 else chunk[0].start,
                    end=unit.end if position == len(bounds) - 2 else chunk[-1].end,
                    original=original,
                    translation=translated[position] if position < len(translated) else "",
                )
            )
        return pieces

    def _adjust_timing(self, cues: list[Cue]) -> None:
        rules = self.rules
        raw_starts = [cue.start for cue in cues]
        previous_end = -math.inf
        for index, cue in enumerate(cues):
            start = max(cue.start - rules.lead_in, previous_end + rules.gap, 0.0)
            text_length = len(collapse_spaces(cue.translation or cue.original))
            needed = max(rules.min_duration, text_length / rules.max_cps)
            end = max(cue.end, start + needed)
            end = min(end, start + max(rules.max_duration, cue.end - start))
            if index + 1 < len(cues):
                end = min(end, raw_starts[index + 1] - rules.gap)
            end = max(end, start + MIN_CUE_SECONDS)
            cue.start, cue.end = round(start, 3), round(end, 3)
            too_fast = text_length / (cue.end - cue.start) > rules.max_cps
            if too_fast and Flag.FAST_READING not in cue.flags:
                cue.flags.append(Flag.FAST_READING)
            previous_end = cue.end
