from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

MEDIA_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
}
PATH_ROLE = Qt.ItemDataRole.UserRole
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1


class ClipStatus(StrEnum):
    PENDING = "Pending"
    PROCESSING = "Processing…"
    READY = "Ready to export"
    EXPORTED = "Exported"
    FAILED = "Failed"


STATUS_MARKS = {
    ClipStatus.PENDING: "○",
    ClipStatus.PROCESSING: "◐",
    ClipStatus.READY: "●",
    ClipStatus.EXPORTED: "✓",
    ClipStatus.FAILED: "✕",
}
STATUS_COLORS = {
    ClipStatus.PENDING: "#a79cc9",
    ClipStatus.PROCESSING: "#c4b5fd",
    ClipStatus.READY: "#e9d5ff",
    ClipStatus.EXPORTED: "#6ee7c8",
    ClipStatus.FAILED: "#ff7a9c",
}


def media_files_in(paths: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in MEDIA_SUFFIXES:
                resolved = candidate.resolve()
                if resolved not in found:
                    found.append(resolved)
    return found


class ClipList(QListWidget):
    paths_dropped = Signal(list)
    clip_activated = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMinimumHeight(150)
        self.itemClicked.connect(lambda item: self.clip_activated.emit(item.data(PATH_ROLE)))

    def add(self, paths: Iterable[Path]) -> list[Path]:
        known = set(self.paths())
        added = [path for path in media_files_in(paths) if path not in known]
        for path in added:
            item = QListWidgetItem()
            item.setData(PATH_ROLE, path)
            item.setToolTip(str(path))
            self.addItem(item)
            self._render(item, ClipStatus.PENDING)
        return added

    def paths(self) -> list[Path]:
        return [self.item(row).data(PATH_ROLE) for row in range(self.count())]

    def status(self, path: Path) -> ClipStatus | None:
        item = self._find(path)
        return None if item is None else ClipStatus(item.data(STATUS_ROLE))

    def set_status(self, path: Path, status: ClipStatus) -> None:
        item = self._find(path)
        if item is not None:
            self._render(item, status)

    def with_status(self, *statuses: ClipStatus) -> list[Path]:
        return [path for path in self.paths() if self.status(path) in statuses]

    def select(self, path: Path) -> None:
        item = self._find(path)
        if item is not None:
            self.setCurrentItem(item)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.paths_dropped.emit(paths)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.count():
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#a79cc9"))
        painter.drawText(
            self.viewport().rect(),
            Qt.AlignmentFlag.AlignCenter,
            "Drop videos or a folder here\nor use the buttons above",
        )

    def _find(self, path: Path) -> QListWidgetItem | None:
        for row in range(self.count()):
            item = self.item(row)
            if item.data(PATH_ROLE) == path:
                return item
        return None

    @staticmethod
    def _render(item: QListWidgetItem, status: ClipStatus) -> None:
        path: Path = item.data(PATH_ROLE)
        item.setData(STATUS_ROLE, status.value)
        item.setText(f"{STATUS_MARKS[status]}   {path.name}\n      {status.value}")
        item.setForeground(QColor(STATUS_COLORS[status]))
