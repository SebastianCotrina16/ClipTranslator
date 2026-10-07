from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.domain.models import Cue
from app.infrastructure import diagnostics


@pytest.fixture
def work_root(tmp_path: Path) -> Path:
    home = Path.home()
    for name, time, seconds in (
        ("clip_b", "2026-10-07 10:00:00", 30.0),
        ("clip_a", "2026-10-06 09:00:00", 20.0),
    ):
        folder = tmp_path / "work" / name
        folder.mkdir(parents=True)
        entry = {
            "time": time,
            "media": str(home / "Videos" / f"{name}.mp4"),
            "duration": 24.0,
            "total_seconds": seconds,
            "language": "fr",
            "stages": [
                {"stage": "separation", "seconds": 3.1, "cached": False, "detail": ""},
                {
                    "stage": "transcribe",
                    "seconds": 9.2,
                    "cached": False,
                    "detail": '{"first_pass_seconds": 6.0, "second_model_seconds": 2.5}',
                },
            ],
            "warnings": [],
        }
        (folder / "run.log").write_text(json.dumps(entry) + "\nnot json\n", encoding="utf-8")
    return tmp_path / "work"


def test_home_folder_and_user_name_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERNAME", "artiom")
    home = Path.home()
    text = f"{home}\\clip.mp4 | {home.as_posix()}/x | {json.dumps(str(home))} | Artiom ran it"
    cleaned = diagnostics.anonymized(text)
    assert str(home) not in cleaned
    assert home.as_posix() not in cleaned
    assert "rtiom" not in cleaned
    assert cleaned.count("~") == 3


def test_recent_runs_are_sorted_and_described(work_root: Path) -> None:
    runs = diagnostics.recent_runs(work_root)
    assert [Path(run["media"]).name for run in runs] == ["clip_a.mp4", "clip_b.mp4"]
    described = diagnostics.describe_run(runs[0])
    assert "clip_a.mp4  clip 24s, work 20s, language fr" in described
    assert "transcribe 9.2s" in described
    assert "second_model_seconds" in described


def test_report_has_the_useful_parts_and_no_secrets(
    work_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "system_summary", lambda settings: "GPU: GTX 1660")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cliptranslator.log").write_text(f"error in {Path.home()}\\x", encoding="utf-8")
    settings = Settings()
    settings.translation.anthropic_api_key = "sk-secret-value"
    cue = Cue(1, 0.5, 2.0, "Gevo dessine", "Gevo draws", 0)
    target = diagnostics.create_report(tmp_path / "report.zip", settings, logs, work_root, [cue])
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        everything = "".join(archive.read(name).decode("utf-8") for name in names)
        summary = archive.read("summary.txt").decode("utf-8")
    assert {"summary.txt", "settings.json", "runs.jsonl", "logs/cliptranslator.log"} <= names
    assert "subtitles.txt" in names
    assert "GPU: GTX 1660" in summary
    assert "clip_b.mp4" in summary
    assert "sk-secret-value" not in everything
    assert str(Path.home()) not in everything


def test_report_without_subtitles_or_logs(
    work_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "system_summary", lambda settings: "")
    target = diagnostics.create_report(tmp_path / "r.zip", Settings(), None, tmp_path / "missing")
    with zipfile.ZipFile(target) as archive:
        assert "subtitles.txt" not in archive.namelist()
        assert "none yet" in archive.read("summary.txt").decode("utf-8")
