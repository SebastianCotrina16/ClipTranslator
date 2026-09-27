from __future__ import annotations

import bisect
from pathlib import Path

from PySide6.QtCore import QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QResizeEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import Cue
from app.presentation.gui.cue_table import short_time

DEFAULT_FRAME = QSizeF(1280, 720)
CAPTION_WIDTH_RATIO = 0.9
CAPTION_FONT_RATIO = 0.055
CAPTION_MARGIN_RATIO = 0.04
CAPTION_BACKGROUND = QColor(0, 0, 0, 170)


class SubtitledPlayer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._cues: list[Cue] = []
        self._starts: list[float] = []
        self._show_original = False
        self._scene = QGraphicsScene(self)
        self._video = QGraphicsVideoItem()
        self._caption_background = QGraphicsRectItem()
        self._caption = QGraphicsTextItem()
        self._view = QGraphicsView(self._scene)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._play_button = QPushButton("Play")
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._time = QLabel(short_time(0))
        self._build()

    def load(self, media: Path) -> None:
        self._player.setSource(QUrl.fromLocalFile(str(media)))
        self._player.pause()

    def set_cues(self, cues: list[Cue]) -> None:
        self._cues = cues
        self._starts = [cue.start for cue in cues]
        self.refresh_caption()

    def show_original(self, enabled: bool) -> None:
        self._show_original = enabled
        self.refresh_caption()

    def seek(self, seconds: float) -> None:
        self._player.setPosition(int(seconds * 1000))

    def refresh_caption(self) -> None:
        self._update_caption(self._player.position() / 1000)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_frame()

    def _build(self) -> None:
        self._scene.setBackgroundBrush(QBrush(Qt.GlobalColor.black))
        self._scene.addItem(self._video)
        self._caption_background.setBrush(QBrush(CAPTION_BACKGROUND))
        self._caption_background.setPen(Qt.PenStyle.NoPen)
        self._scene.addItem(self._caption_background)
        self._caption.setDefaultTextColor(Qt.GlobalColor.white)
        self._scene.addItem(self._caption)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setStyleSheet("border: 0; background: black;")
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._video.nativeSizeChanged.connect(lambda _: self._fit_frame())
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(lambda ms: self._slider.setRange(0, int(ms)))
        self._player.playbackStateChanged.connect(self._on_state)
        self._slider.sliderMoved.connect(self._player.setPosition)
        self._play_button.clicked.connect(self._toggle_playback)
        controls = QHBoxLayout()
        controls.addWidget(self._play_button)
        controls.addWidget(self._slider, stretch=1)
        controls.addWidget(self._time)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view, stretch=1)
        layout.addLayout(controls)
        self._fit_frame()

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_button.setText("Pause" if playing else "Play")

    def _on_position(self, milliseconds: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(milliseconds)
        self._slider.blockSignals(False)
        self._time.setText(short_time(milliseconds / 1000))
        self._update_caption(milliseconds / 1000)

    def _current_cue(self, seconds: float) -> Cue | None:
        position = bisect.bisect_right(self._starts, seconds) - 1
        if position < 0:
            return None
        cue = self._cues[position]
        return cue if cue.start <= seconds <= cue.end else None

    def _update_caption(self, seconds: float) -> None:
        cue = self._current_cue(seconds)
        text = ""
        if cue is not None:
            text = cue.original if self._show_original or not cue.translation else cue.translation
        self._caption.setPlainText(text)
        self._layout_caption()

    def _frame_size(self) -> QSizeF:
        size = self._video.nativeSize()
        return size if size.width() > 0 and size.height() > 0 else DEFAULT_FRAME

    def _fit_frame(self) -> None:
        frame = self._frame_size()
        self._video.setSize(frame)
        self._scene.setSceneRect(QRectF(0, 0, frame.width(), frame.height()))
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._layout_caption()

    def _layout_caption(self) -> None:
        frame = self._frame_size()
        font = QFont()
        font.setPixelSize(max(int(frame.height() * CAPTION_FONT_RATIO), 12))
        font.setBold(True)
        self._caption.setFont(font)
        self._caption.setTextWidth(frame.width() * CAPTION_WIDTH_RATIO)
        document = self._caption.document()
        document.setDefaultStyleSheet("")
        option = document.defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        document.setDefaultTextOption(option)
        box = self._caption.boundingRect()
        x = (frame.width() - box.width()) / 2
        y = frame.height() * (1 - CAPTION_MARGIN_RATIO) - box.height()
        self._caption.setPos(x, y)
        visible = bool(self._caption.toPlainText())
        self._caption_background.setVisible(visible)
        if visible:
            ideal = self._caption.document().idealWidth()
            padding = font.pixelSize() * 0.3
            left = (frame.width() - ideal) / 2 - padding
            self._caption_background.setRect(QRectF(left, y, ideal + padding * 2, box.height()))
