from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.domain.models import Cue
from app.infrastructure.github_releases import RELEASES_PAGE, GitHubReleases
from app.presentation.gui.clip_queue import ClipList, ClipStatus, media_files_in
from app.presentation.gui.cue_table import Column, CueTableModel


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def cues() -> list[Cue]:
    return [
        Cue(1, 1.0, 2.0, "hi", "hola", 0),
        Cue(2, 3.0, 4.0, "bye", "chau", 1),
    ]


def model_with(qt_app: QApplication) -> tuple[CueTableModel, list[Cue]]:
    model = CueTableModel()
    items = cues()
    model.set_cues(items)
    return model, items


def test_text_edit_can_be_undone_and_redone(qt_app: QApplication) -> None:
    model, items = model_with(qt_app)
    assert model.setData(model.index(0, Column.TRANSLATION), "hola editado")
    assert items[0].translation == "hola editado"
    model.undo_stack.undo()
    assert items[0].translation == "hola"
    model.undo_stack.redo()
    assert items[0].translation == "hola editado"


def test_time_edit_is_parsed_and_validated(qt_app: QApplication) -> None:
    model, items = model_with(qt_app)
    rejected: list[str] = []
    model.edit_rejected.connect(rejected.append)
    assert model.setData(model.index(0, Column.START), "0:00.50")
    assert items[0].start == 0.5
    assert not model.setData(model.index(0, Column.END), "0:00.20")
    assert not model.setData(model.index(0, Column.START), "later")
    assert len(rejected) == 2
    assert items[0].end == 2.0


def test_shift_rows_is_one_undo_step(qt_app: QApplication) -> None:
    model, items = model_with(qt_app)
    model.shift_rows([0, 1], 0.5)
    assert [(c.start, c.end) for c in items] == [(1.5, 2.5), (3.5, 4.5)]
    model.undo_stack.undo()
    assert [(c.start, c.end) for c in items] == [(1.0, 2.0), (3.0, 4.0)]
    assert not model.undo_stack.canUndo()


def test_edits_emit_saved_signal(qt_app: QApplication) -> None:
    model, _ = model_with(qt_app)
    edited: list[bool] = []
    model.edited.connect(lambda: edited.append(True))
    model.setData(model.index(1, Column.ORIGINAL), "goodbye")
    model.undo_stack.undo()
    assert len(edited) == 2


def test_media_files_in_folder_filters_and_deduplicates(tmp_path: Path) -> None:
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "a.MKV").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    found = media_files_in([tmp_path, tmp_path / "b.mp4"])
    assert [path.name for path in found] == ["a.MKV", "b.mp4"]


def test_clip_list_tracks_status(qt_app: QApplication, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    clips = ClipList()
    assert clips.add([video]) == [video.resolve()]
    assert clips.add([video]) == []
    assert clips.status(video.resolve()) is ClipStatus.PENDING
    clips.set_status(video.resolve(), ClipStatus.EXPORTED)
    assert clips.with_status(ClipStatus.EXPORTED) == [video.resolve()]


def test_update_links_outside_the_project_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, url: str) -> None:
            self._url = url

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"tag_name": "v9.0.0", "html_url": self._url, "body": "notes"}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Response("https://evil.example/x"))
    assert GitHubReleases().latest() is None
    monkeypatch.setattr("httpx.get", lambda *a, **k: Response(f"{RELEASES_PAGE}tag/v9.0.0"))
    release = GitHubReleases().latest()
    assert release is not None and release.version == "v9.0.0"
