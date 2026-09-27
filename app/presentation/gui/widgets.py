from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.presentation.gui.icons import icon

CARD_PADDING = 18


def card(*children: QWidget | QLayout, spacing: int = 12) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
    layout.setSpacing(spacing)
    for child in children:
        if isinstance(child, QLayout):
            layout.addLayout(child)
        else:
            layout.addWidget(child)
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(40)
    shadow.setOffset(0, 12)
    shadow.setColor(Qt.GlobalColor.black)
    frame.setGraphicsEffect(shadow)
    return frame


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("section")
    return label


def icon_button(text: str, icon_name: str, object_name: str = "") -> QPushButton:
    button = QPushButton(icon(icon_name), f"  {text}" if text else "")
    button.setIconSize(QSize(18, 18))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if object_name:
        button.setObjectName(object_name)
    return button


class DropZone(QFrame):
    file_dropped = Signal(Path)
    browse_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        self._icon = QLabel()
        self._icon.setPixmap(icon("upload", "#c4b5fd").pixmap(34, 34))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel("Drop a video or audio file")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self._hint = QLabel("or click to browse")
        self._hint.setObjectName("muted")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.addStretch(1)
        layout.addWidget(self._icon)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def show_file(self, media: Path) -> None:
        self._icon.setPixmap(icon("film", "#c4b5fd").pixmap(34, 34))
        self._title.setText(media.name)
        self._hint.setText("Click or drop another file to replace it")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse_requested.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.file_dropped.emit(Path(url.toLocalFile()))
                return

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class NoticeBox(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("notice")
        self._label = QLabel()
        self._label.setObjectName("noticeText")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self._label)
        self._messages: list[str] = []
        self.hide()

    def add(self, message: str) -> None:
        if message in self._messages:
            return
        self._messages.append(message)
        self._label.setText("\n\n".join(self._messages))
        self.show()

    def clear(self) -> None:
        self._messages.clear()
        self._label.clear()
        self.hide()
