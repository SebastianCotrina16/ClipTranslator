from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from app.application.whats_new import ReleaseNotes, as_markdown, parse_notes

log = logging.getLogger(__name__)

NOTES_FILE = Path(__file__).resolve().parents[2] / "assets" / "whats_new.md"


def bundled_notes() -> list[ReleaseNotes]:
    try:
        return parse_notes(NOTES_FILE.read_text(encoding="utf-8"))
    except OSError as error:
        log.warning("Could not read the release notes: %s", error)
        return []


class WhatsNewDialog(QDialog):
    def __init__(
        self, notes: list[ReleaseNotes], title: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 460)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setMarkdown(as_markdown(notes))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        done = buttons.button(QDialogButtonBox.StandardButton.Ok)
        done.setText("Got it")
        done.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(text, stretch=1)
        layout.addWidget(buttons)
