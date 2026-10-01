from __future__ import annotations

from collections.abc import Callable
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QUndoStack

from app.domain.models import Cue, Reading
from app.domain.text import collapse_spaces
from app.domain.timing import InvalidTimingError, edit_time_text, parse_time_text, retime, shift
from app.presentation.gui.edit_commands import Changes, CueEditCommand, CueState, record_changes
from app.presentation.gui.texts import flag_labels

FLAGGED_ROW_COLOR = QColor(255, 196, 0, 45)
ModelIndex = QModelIndex | QPersistentModelIndex
ROOT = QModelIndex()


class Column(IntEnum):
    NUMBER = 0
    START = 1
    END = 2
    ORIGINAL = 3
    TRANSLATION = 4
    FLAGS = 5


TEXT_COLUMNS = {Column.ORIGINAL, Column.TRANSLATION}
TIME_COLUMNS = {Column.START, Column.END}
EDITABLE_COLUMNS = TEXT_COLUMNS | TIME_COLUMNS
HEADERS = {
    Column.NUMBER: "#",
    Column.START: "Start",
    Column.END: "End",
    Column.ORIGINAL: "Original",
    Column.TRANSLATION: "Translation",
    Column.FLAGS: "Warnings",
}


def short_time(seconds: float) -> str:
    return edit_time_text(seconds)


class CueTableModel(QAbstractTableModel):
    edited = Signal()
    edit_rejected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cues: list[Cue] = []
        self.undo_stack = QUndoStack(self)

    def set_cues(self, cues: list[Cue]) -> None:
        self.beginResetModel()
        self._cues = cues
        self.undo_stack.clear()
        self.endResetModel()

    def refresh_rows(self, rows: list[int]) -> None:
        for row in rows:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(Column) - 1))

    def refresh_row(self, row: int) -> None:
        self.refresh_rows([row])

    def cue_at(self, row: int) -> Cue | None:
        return self._cues[row] if 0 <= row < len(self._cues) else None

    def shift_rows(self, rows: list[int], seconds: float) -> None:
        valid = [row for row in rows if self.cue_at(row) is not None]
        if not valid or seconds == 0:
            return
        direction = "later" if seconds > 0 else "earlier"
        self._push(
            f"Move {len(valid)} line(s) {abs(seconds):.2f} s {direction}",
            valid,
            lambda: shift([self._cues[row] for row in valid], seconds),
        )

    def use_version(self, row: int, version: Reading) -> None:
        cue = self.cue_at(row)
        if cue is None:
            return

        def mutate() -> None:
            cue.original = version.text
            cue.translation = version.translation or ""

        self._push(f"Choose a version of line {cue.index}", [row], mutate)

    def record_external_change(self, row: int, before: CueState, description: str) -> None:
        cue = self.cue_at(row)
        if cue is None or CueState.of(cue) == before:
            return
        changes: Changes = {row: (before, CueState.of(cue))}
        self.undo_stack.push(CueEditCommand(description, self._cues, changes, self._applied))

    def rowCount(self, parent: ModelIndex = ROOT) -> int:
        return 0 if parent.isValid() else len(self._cues)

    def columnCount(self, parent: ModelIndex = ROOT) -> int:
        return 0 if parent.isValid() else len(Column)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[Column(section)]
        return None

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        cue = self.cue_at(index.row())
        if cue is None:
            return None
        column = Column(index.column())
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._value(cue, column)
        if role == Qt.ItemDataRole.BackgroundRole and cue.flags:
            return FLAGGED_ROW_COLOR
        if role == Qt.ItemDataRole.ToolTipRole:
            if column is Column.FLAGS:
                return flag_labels(cue.flags)
            if column in TIME_COLUMNS:
                return "Double-click to edit, for example 1:08.50"
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if Column(index.column()) in EDITABLE_COLUMNS:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        cue = self.cue_at(index.row())
        column = Column(index.column())
        if cue is None or role != Qt.ItemDataRole.EditRole or column not in EDITABLE_COLUMNS:
            return False
        try:
            mutate = self._mutation(cue, column, str(value))
        except InvalidTimingError as error:
            self.edit_rejected.emit(str(error))
            return False
        self._push(f"Edit line {cue.index}", [index.row()], mutate)
        return True

    def _mutation(self, cue: Cue, column: Column, value: str) -> Callable[[], None]:
        if column in TEXT_COLUMNS:
            text = collapse_spaces(value)
            if column is Column.ORIGINAL:
                return lambda: setattr(cue, "original", text)
            return lambda: setattr(cue, "translation", text)
        seconds = parse_time_text(value)
        start = seconds if column is Column.START else cue.start
        end = seconds if column is Column.END else cue.end
        if start < 0 or end - start <= 0:
            raise InvalidTimingError("The end time must be after the start time.")
        return lambda: retime(cue, start, end)

    def _push(self, description: str, rows: list[int], mutate: Callable[[], None]) -> None:
        try:
            changes = record_changes(self._cues, rows, mutate)
        except InvalidTimingError as error:
            self.edit_rejected.emit(str(error))
            return
        if changes:
            self.undo_stack.push(CueEditCommand(description, self._cues, changes, self._applied))

    def _applied(self, rows: list[int]) -> None:
        self.refresh_rows(rows)
        self.edited.emit()

    def _value(self, cue: Cue, column: Column) -> str:
        values = {
            Column.NUMBER: str(cue.index),
            Column.START: short_time(cue.start),
            Column.END: short_time(cue.end),
            Column.ORIGINAL: cue.original,
            Column.TRANSLATION: cue.translation,
            Column.FLAGS: flag_labels(cue.flags),
        }
        return values[column]
