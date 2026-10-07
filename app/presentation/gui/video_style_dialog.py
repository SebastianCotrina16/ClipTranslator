from __future__ import annotations

import itertools
import logging
import tempfile
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.domain.subtitle_style import (
    FONT_SIZES,
    TEXT_COLORS,
    Background,
    Position,
    SubtitleStyle,
)
from app.infrastructure.ffmpeg import render_preview

log = logging.getLogger(__name__)

PREVIEW_DELAY_MS = 200
PREVIEW_SIZE = (640, 360)
SWATCH_SIZE = 14
CHOOSE_COLOR = "choose"
SAMPLE_TEXT = "This is how your subtitles\nwill look in the video"
BACKGROUNDS = {
    "Semi-transparent box": Background.BOX,
    "Black outline": Background.OUTLINE,
}
POSITIONS = {"Bottom": Position.BOTTOM, "Top": Position.TOP}
MUSIC_NOTE = "Keeps only the voices. Songs with singing may stay, and game sounds are removed too."
NOTHING_CHOSEN = "Choose subtitles, removing the music, or both."


class PreviewRender(QObject):
    rendered = Signal(int, str)
    failed = Signal(int, str)

    def __init__(self, number: int, render: Callable[[], Path]) -> None:
        super().__init__()
        self._number = number
        self._render = render

    def run(self) -> None:
        try:
            output = self._render()
        except Exception as error:
            log.exception("Rendering the subtitle preview failed")
            self.failed.emit(self._number, str(error))
            return
        self.rendered.emit(self._number, str(output))


def color_swatch(color: str) -> QIcon:
    pixmap = QPixmap(SWATCH_SIZE, SWATCH_SIZE)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class VideoStyleDialog(QDialog):
    def __init__(
        self,
        media: Path,
        seconds: float,
        text: str,
        style: SubtitleStyle,
        parent: QWidget | None = None,
        burn_subtitles: bool = True,
        remove_music: bool = False,
    ) -> None:
        super().__init__(parent)
        self._media = media
        self._seconds = seconds
        self._text = text.strip() or SAMPLE_TEXT
        self._folder = tempfile.TemporaryDirectory(
            prefix="cliptranslator-preview-", ignore_cleanup_errors=True
        )
        self._numbers = itertools.count(1)
        self._latest = 0
        self._rendering: PreviewRender | None = None
        self._text_color = style.text_color
        self._subtitles = QCheckBox("Add the subtitles to the video")
        self._no_music = QCheckBox("Remove the background music")
        self._music_note = QLabel(MUSIC_NOTE)
        self._style_box = QWidget()
        self._color = QComboBox()
        self._background = QComboBox()
        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity_value = QLabel()
        self._size = QComboBox()
        self._position = QComboBox()
        self._preview = QLabel("Loading preview…")
        self._status = QLabel()
        self._timer = QTimer(self)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._build()
        self._show_style(style)
        self._subtitles.setChecked(burn_subtitles)
        self._no_music.setChecked(remove_music)
        self._connect()
        self._refresh()

    def burn_subtitles(self) -> bool:
        return self._subtitles.isChecked()

    def remove_music(self) -> bool:
        return self._no_music.isChecked()

    def style(self) -> SubtitleStyle:
        return SubtitleStyle(
            text_color=self._text_color,
            background=Background(self._background.currentData()),
            box_opacity=self._opacity.value(),
            font_size=self._size.currentData(),
            position=Position(self._position.currentData()),
        )

    def done(self, result: int) -> None:
        self._timer.stop()
        self._folder.cleanup()
        super().done(result)

    def _build(self) -> None:
        self.setWindowTitle("Export video")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(*PREVIEW_SIZE)
        self._preview.setStyleSheet("background: #000; border-radius: 8px; color: #aaa;")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        self._music_note.setObjectName("muted")
        self._music_note.setWordWrap(True)
        self._opacity.setRange(0, 100)
        self._opacity.setSingleStep(5)
        self._opacity_value.setFixedWidth(44)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        export_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        export_button.setText("Export video")
        export_button.setObjectName("primary")
        for name, color in TEXT_COLORS.items():
            self._color.addItem(color_swatch(color), name, color)
        self._color.addItem("Choose another color…", CHOOSE_COLOR)
        for name, background in BACKGROUNDS.items():
            self._background.addItem(name, background.value)
        for name, size in FONT_SIZES.items():
            self._size.addItem(name, size)
        for name, position in POSITIONS.items():
            self._position.addItem(name, position.value)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity, stretch=1)
        opacity_row.addWidget(self._opacity_value)
        form = QFormLayout(self._style_box)
        form.setContentsMargins(24, 0, 0, 0)
        form.addRow("Text color", self._color)
        form.addRow("Background", self._background)
        form.addRow("Box opacity", opacity_row)
        form.addRow("Text size", self._size)
        form.addRow("Position", self._position)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._status)
        layout.addWidget(self._subtitles)
        layout.addWidget(self._style_box)
        layout.addWidget(self._no_music)
        layout.addWidget(self._music_note)
        layout.addWidget(self._buttons)

    def _show_style(self, style: SubtitleStyle) -> None:
        self._select_color(style.text_color)
        self._background.setCurrentIndex(self._background.findData(style.background.value))
        self._opacity.setValue(style.box_opacity)
        size_index = self._size.findData(style.font_size)
        if size_index < 0:
            self._size.addItem(f"Custom ({style.font_size})", style.font_size)
            size_index = self._size.count() - 1
        self._size.setCurrentIndex(size_index)
        self._position.setCurrentIndex(self._position.findData(style.position.value))

    def _connect(self) -> None:
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._color.activated.connect(self._on_color_chosen)
        for combo in (self._background, self._size, self._position):
            combo.currentIndexChanged.connect(self._refresh)
        self._opacity.valueChanged.connect(self._refresh)
        self._subtitles.toggled.connect(self._refresh)
        self._no_music.toggled.connect(self._update_export_button)
        self._timer.timeout.connect(self._render)

    def _on_color_chosen(self, index: int) -> None:
        color = self._color.itemData(index)
        if color == CHOOSE_COLOR:
            chosen = QColorDialog.getColor(QColor(self._text_color), self, "Text color")
            color = chosen.name() if chosen.isValid() else self._text_color
        self._select_color(color)
        self._refresh()

    def _select_color(self, color: str) -> None:
        color = color.upper()
        self._text_color = color
        index = self._color.findData(color)
        if index < 0:
            custom = self._color.findData(CHOOSE_COLOR) - 1
            if custom >= len(TEXT_COLORS):
                self._color.removeItem(custom)
            self._color.insertItem(len(TEXT_COLORS), color_swatch(color), "Custom", color)
            index = len(TEXT_COLORS)
        self._color.setCurrentIndex(index)

    def _refresh(self) -> None:
        box = self._background.currentData() == Background.BOX.value
        self._style_box.setEnabled(self.burn_subtitles())
        self._opacity.setEnabled(box)
        self._opacity_value.setText(f"{self._opacity.value()}%")
        self._update_export_button()
        self._timer.start()

    def _update_export_button(self) -> None:
        chosen = self.burn_subtitles() or self.remove_music()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(chosen)
        if not chosen:
            self._status.setText(NOTHING_CHOSEN)
        elif self._status.text() == NOTHING_CHOSEN:
            self._status.setText("")

    def _render(self) -> None:
        if self._rendering is not None:
            self._timer.start()
            return
        number = next(self._numbers)
        self._latest = number
        output = Path(self._folder.name) / f"preview-{number}.png"
        style = self.style() if self.burn_subtitles() else None
        render = partial(render_preview, self._media, self._seconds, self._text, style, output)
        job = PreviewRender(number, render)
        job.rendered.connect(self._on_rendered)
        job.failed.connect(self._on_failed)
        self._rendering = job
        threading.Thread(target=job.run, name="PreviewRender", daemon=True).start()

    def _on_rendered(self, number: int, path: str) -> None:
        self._rendering = None
        if number != self._latest:
            return
        pixmap = QPixmap(path)
        self._preview.setPixmap(
            pixmap.scaled(
                self._preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        if self.burn_subtitles() or self.remove_music():
            self._status.setText("Preview on a frame of your video.")

    def _on_failed(self, number: int, message: str) -> None:
        self._rendering = None
        if number == self._latest:
            self._status.setText(f"The preview could not be created: {message}")
