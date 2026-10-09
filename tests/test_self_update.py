from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from app.application.updates import Installer, Release
from app.config.session import SavedClip, Session, SessionStore
from app.config.store import SettingsStore
from app.domain.models import Cue
from app.infrastructure.github_releases import DOWNLOADS, installed_version, installer_from
from app.infrastructure.self_update import UpdateError, download_installer
from app.presentation.gui.clip_queue import ClipStatus
from app.presentation.gui.cue_table import Column
from app.presentation.gui.main_window import MainWindow, restored_status

PAYLOAD = b"installer bytes" * 1000
NAME = "ClipTranslator-Setup-1.2.0.exe"


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def asset(**changes: object) -> dict:
    data = {
        "name": NAME,
        "browser_download_url": f"{DOWNLOADS}v1.2.0/{NAME}",
        "size": len(PAYLOAD),
        "digest": f"sha256:{hashlib.sha256(PAYLOAD).hexdigest()}",
    }
    return data | changes


def installer(**changes: object) -> Installer:
    result = installer_from([asset(**changes)])
    assert result is not None
    return result


def test_installer_needs_a_project_link_and_checksum() -> None:
    assert installer().sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert installer_from([asset(browser_download_url="https://evil.example/x.exe")]) is None
    assert installer_from([asset(digest=None)]) is None
    assert installer_from([asset(name="notes.txt")]) is None
    assert installer_from("nonsense") is None


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch):
    def serve(payload: bytes) -> None:
        class Response:
            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self, size: int):
                for start in range(0, len(payload), size):
                    yield payload[start : start + size]

        @contextmanager
        def stream(*args: object, **kwargs: object):
            yield Response()

        monkeypatch.setattr("httpx.stream", stream)

    return serve


def test_download_is_verified_before_use(served, tmp_path: Path) -> None:
    served(PAYLOAD)
    seen: list[float] = []
    path = download_installer(installer(), tmp_path / "update", seen.append)
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == 1.0


@pytest.mark.parametrize("payload", [PAYLOAD[:-1] + b"X", PAYLOAD + b"extra", PAYLOAD[:10]])
def test_damaged_downloads_are_rejected(served, tmp_path: Path, payload: bytes) -> None:
    served(payload)
    with pytest.raises(UpdateError):
        download_installer(installer(), tmp_path / "update")
    assert not (tmp_path / "update" / NAME).exists()


def test_session_is_read_once_and_survives_bad_data(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "session.json")
    session = Session([SavedClip("C:/clips/a.mp4", "Exported")], "C:/clips/a.mp4", "pt", "ctx")
    store.save(session)
    assert store.take() == session
    assert store.take() is None
    store.path.write_text("{broken", encoding="utf-8")
    assert store.take() is None
    assert not store.path.exists()


def test_clips_being_processed_are_restored_as_pending() -> None:
    assert restored_status("Processing…") is ClipStatus.PENDING
    assert restored_status("Exported") is ClipStatus.EXPORTED
    assert restored_status("unknown") is ClipStatus.PENDING


def window_with(tmp_path: Path, session: Session | None = None) -> MainWindow:
    settings = SettingsStore(tmp_path / "config.toml")
    settings.save(settings.load())
    sessions = SessionStore(tmp_path / "session.json")
    if session is not None:
        sessions.save(session)
    return MainWindow(settings, session_store=sessions)


def test_clips_come_back_after_an_update(qt_app: QApplication, tmp_path: Path) -> None:
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    for clip in (first, second):
        clip.write_bytes(b"")
    session = Session(
        [SavedClip(str(first), "Pending"), SavedClip(str(second), "Processing…")],
        str(first),
        "pt",
        "two friends drawing",
    )
    window = window_with(tmp_path, session)
    assert window._clips.paths() == [first.resolve(), second.resolve()]
    assert window._clips.status(second.resolve()) is ClipStatus.PENDING
    assert window._context.text() == "two friends drawing"
    assert window._source.currentData() == "pt"
    assert window._current_session().current == str(first.resolve())
    window.close()


def test_update_waits_while_clips_are_processing(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with(tmp_path)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args[2]))
    window._release = Release("v1.2.0", DOWNLOADS, installer=installer())
    window._queue_active = True
    window._install_update()
    assert shown and not window._update_runner.busy and not window._updating
    window._queue_active = False
    window.close()


def test_open_edit_is_kept_before_closing(qt_app: QApplication, tmp_path: Path) -> None:
    window = window_with(tmp_path)
    window._model.set_cues([Cue(1, 1.0, 2.0, "hola", "hello", 0)])
    window.show()
    window.activateWindow()
    index = window._model.index(0, Column.TRANSLATION)
    window._table.setCurrentIndex(index)
    window._table.edit(index)
    qt_app.processEvents()
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.setText("hello there")
    window._finish_editing()
    assert window._model.cue_at(0).translation == "hello there"
    window.close()


def test_the_installed_version_is_shown(qt_app: QApplication, tmp_path: Path) -> None:
    window = window_with(tmp_path)
    version = installed_version()
    assert window._version.text() == f"Version {version}"
    assert window.windowTitle() == f"ClipTranslator {version}"
