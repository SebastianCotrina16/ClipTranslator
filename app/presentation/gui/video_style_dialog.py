from __future__ import annotations

import itertools
import logging
import tempfile
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.domain.audio_leveling import (
    LOUDEST_TARGET,
    QUIETEST_TARGET,
    TAME_CHOICES,
    Leveling,
    Tame,
    target_hint,
)
from app.domain.subtitle_style import (
    FONT_SIZES,
    TEXT_COLORS,
    Background,
    Position,
    SubtitleStyle,
)
from app.infrastructure.ffmpeg import loudest_moment, render_audio_preview, render_preview
from app.presentation.gui.widgets import help_button, section_label, with_help

log = logging.getLogger(__name__)

PREVIEW_DELAY_MS = 200
PREVIEW_SIZE = (640, 360)
SWATCH_SIZE = 14
INDENT = 28
CHOOSE_COLOR = "choose"
SAMPLE_TEXT = "This is how your subtitles\nwill look in the video"
BACKGROUNDS = {
    "Semi-transparent box": Background.BOX,
    "Black outline": Background.OUTLINE,
}
POSITIONS = {"Bottom": Position.BOTTOM, "Top": Position.TOP}
NOTHING_CHOSEN = "Choose at least one option."
LISTEN = "▶  Listen"
COMPARE = "▶  Original"
STOP = "■  Stop"
SUBTITLES_HELP = (
    "Burns the subtitles into the picture with the style below. Untick it to get a clean "
    "video and import the .srt into CapCut instead, so zooms and PNGs never cover the text."
)
MUSIC_HELP = (
    "Keeps only the voices and removes everything else, which helps against copyrighted "
    "music. Songs with singing may partly stay (the singer is a voice too), and game "
    "sounds are removed as well."
)
LEVEL_HELP = (
    "Makes the whole clip sound evenly loud: quiet voices go up, screams go down, and the "
    "audio stops clipping (that crackly sound when a mic is too loud)."
)
VOLUME_HELP = (
    "How loud the final video is. -14 is what YouTube, TikTok and Instagram expect: louder "
    "videos get turned down by them anyway, and quieter ones sound weak next to others."
)
TAME_HELP = (
    "How much screams and sudden loud moments are softened compared to normal talking. "
    "Off keeps them as they are, Strong makes everything almost the same volume."
)
LISTEN_HELP = (
    "Plays the loudest 10 seconds of your clip with these settings, so you can hear the "
    "result before exporting. Original plays the same moment without any changes."
)


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
            log.exception("Rendering a preview failed")
            self.failed.emit(self._number, str(error))
            return
        self.rendered.emit(self._number, str(output))


def color_swatch(color: str) -> QIcon:
    pixmap = QPixmap(SWATCH_SIZE, SWATCH_SIZE)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def panel(*rows: QWidget | QHBoxLayout) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setSpacing(10)
    for row in rows:
        if isinstance(row, QHBoxLayout):
            layout.addLayout(row)
        else:
            layout.addWidget(row)
    layout.addStretch(1)
    return frame


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
        level_audio: bool = False,
        leveling: Leveling | None = None,
        voices: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._media = media
        self._voices = voices
        self._seconds = seconds
        self._text = text.strip() or SAMPLE_TEXT
        self._folder = tempfile.TemporaryDirectory(
            prefix="cliptranslator-preview-", ignore_cleanup_errors=True
        )
        self._numbers = itertools.count(1)
        self._latest = 0
        self._latest_sound = 0
        self._loudest: dict[Path, float] = {}
        self._rendering: PreviewRender | None = None
        self._sound_job: PreviewRender | None = None
        self._sound_leveled = True
        self._text_color = style.text_color
        self._subtitles = QCheckBox("Add the subtitles to the video")
        self._no_music = QCheckBox("Remove the background music")
        self._level = QCheckBox("Level the volume")
        self._style_box = QWidget()
        self._level_box = QWidget()
        self._color = QComboBox()
        self._background = QComboBox()
        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity_value = QLabel()
        self._size = QComboBox()
        self._position = QComboBox()
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume_value = QLabel()
        self._tame = QComboBox()
        self._tame_note = muted()
        self._listen = QPushButton(LISTEN)
        self._compare = QPushButton(COMPARE)
        self._sound_status = muted()
        self._player = QMediaPlayer(self)
        self._speaker = QAudioOutput(self)
        self._preview = QLabel("Loading preview…")
        self._status = QLabel()
        self._timer = QTimer(self)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._build()
        self._show_style(style)
        self._show_leveling(leveling or Leveling())
        self._subtitles.setChecked(burn_subtitles)
        self._no_music.setChecked(remove_music)
        self._level.setChecked(level_audio)
        self._connect()
        self._refresh()

    def burn_subtitles(self) -> bool:
        return self._subtitles.isChecked()

    def remove_music(self) -> bool:
        return self._no_music.isChecked()

    def level_audio(self) -> bool:
        return self._level.isChecked()

    def leveling(self) -> Leveling:
        return Leveling(self._volume.value(), Tame(self._tame.currentData()))

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
        self._player.stop()
        self._player.setSource(QUrl())
        self._folder.cleanup()
        super().done(result)

    def _build(self) -> None:
        self.setWindowTitle("Export video")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(*PREVIEW_SIZE)
        self._preview.setStyleSheet("background: #000; border-radius: 8px; color: #aaa;")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        self._player.setAudioOutput(self._speaker)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        export_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        export_button.setText("Export video")
        export_button.setObjectName("primary")
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._status)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(self._subtitles_panel(), stretch=1)
        columns.addWidget(self._audio_panel(), stretch=1)
        layout.addLayout(columns)
        layout.addWidget(self._buttons)

    def _subtitles_panel(self) -> QFrame:
        for name, color in TEXT_COLORS.items():
            self._color.addItem(color_swatch(color), name, color)
        self._color.addItem("Choose another color…", CHOOSE_COLOR)
        for name, background in BACKGROUNDS.items():
            self._background.addItem(name, background.value)
        for name, size in FONT_SIZES.items():
            self._size.addItem(name, size)
        for name, position in POSITIONS.items():
            self._position.addItem(name, position.value)
        self._opacity.setRange(0, 100)
        self._opacity.setSingleStep(5)
        self._opacity_value.setFixedWidth(44)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity, stretch=1)
        opacity_row.addWidget(self._opacity_value)
        form = QFormLayout(self._style_box)
        form.setContentsMargins(INDENT, 0, 0, 0)
        form.addRow("Text color", self._color)
        form.addRow("Background", self._background)
        form.addRow("Box opacity", opacity_row)
        form.addRow("Text size", self._size)
        form.addRow("Position", self._position)
        return panel(
            section_label("Subtitles"),
            with_help(self._subtitles, SUBTITLES_HELP),
            self._style_box,
        )

    def _audio_panel(self) -> QFrame:
        self._volume.setRange(QUIETEST_TARGET, LOUDEST_TARGET)
        self._volume.setSingleStep(1)
        self._volume.setPageStep(2)
        self._volume.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._volume.setTickInterval(2)
        self._volume_value.setWordWrap(True)
        for tame, (name, _) in TAME_CHOICES.items():
            self._tame.addItem(name, tame.value)
        for button in (self._listen, self._compare):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listen.setObjectName("primary")
        volume_row = QHBoxLayout()
        volume_row.addWidget(muted("Quieter"))
        volume_row.addWidget(self._volume, stretch=1)
        volume_row.addWidget(muted("Louder"))
        listen_row = QHBoxLayout()
        listen_row.addWidget(self._listen, stretch=1)
        listen_row.addWidget(self._compare)
        listen_row.addWidget(help_button(LISTEN_HELP))
        level = QVBoxLayout(self._level_box)
        level.setContentsMargins(INDENT, 0, 0, 0)
        level.setSpacing(8)
        level.addLayout(with_help(QLabel("Volume"), VOLUME_HELP))
        level.addLayout(volume_row)
        level.addWidget(self._volume_value)
        level.addSpacing(4)
        level.addLayout(with_help(QLabel("Tame loud moments"), TAME_HELP))
        level.addWidget(self._tame)
        level.addWidget(self._tame_note)
        level.addSpacing(4)
        level.addLayout(listen_row)
        level.addWidget(self._sound_status)
        return panel(
            section_label("Audio"),
            with_help(self._no_music, MUSIC_HELP),
            with_help(self._level, LEVEL_HELP),
            self._level_box,
        )

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

    def _show_leveling(self, leveling: Leveling) -> None:
        self._volume.setValue(leveling.target)
        self._tame.setCurrentIndex(self._tame.findData(leveling.tame.value))
        self._describe_leveling()

    def _connect(self) -> None:
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._color.activated.connect(self._on_color_chosen)
        for combo in (self._background, self._size, self._position):
            combo.currentIndexChanged.connect(self._refresh)
        self._opacity.valueChanged.connect(self._refresh)
        self._subtitles.toggled.connect(self._refresh)
        for box in (self._no_music, self._level):
            box.toggled.connect(self._refresh_audio)
        self._volume.valueChanged.connect(self._describe_leveling)
        self._tame.currentIndexChanged.connect(self._describe_leveling)
        self._listen.clicked.connect(lambda: self._play(leveled=True))
        self._compare.clicked.connect(lambda: self._play(leveled=False))
        self._player.playbackStateChanged.connect(self._on_playback)
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
        self._refresh_audio()
        self._timer.start()

    def _refresh_audio(self) -> None:
        self._level_box.setEnabled(self.level_audio())
        self._update_export_button()

    def _describe_leveling(self) -> None:
        target = self._volume.value()
        self._volume_value.setText(f"<b>{target} LUFS</b> · {target_hint(target)}")
        self._tame_note.setText(TAME_CHOICES[Tame(self._tame.currentData())][1])

    def _update_export_button(self) -> None:
        chosen = self.burn_subtitles() or self.remove_music() or self.level_audio()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(chosen)
        if not chosen:
            self._status.setText(NOTHING_CHOSEN)
        elif self._status.text() == NOTHING_CHOSEN:
            self._status.setText("")

    def _sound_source(self) -> Path:
        if self.remove_music() and self._voices is not None and self._voices.is_file():
            return self._voices
        return self._media

    def _play(self, leveled: bool) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
            return
        number = next(self._numbers)
        self._latest_sound = number
        source = self._sound_source()
        output = Path(self._folder.name) / f"sound-{number}.wav"
        leveling = self.leveling() if leveled else None
        render = partial(self._render_sound, source, leveling, output)
        job = PreviewRender(number, render)
        self._sound_leveled = leveled
        job.rendered.connect(self._on_sound)
        job.failed.connect(self._on_sound_failed)
        for button in (self._listen, self._compare):
            button.setEnabled(False)
        self._sound_status.setText("Preparing the loudest 10 seconds of your clip…")
        self._sound_job = job
        threading.Thread(target=job.run, name="SoundPreview", daemon=True).start()

    def _render_sound(self, source: Path, leveling: Leveling | None, output: Path) -> Path:
        if source not in self._loudest:
            self._loudest[source] = loudest_moment(source)
        return render_audio_preview(source, self._loudest[source], leveling, output)

    def _on_sound(self, number: int, path: str) -> None:
        leveled = self._sound_leveled
        for button in (self._listen, self._compare):
            button.setEnabled(True)
        if number != self._latest_sound:
            return
        start = self._loudest.get(self._sound_source(), 0.0)
        moment = f"{int(start // 60)}:{int(start % 60):02d}"
        what = "with your settings" if leveled else "the original sound"
        self._sound_status.setText(f"Playing {what}, from {moment} in your clip.")
        (self._listen if leveled else self._compare).setText(STOP)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _on_sound_failed(self, number: int, message: str) -> None:
        for button in (self._listen, self._compare):
            button.setEnabled(True)
        if number == self._latest_sound:
            self._sound_status.setText(f"The sound preview could not be created: {message}")

    def _on_playback(self, state: QMediaPlayer.PlaybackState) -> None:
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self._listen.setText(LISTEN)
            self._compare.setText(COMPARE)

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
        if self.burn_subtitles() or self.remove_music() or self.level_audio():
            self._status.setText("Preview on a frame of your video.")

    def _on_failed(self, number: int, message: str) -> None:
        self._rendering = None
        if number == self._latest:
            self._status.setText(f"The preview could not be created: {message}")
