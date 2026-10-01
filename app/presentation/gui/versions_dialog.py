from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import Cue, Reading

MODEL_NAMES = {
    "large-v3": "Main model (Whisper large-v3)",
    "large-v2": "Second model (Whisper large-v2)",
    "large-v3-turbo": "Whisper large-v3-turbo",
    "medium": "Whisper medium",
}


def model_name(source: str) -> str:
    return MODEL_NAMES.get(source, f"Whisper {source}")


def describe(version: Reading) -> str:
    translation = version.translation or "(not translated)"
    return f"{model_name(version.source)}\n{version.text}\n→ {translation}"


class VersionsDialog(QDialog):
    def __init__(self, cue: Cue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._versions = cue.versions
        self._group = QButtonGroup(self)
        self.setWindowTitle(f"Line {cue.index}: choose a version")
        self.setMinimumWidth(560)
        intro = QLabel(
            "The models heard this part differently. "
            "Pick the version that makes the most sense in the clip."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(intro)
        for position, version in enumerate(self._versions):
            option = QRadioButton(describe(version))
            option.setChecked(version.text == cue.original)
            self._group.addButton(option, position)
            layout.addWidget(option)
        if self._group.checkedId() < 0 and self._versions:
            self._group.button(0).setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use this version")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> Reading:
        return self._versions[max(self._group.checkedId(), 0)]
