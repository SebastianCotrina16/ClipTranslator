from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.config.store import SettingsStore
from app.domain.subtitle_style import (
    Background,
    Position,
    SubtitleStyle,
    ass_color,
    force_style,
)
from app.infrastructure.ffmpeg import ffmpeg_executable, render_preview
from app.presentation.gui.video_style_dialog import VideoStyleDialog


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def style_fields(style: SubtitleStyle) -> dict[str, str]:
    return dict(item.split("=", 1) for item in force_style(style).split(","))


def test_colors_are_converted_to_ass_order_with_transparency() -> None:
    assert ass_color("#FFE14D") == "&H004DE1FF"
    assert ass_color("#000000", 60) == "&H66000000"
    assert ass_color("#000000", 0) == "&HFF000000"


def test_box_style_draws_a_semi_transparent_box() -> None:
    fields = style_fields(SubtitleStyle(text_color="#FFE14D", box_opacity=50))
    assert fields["BorderStyle"] == "3"
    assert fields["PrimaryColour"] == "&H004DE1FF"
    assert fields["OutlineColour"] == fields["BackColour"] == "&H80000000"


def test_outline_style_and_top_position() -> None:
    fields = style_fields(
        SubtitleStyle(background=Background.OUTLINE, position=Position.TOP, font_size=28)
    )
    assert fields["BorderStyle"] == "1"
    assert fields["OutlineColour"] == "&H00000000"
    assert fields["Alignment"] == "6"
    assert fields["FontSize"] == "28"


def test_invalid_values_fall_back_to_safe_defaults() -> None:
    style = SubtitleStyle.from_values("red',x=1", "neon", 250, 500, "middle")
    assert style == SubtitleStyle(box_opacity=100, font_size=48)


def test_store_keeps_a_valid_video_style(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.toml")
    settings = store.load()
    settings.video.remember(SubtitleStyle(text_color="#ffe14d", position=Position.TOP))
    store.save(settings)
    style = store.load().video.style()
    assert style.text_color == "#FFE14D"
    assert style.position is Position.TOP


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    video = tmp_path / "it's a clip.mp4"
    subprocess.run(
        [
            ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=2",
            str(video),
        ],
        check=True,
    )
    return video


def test_preview_renders_a_frame(sample_video: Path, tmp_path: Path) -> None:
    output = render_preview(
        sample_video, 1.0, "Hello there", SubtitleStyle(), tmp_path / "preview.png"
    )
    assert output.stat().st_size > 0


@pytest.mark.parametrize(
    "chosen",
    [
        SubtitleStyle(text_color="#FFE14D", box_opacity=35, position=Position.TOP),
        SubtitleStyle(text_color="#123456", background=Background.OUTLINE, font_size=30),
    ],
)
def test_style_dialog_returns_the_chosen_style(
    qt_app: QApplication, sample_video: Path, chosen: SubtitleStyle
) -> None:
    dialog = VideoStyleDialog(sample_video, 1.0, "", chosen)
    assert dialog.style() == chosen
    dialog.reject()
