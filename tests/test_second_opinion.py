from __future__ import annotations

import json
import os
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from app.application.translation import (
    Request,
    Task,
    TranslationService,
    fill_versions,
    translate_versions,
)
from app.domain.coverage import Region
from app.domain.models import (
    Cue,
    Flag,
    Reading,
    cues_from_records,
    segments_from_records,
    to_records,
)
from app.domain.quality import HallucinationDetector
from app.domain.second_opinion import doubtful_regions, settle
from app.domain.segmentation import SegmentationRules, UnitBuilder
from app.domain.subtitles import CueBuilder
from app.presentation.gui.cue_table import Column, CueTableModel
from app.presentation.gui.versions_dialog import VersionsDialog
from tests.builders import make_segment, make_unit

DETECTOR = HallucinationDetector()
SOURCES = ("large-v3", "large-v2")
START = Region(0.0, 5.3)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_made_up_lines_and_barely_heard_parts_are_doubtful() -> None:
    made_up = make_segment("Sous-titres par Jérémy Diaz", start=0.5, step=0.8)
    fine = make_segment("Gevo dénonce toi", start=10.5)
    quiet = Region(20.0, 23.0)
    regions = [START, Region(10.0, 12.0), quiet]
    assert doubtful_regions(regions, [made_up, fine], [], DETECTOR) == [START]
    assert doubtful_regions(regions, [made_up, fine], [quiet], DETECTOR) == [START, quiet]


def test_second_model_replaces_a_made_up_line() -> None:
    made_up = make_segment("Sous-titres par Jérémy Diaz", start=0.5, step=0.8)
    later = make_segment("Gevo dénonce toi", start=10.5, segment_id=1)
    heard = [make_segment("Ah merde !", start=0.8), make_segment("Un zombie ?", start=1.8)]
    result = settle([made_up, later], heard, [START], SOURCES, DETECTOR)
    assert [segment.text for segment in result] == ["Ah merde ! Un zombie ?", "Gevo dénonce toi"]
    assert result[0].flags == [Flag.SECOND_MODEL]
    assert result[0].versions == []


def test_disagreement_keeps_both_versions() -> None:
    primary = make_segment("Non mais on croit", start=0.5)
    heard = [make_segment("Non mais on voit rien", start=0.5)]
    [line] = settle([primary], heard, [START], SOURCES, DETECTOR)
    assert line.text == "Non mais on croit"
    assert line.flags == [Flag.MODELS_DISAGREE]
    assert [(version.source, version.text) for version in line.versions] == [
        ("large-v3", "Non mais on croit"),
        ("large-v2", "Non mais on voit rien"),
    ]


@pytest.mark.parametrize(
    "heard",
    [
        [],
        [make_segment("non, mais on croit", start=0.5)],
        [make_segment("Merci d'avoir regardé", start=0.5)],
    ],
)
def test_nothing_changes_without_a_useful_second_opinion(heard: list) -> None:
    primary = make_segment("Non, mais on croit !", start=0.5)
    [line] = settle([primary], heard, [START], SOURCES, DETECTOR)
    assert line.text == "Non, mais on croit !"
    assert line.flags == []


def test_review_flags_and_versions_survive_the_rest_of_the_pipeline() -> None:
    primary = make_segment("Non mais on croit. Lui aussi.", start=0.5)
    [line] = settle(
        [primary], [make_segment("Non mais on voit rien", start=0.5)], [START], SOURCES, DETECTOR
    )
    [restored] = DETECTOR.flag(segments_from_records(to_records([line])))
    assert Flag.MODELS_DISAGREE in restored.flags
    [unit] = UnitBuilder(SegmentationRules(max_duration=0.5)).build([restored])
    assert unit.text == "Non mais on croit. Lui aussi."
    assert len(unit.versions) == 2
    unit.translation = "No but we believe. Him too."
    [cue] = CueBuilder().build([unit])
    assert cue.translation == "No but we believe. Him too."
    assert cues_from_records(to_records([cue]))[0].versions == cue.versions


class EchoModel:
    description = "echo"

    def prepare(self, progress: Any = None) -> list[str]:
        return []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = user.split("Segments to translate:\n", 1)[1].split("\n\n", 1)[0]
        [item] = json.loads(payload)["segments"]
        return {"translations": [{"id": item["id"], "text": f"EN {item['text']}"}]}

    def unload(self) -> None:
        return None


def test_every_version_is_translated() -> None:
    before = make_unit("Gevo", "Gevo", unit_id=0)
    doubtful = make_unit("on croit", "we believe", unit_id=1)
    doubtful.versions = [Reading("large-v3", "on croit"), Reading("large-v2", "on voit rien")]
    found = translate_versions(
        TranslationService(EchoModel()),
        [before, doubtful],
        {0: "Gevo", 1: "we believe"},
        Request(Task.TRANSLATE, "fr", "en"),
        "prompt",
    )
    assert found == {1: [None, "EN on voit rien"]}
    fill_versions(doubtful, found[1])
    assert [version.translation for version in doubtful.versions] == [
        "we believe",
        "EN on voit rien",
    ]


def versioned_cue() -> Cue:
    return Cue(
        1,
        0.5,
        2.0,
        "on croit",
        "we believe",
        0,
        [Flag.MODELS_DISAGREE],
        [
            Reading("large-v3", "on croit", "we believe"),
            Reading("large-v2", "on voit rien", "we see nothing"),
        ],
    )


def test_choosing_a_version_can_be_undone(qt_app: QApplication) -> None:
    model = CueTableModel()
    cue = versioned_cue()
    model.set_cues([cue])
    model.use_version(0, cue.versions[1])
    assert (cue.original, cue.translation) == ("on voit rien", "we see nothing")
    assert model.data(model.index(0, Column.TRANSLATION)) == "we see nothing"
    model.undo_stack.undo()
    assert (cue.original, cue.translation) == ("on croit", "we believe")


def test_versions_dialog_starts_on_the_current_version(qt_app: QApplication) -> None:
    cue = versioned_cue()
    cue.original = "on voit rien"
    dialog = VersionsDialog(cue)
    assert dialog.chosen().source == "large-v2"
    dialog.reject()
