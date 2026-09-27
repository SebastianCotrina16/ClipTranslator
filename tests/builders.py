from __future__ import annotations

from app.domain.models import Segment, Unit, Word


def make_words(
    text: str, start: float = 0.0, step: float = 0.3, pauses: dict[int, float] | None = None
) -> list[Word]:
    pauses = pauses or {}
    words: list[Word] = []
    moment = start
    for index, token in enumerate(text.split()):
        moment += pauses.get(index, 0.0)
        words.append(
            Word(start=round(moment, 3), end=round(moment + step * 0.8, 3), text=" " + token)
        )
        moment += step
    return words


def make_segment(
    text: str,
    start: float = 0.0,
    segment_id: int = 0,
    step: float = 0.3,
    pauses: dict[int, float] | None = None,
    **quality: float,
) -> Segment:
    words = make_words(text, start, step, pauses)
    return Segment(
        id=segment_id,
        start=words[0].start,
        end=words[-1].end,
        text=text,
        words=words,
        **quality,
    )


def make_unit(
    text: str,
    translation: str | None,
    start: float = 0.0,
    step: float = 0.3,
    unit_id: int = 0,
) -> Unit:
    words = make_words(text, start, step)
    return Unit(
        id=unit_id,
        start=words[0].start,
        end=words[-1].end,
        text=text,
        words=words,
        translation=translation,
    )
