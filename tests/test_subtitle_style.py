from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.config.store import SettingsStore
from app.domain.subtitle_style import (
    Background,
    Position,
    SubtitleStyle,
    ass_color,
    force_style,
)
from app.infrastructure.ffmpeg import ffmpeg_executable, render_preview, render_video
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


def make_media(target: Path, *sources: str) -> Path:
    inputs = [part for source in sources for part in ("-f", "lavfi", "-i", source)]
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", *inputs, "-t", "2"]
    subprocess.run([*command, str(target)], check=True)
    return target


def streams(media: Path) -> str:
    probe = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-i", str(media)], capture_output=True, text=True
    )
    return probe.stderr


def test_video_can_get_voice_only_audio_without_subtitles(tmp_path: Path) -> None:
    clip = make_media(tmp_path / "clip.mp4", "color=c=blue:s=320x180:d=2", "sine=f=440:d=2")
    voices = make_media(tmp_path / "voices.wav", "sine=f=220:d=2")
    output = render_video(clip, tmp_path / "clip.no-music.mp4", audio=voices)
    found = streams(output)
    assert "Video: h264" in found
    assert "Audio: aac" in found


def test_video_with_subtitles_and_voice_only_audio(tmp_path: Path) -> None:
    clip = make_media(tmp_path / "clip.mp4", "color=c=blue:s=320x180:d=2", "sine=f=440:d=2")
    voices = make_media(tmp_path / "voices.wav", "sine=f=220:d=2")
    subtitles = tmp_path / "clip.en.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    output = render_video(clip, tmp_path / "out.mp4", subtitles, SubtitleStyle(), voices)
    assert "Audio: aac" in streams(output)


def test_preview_without_subtitles(sample_video: Path, tmp_path: Path) -> None:
    output = render_preview(sample_video, 1.0, "", None, tmp_path / "plain.png")
    assert output.stat().st_size > 0


def test_export_needs_subtitles_or_music_removal(qt_app: QApplication, sample_video: Path) -> None:
    dialog = VideoStyleDialog(sample_video, 1.0, "", SubtitleStyle(), None, True, True)
    export = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    dialog._subtitles.setChecked(False)
    assert export.isEnabled()
    assert (dialog.burn_subtitles(), dialog.remove_music()) == (False, True)
    dialog._no_music.setChecked(False)
    assert not export.isEnabled()
    dialog._subtitles.setChecked(True)
    assert export.isEnabled()
    dialog.reject()
