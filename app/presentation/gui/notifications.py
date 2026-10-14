from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from app.presentation.gui.icons import app_icon

MESSAGE_MS = 10000
TRAY_LINGER_MS = 15000


def play_sound() -> None:
    if sys.platform == "win32":
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    else:
        QApplication.beep()


class DoneNotifier:
    def __init__(self, window: QWidget) -> None:
        self._window = window
        self._tray: QSystemTrayIcon | None = None
        self._hide_timer = QTimer(window)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_tray)

    def notify(self, title: str, message: str) -> bool:
        if self._window.isActiveWindow():
            return False
        QApplication.alert(self._window, 0)
        play_sound()
        tray = self._tray_icon()
        if tray is not None:
            tray.show()
            tray.showMessage(title, message, app_icon(), MESSAGE_MS)
            self._hide_timer.start(TRAY_LINGER_MS)
        return True

    def _tray_icon(self) -> QSystemTrayIcon | None:
        if self._tray is None and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(app_icon(), self._window)
            self._tray.setToolTip("ClipTranslator")
            self._tray.messageClicked.connect(self._bring_back)
            self._tray.activated.connect(lambda _reason: self._bring_back())
        return self._tray

    def _bring_back(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()
        self._hide_tray()

    def _hide_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
