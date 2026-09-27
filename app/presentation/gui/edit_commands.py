from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QUndoCommand

from app.domain.models import Cue


@dataclass(frozen=True)
class CueState:
    start: float
    end: float
    original: str
    translation: str

    @classmethod
    def of(cls, cue: Cue) -> CueState:
        return cls(cue.start, cue.end, cue.original, cue.translation)

    def apply_to(self, cue: Cue) -> None:
        cue.start, cue.end = self.start, self.end
        cue.original, cue.translation = self.original, self.translation


Changes = dict[int, tuple[CueState, CueState]]


class CueEditCommand(QUndoCommand):
    def __init__(
        self,
        description: str,
        cues: list[Cue],
        changes: Changes,
        on_applied: Callable[[list[int]], None],
    ) -> None:
        super().__init__(description)
        self._cues = cues
        self._changes = changes
        self._on_applied = on_applied

    def redo(self) -> None:
        self._apply(after=True)

    def undo(self) -> None:
        self._apply(after=False)

    def _apply(self, after: bool) -> None:
        for position, (before_state, after_state) in self._changes.items():
            (after_state if after else before_state).apply_to(self._cues[position])
        self._on_applied(sorted(self._changes))


def record_changes(cues: list[Cue], positions: list[int], mutate: Callable[[], None]) -> Changes:
    before = {position: CueState.of(cues[position]) for position in positions}
    mutate()
    after = {position: CueState.of(cues[position]) for position in positions}
    for position, state in before.items():
        state.apply_to(cues[position])
    return {
        position: (before[position], after[position])
        for position in positions
        if before[position] != after[position]
    }
