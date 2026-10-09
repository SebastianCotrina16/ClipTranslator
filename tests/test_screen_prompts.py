from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.application.pipeline import Pipeline, PipelineServices, Stage
from app.application.screen_prompts import spoken_around, translate_prompts
from app.config.settings import Settings
from app.config.store import SettingsStore
from app.domain.models import Cue
from app.domain.names import NameFixer, known_names
from app.domain.screen_prompts import (
    Detection,
    PromptScan,
    PromptStyle,
    canonical_keys,
    group_lines,
    is_album_title,
    is_button,
    is_players_title,
    prompt_key,
)
from app.domain.subtitle_style import SubtitleStyle
from app.infrastructure.prompt_renderer import PromptRenderer, nunito
from app.infrastructure.subtitle_files import video_name
from app.presentation.gui.video_style_dialog import VideoStyleDialog

PURPLE = (150, 60, 90)
CARD = (250, 250, 250)
INK = (60, 60, 60)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    "title",
    ["LAZYYBXNES'S ALBUM", "ÁLBUM DE ARMAJUNIOR", "ALBUM VON MIDNIGHTKISS", "AЛЬБOM VORCHYNDED"],
)
def test_album_titles_in_every_language_are_found(title: str) -> None:
    assert is_album_title(title)


def test_titles_buttons_and_names_are_told_apart() -> None:
    assert is_players_title("JUGADORES") and is_players_title("ИГРОКИ")
    assert is_button("SEGUIR") and is_button("ДАЛЬШ") and is_button("Zurück")
    assert not is_button("Grabstein vorm Baum")
    assert not is_album_title("Harry potter")


def test_partial_and_misread_prompts_join_the_full_one() -> None:
    keys = ["hollow knight", "llow knight", "harry potter", "harry potter y la piedra filosofal"]
    mapping = canonical_keys(keys + ["silent hilì", "silent hill"])
    assert mapping["llow knight"] == "hollow knight"
    assert mapping["silent hilì"] == "silent hill"
    assert mapping["harry potter"] == "harry potter"


def test_only_lines_inside_the_same_card_are_grouped() -> None:
    name = (888.0, 693.0, 951.0, 717.0)
    first = (661.0, 744.0, 910.0, 777.0)
    second = (700.0, 776.0, 880.0, 806.0)
    in_card = {first, second}
    groups = group_lines([name, first, second], lambda box: box in in_card)
    assert groups == [[name], [first, second]]


def album_frame(text: str, top: int = 300) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    image = Image.new("RGB", (1280, 720), PURPLE)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([900, top, 1180, top + 70], radius=9, fill=CARD)
    font = nunito(30)
    left, upper, right, lower = draw.textbbox((920, top + 35), text, font=font, anchor="lm")
    draw.text((920, top + 35), text, font=font, fill=INK, anchor="lm")
    frame = np.array(image)[:, :, ::-1].copy()
    return frame, (int(left), int(upper), int(right), int(lower))


def renderer_for(text: str, translation: str, style: PromptStyle) -> PromptRenderer:
    frame, box = album_frame(text)
    template = frame[box[1] : box[3], box[0] : box[2]].mean(axis=2).astype(np.float32)
    detection = Detection(0, box, text)
    return PromptRenderer([detection], [template], {prompt_key(text): translation}, 30.0, style)


def test_the_translation_replaces_the_prompt_and_follows_the_scroll() -> None:
    renderer = renderer_for("Lisa", "Fox", PromptStyle.FIT)
    for frame_number, top in ((0, 300), (1, 312), (2, 330)):
        frame, box = album_frame("Lisa", top)
        before = frame.copy()
        [placed] = renderer.apply(frame_number, frame)
        assert placed.text == "Fox"
        assert placed.box[1] == box[1]
        assert np.abs(frame.astype(int) - before.astype(int)).max() > 100
        assert tuple(frame[top + 5, 905][::-1]) == CARD


def test_a_wider_box_keeps_the_text_size() -> None:
    long = "A zombie hand coming out of the ground"
    frame, box = album_frame("Zombie")
    renderer_for("Zombie", long, PromptStyle.WIDEN).apply(0, frame)
    assert tuple(frame[305, 860][::-1]) == CARD
    fitted, _ = album_frame("Zombie")
    renderer_for("Zombie", long, PromptStyle.FIT).apply(0, fitted)
    assert tuple(fitted[305, 860][::-1]) == PURPLE


def test_nothing_is_drawn_where_the_prompt_is_gone() -> None:
    renderer = renderer_for("Lisa", "Fox", PromptStyle.FIT)
    empty = np.full((720, 1280, 3), PURPLE[::-1], np.uint8)
    assert renderer.apply(5, empty) == []
    assert (empty == np.array(PURPLE[::-1], np.uint8)).all()


class PromptModel:
    description = "prompts"

    def __init__(self) -> None:
        self.request = ""

    def prepare(self, progress: Any = None) -> list[str]:
        return []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.request = user
        items = json.loads(user.split("Prompts:\n", 1)[1].split("\n\n", 1)[0])["prompts"]
        answers = {"Hollow knight": "Hollow knight", "лиса толстая": "Fat fox", "Геворг": "Guevo"}
        return {"translations": [{"id": i["id"], "text": answers[i["text"]]} for i in items]}

    def unload(self) -> None:
        return None


def test_prompts_are_translated_with_what_was_said_around_them() -> None:
    detections = [
        Detection(0, (0, 0, 10, 10), "лиса толстая"),
        Detection(30, (0, 0, 10, 10), "Hollow knight"),
        Detection(60, (0, 0, 10, 10), "llow knight"),
        Detection(90, (0, 0, 10, 10), "Геворг"),
    ]
    cues = [Cue(1, 0.0, 1.5, "смотри, толстая лиса", "look, a fat fox", 0)]
    model = PromptModel()
    found = translate_prompts(
        model, detections, 30.0, cues, "en", "system", NameFixer(known_names(""))
    )
    assert found == {"лиса толстая": "Fat fox", "геворг": "Gevo"}
    assert "смотри, толстая лиса" in model.request
    assert '"text": "llow knight"' not in model.request
    assert model.request.endswith("exactly these ids: 0, 1, 2.")


def test_speech_is_taken_from_around_the_moment() -> None:
    cues = [Cue(1, 0.0, 1.0, "early", "", 0), Cue(2, 20.0, 21.0, "late", "", 1)]
    assert spoken_around(cues, 2.0) == "early"


class FakeReader:
    def __init__(self) -> None:
        self.scans = 0

    @property
    def cache_identity(self) -> dict[str, Any]:
        return {"fake": 1}

    def prepare(self, progress: Any = None) -> None:
        return None

    def scan(self, media: Path, progress: Any = None) -> PromptScan:
        self.scans += 1
        return PromptScan(64, 36, 30.0, [Detection(0, (1, 2, 3, 4), "Лиса")], [np.zeros((2, 2))])

    def store(self, scan: PromptScan, path: Path) -> dict[str, Any]:
        path.write_bytes(b"templates")
        return {"templates": path.name, "texts": [d.text for d in scan.detections]}

    def load(self, data: dict[str, Any], folder: Path) -> PromptScan:
        detections = [Detection(0, (1, 2, 3, 4), text) for text in data["texts"]]
        return PromptScan(64, 36, 30.0, detections, [np.zeros((2, 2))])


def test_reading_the_prompts_is_cached_per_clip(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    reader = FakeReader()
    services = PipelineServices(
        audio=None,
        speech_detector=None,
        subtitle_writer=None,
        create_transcriber=lambda: None,
        create_language_model=lambda: None,
        create_separator=lambda: None,
        create_prompt_reader=lambda: reader,
    )
    for _ in range(2):
        pipeline = Pipeline(media, Settings(), services, tmp_path / "work")
        scan = pipeline.read_screen_prompts()
    assert [d.text for d in scan.detections] == ["Лиса"]
    assert reader.scans == 1
    assert pipeline.state.records[-1].stage == Stage.SCREEN_SCAN


def test_prompt_choice_is_remembered_and_named(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.toml")
    settings = store.load()
    assert settings.video.prompts() is PromptStyle.WIDEN
    settings.video.prompt_style = "fit"
    store.save(settings)
    assert store.load().video.prompts() is PromptStyle.FIT
    assert (
        video_name(Path("clip.mkv"), True, True, False, True)
        == "clip.subtitled.prompts.no-music.mp4"
    )


def test_export_can_only_translate_the_prompts(qt_app: QApplication, tmp_path: Path) -> None:
    clip = tmp_path / "clip.png"
    Image.new("RGB", (64, 36), PURPLE).save(clip)
    dialog = VideoStyleDialog(
        clip, 0.0, "", SubtitleStyle(), None, False, False, False, None, None, True, PromptStyle.FIT
    )
    export = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert export.isEnabled()
    assert (dialog.translate_prompts(), dialog.prompt_style()) == (True, PromptStyle.FIT)
    dialog._widen.setChecked(True)
    assert dialog.prompt_style() is PromptStyle.WIDEN
    dialog._prompts.setChecked(False)
    assert not export.isEnabled()
    assert not dialog._prompt_box.isEnabled()
    dialog.reject()
