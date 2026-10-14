from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.corrections import CorrectionStore
from app.domain.corrections import Correction
from app.presentation.gui.texts import language_name

EXPLANATION = (
    "When you fix a word or a short phrase in a subtitle, ClipTranslator remembers it and "
    "fixes it the same way in your next clips. Remove the ones you do not want."
)
CORRECTION_ROLE = Qt.ItemDataRole.UserRole


def describe(correction: Correction) -> str:
    return f"“{correction.wrong}”  →  “{correction.right}”   ({language_name(correction.language)})"


class CorrectionsDialog(QDialog):
    def __init__(self, store: CorrectionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Remembered fixes")
        self.setMinimumSize(520, 380)
        explanation = QLabel(EXPLANATION)
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._empty = QLabel("Nothing remembered yet. Fix a subtitle and it will appear here.")
        self._empty.setObjectName("muted")
        self._remove = QPushButton("Remove selected")
        self._remove.setObjectName("danger")
        self._remove.clicked.connect(self._remove_selected)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(explanation)
        layout.addWidget(self._list, stretch=1)
        layout.addWidget(self._empty)
        layout.addWidget(self._remove, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(buttons)
        self._fill()

    def _fill(self) -> None:
        self._list.clear()
        for correction in self._store.load():
            item = QListWidgetItem(describe(correction))
            item.setData(CORRECTION_ROLE, correction)
            self._list.addItem(item)
        self._empty.setVisible(self._list.count() == 0)
        self._update_buttons()

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._store.forget(item.data(CORRECTION_ROLE))
        self._fill()

    def _update_buttons(self) -> None:
        self._remove.setEnabled(bool(self._list.selectedItems()))
