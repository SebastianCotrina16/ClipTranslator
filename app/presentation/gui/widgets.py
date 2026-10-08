from __future__ import annotations

import html

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QToolTip,
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


def help_button(text: str) -> QPushButton:
    explanation = f"<p style='max-width: 320px'>{html.escape(text)}</p>"
    button = QPushButton("?")
    button.setObjectName("help")
    button.setCursor(Qt.CursorShape.WhatsThisCursor)
    button.setToolTip(explanation)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.clicked.connect(
        lambda: QToolTip.showText(
            button.mapToGlobal(QPoint(0, button.height())), explanation, button
        )
    )
    return button


def with_help(widget: QWidget, text: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(widget)
    row.addWidget(help_button(text))
    row.addStretch(1)
    return row


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
    update_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("banner")
        self._url = ""
        self._automatic = False
        self._label = QLabel()
        self._label.setObjectName("bannerText")
        self._label.setWordWrap(True)
        self._action = icon_button("Download", "download", "primary")
        self._dismiss = QPushButton("✕")
        self._dismiss.setObjectName("ghost")
        self._dismiss.setFixedWidth(36)
        self._dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action.clicked.connect(self._on_action)
        self._dismiss.clicked.connect(self.hide)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 10)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(self._action)
        layout.addWidget(self._dismiss)
        self.hide()

    def show_release(self, version: str, url: str, automatic: bool) -> None:
        self._url = url
        self._automatic = automatic
        name = f"<b>ClipTranslator {version.lstrip('v')} is available.</b> "
        if automatic:
            self._label.setText(name + "Update now and the app will reopen when it is done.")
            self._action.setText("Update now")
        else:
            self._label.setText(name + "Download the new installer and run it to update.")
            self._action.setText("Download")
        self._set_busy(False)
        self.show()

    def show_progress(self, message: str) -> None:
        self._label.setText(message)
        self._set_busy(True)
        self.show()

    def show_failure(self, message: str) -> None:
        self._automatic = False
        self._label.setText(f"<b>The update did not finish.</b> {html.escape(message)}")
        self._action.setText("Download")
        self._set_busy(False)
        self.show()

    def _set_busy(self, busy: bool) -> None:
        self._action.setEnabled(not busy)
        self._dismiss.setEnabled(not busy)

    def _on_action(self) -> None:
        if self._automatic:
            self.update_requested.emit()
        else:
            self.download_requested.emit(self._url)
