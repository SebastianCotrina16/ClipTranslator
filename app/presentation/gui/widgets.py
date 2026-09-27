from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
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


class UpdateBanner(QFrame):
    download_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("banner")
        self._url = ""
        self._label = QLabel()
        self._label.setObjectName("bannerText")
        download = icon_button("Download", "download", "primary")
        dismiss = QPushButton("✕")
        dismiss.setObjectName("ghost")
        dismiss.setFixedWidth(36)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        download.clicked.connect(lambda: self.download_requested.emit(self._url))
        dismiss.clicked.connect(self.hide)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 10)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(download)
        layout.addWidget(dismiss)
        self.hide()

    def show_release(self, version: str, url: str) -> None:
        self._url = url
        self._label.setText(
            f"<b>ClipTranslator {version.lstrip('v')} is available.</b> "
            "Download the new installer and run it to update."
        )
        self.show()
