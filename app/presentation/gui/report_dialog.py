from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

EXPLANATION = (
    "Creates a .zip file on your Desktop that helps find and fix problems. "
    "Send it to the developer (Discord, WhatsApp…).\n\n"
    "It includes: the app version, your computer and GPU, your settings (without API keys), "
    "how long each step took on your recent clips, and any errors.\n\n"
    "It never includes your videos or audio, and your Windows user name is removed."
)


class ReportDialog(QDialog):
    def __init__(self, has_subtitles: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report a problem")
        self.setMinimumWidth(480)
        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        self._subtitles = QCheckBox("Include the subtitles of the current clip")
        self._subtitles.setEnabled(has_subtitles)
        self._subtitles.setToolTip("Useful when a translation or transcription looks wrong.")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        create = buttons.button(QDialogButtonBox.StandardButton.Ok)
        create.setText("Create report")
        create.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(explanation)
        layout.addWidget(self._subtitles)
        layout.addWidget(buttons)

    def include_subtitles(self) -> bool:
        return self._subtitles.isEnabled() and self._subtitles.isChecked()
