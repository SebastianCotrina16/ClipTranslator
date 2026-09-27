from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import Segment, Unit, Word
from app.domain.text import ends_clause, ends_sentence, join_words


@dataclass(frozen=True)
class SegmentationRules:
    pause: float = 0.4
    max_duration: float = 7.0


@dataclass
class _WordGroup:
    words: list[Word] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)


class UnitBuilder:
    def __init__(self, rules: SegmentationRules | None = None) -> None:
        self._rules = rules or SegmentationRules()

    def build(self, segments: list[Segment]) -> list[Unit]:
        units: list[Unit] = []
        for group in self._group_words(segments):
            for words in self._split_long(group.words):
                text = join_words(words)
                if text:
                    units.append(self._make_unit(len(units), words, text, group.flags))
        return units

    def _group_words(self, segments: list[Segment]) -> list[_WordGroup]:
        groups: list[_WordGroup] = []
        current = _WordGroup()

        def close_current() -> None:
            nonlocal current
            if current.words:
                groups.append(current)
            current = _WordGroup()

        for segment in segments:
            if segment.flags:
                close_current()
            for word in segment.words or [Word(segment.start, segment.end, segment.text)]:
                if current.words and word.start - current.words[-1].end >= self._rules.pause:
                    close_current()
                current.words.append(word)
                current.flags.update(segment.flags)
                if ends_sentence(word.text):
                    close_current()
            if segment.flags:
                close_current()
        close_current()
        return groups

    def _split_long(self, words: list[Word]) -> list[list[Word]]:
        duration = words[-1].end - words[0].start
        if duration <= self._rules.max_duration or len(words) < 2:
            return [words]
        cut = self._best_cut(words, duration)
        return self._split_long(words[:cut]) + self._split_long(words[cut:])

    @staticmethod
    def _best_cut(words: list[Word], duration: float) -> int:
        middle = words[0].start + duration / 2
        best_index, best_score = 1, float("-inf")
        for index in range(1, len(words)):
            previous, following = words[index - 1], words[index]
            score = -abs(previous.end - middle) / duration
            if ends_sentence(previous.text):
                score += 0.6
            elif ends_clause(previous.text):
                score += 0.4
            score += min(following.start - previous.end, 1.0) * 0.5
            if score > best_score:
                best_index, best_score = index, score
        return best_index

    @staticmethod
    def _make_unit(unit_id: int, words: list[Word], text: str, flags: set[str]) -> Unit:
        return Unit(
            id=unit_id,
            start=words[0].start,
            end=words[-1].end,
            text=text,
            words=words,
            flags=sorted(flags),
        )
