from __future__ import annotations

from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from app.domain.models import Cue
from app.domain.text import collapse_spaces
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


EDITABLE_COLUMNS = {Column.ORIGINAL, Column.TRANSLATION}
HEADERS = {
    Column.NUMBER: "#",
    Column.START: "Start",
    Column.END: "End",
    Column.ORIGINAL: "Original",
    Column.TRANSLATION: "Translation",
    Column.FLAGS: "Warnings",
}


def short_time(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes)}:{rest:05.2f}"


class CueTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._cues: list[Cue] = []

    def set_cues(self, cues: list[Cue]) -> None:
        self.beginResetModel()
        self._cues = cues
        self.endResetModel()

    def cue_at(self, row: int) -> Cue | None:
        return self._cues[row] if 0 <= row < len(self._cues) else None

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
        if role == Qt.ItemDataRole.ToolTipRole and column is Column.FLAGS:
            return flag_labels(cue.flags)
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
        text = collapse_spaces(str(value))
        if column is Column.ORIGINAL:
            cue.original = text
        else:
            cue.translation = text
        self.dataChanged.emit(index, index, [role])
        return True

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
