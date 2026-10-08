from __future__ import annotations

import pytest

from app.application.translation import Request, Task, build_user_message
from app.domain.models import Reading
from app.domain.names import NameFixer, known_names, prefer_named_versions, spell_names
from tests.builders import make_unit

FIXER = NameFixer(known_names("Kiki, Régis"))


def test_gevo_is_always_known_and_names_are_not_repeated() -> None:
    assert known_names("") == ("Gevo",)
    assert known_names("kiki; Gevo,\n Régis , ") == ("Gevo", "kiki", "Régis")


@pytest.mark.parametrize(
    ("heard", "fixed"),
    [
        ("Il y a G'Evo qui fait des poissons", "Il y a Gevo qui fait des poissons"),
        ("Gévo dénonce toi", "Gevo dénonce toi"),
        ("Guevo !", "Gevo !"),
        ("Jevo, regarde", "Gevo, regarde"),
        ("Djévo et Gévaux", "Gevo et Gevo"),
        ("G Evo est là", "Gevo est là"),
        ("Kevo did it", "Gevo did it"),
        ("That's gevo's drawing", "That's Gevo's drawing"),
        ("Kika ! Regis ?", "Kiki ! Régis ?"),
        ("¿Quién es Geo? Es de gebo", "¿Quién es Gevo? Es de Gevo"),
        ("¿Quién es Heo? Hevo, Jeo", "¿Quién es Gevo? Gevo, Gevo"),
    ],
)
def test_misheard_names_are_spelled_right(heard: str, fixed: str) -> None:
    assert FIXER.fix(heard) == fixed


@pytest.mark.parametrize(
    "text",
    [
        "je vois",
        "Je veux",
        "Give it",
        "Evo",
        "J'ai vu Gevo",
        "Chevaux et cheveux",
        "kevo in lowercase is left alone",
    ],
)
def test_ordinary_words_are_left_alone(text: str) -> None:
    assert FIXER.fix(text) == text


def test_names_are_fixed_in_text_translation_and_versions() -> None:
    unit = make_unit("Gévo dessine", "Gévo draws")
    unit.versions = [Reading("large-v3", "Gévo dessine", "Guevo draws")]
    [fixed] = spell_names([unit], FIXER)
    assert (fixed.text, fixed.translation) == ("Gevo dessine", "Gevo draws")
    assert (fixed.versions[0].text, fixed.versions[0].translation) == (
        "Gevo dessine",
        "Gevo draws",
    )


def test_the_translator_is_told_the_names() -> None:
    request = Request(Task.TRANSLATE, "fr", "en", names=("Gevo", "Kiki"))
    message = build_user_message([{"id": 1, "text": "Gevo"}], request)
    assert "never translate them: Gevo, Kiki." in message


def test_the_version_that_names_someone_is_preferred() -> None:
    unit = make_unit("Chicos, ¿qué deseo?", "Guys, what do I want?")
    unit.versions = [
        Reading("large-v3", "Chicos, ¿qué deseo?", "Guys, what do I want?"),
        Reading("large-v2", "Chicos, ¿quién es Heo?", "Guys, who is Heo?"),
    ]
    [chosen] = prefer_named_versions(spell_names([unit], FIXER), FIXER)
    assert (chosen.text, chosen.translation) == ("Chicos, ¿quién es Gevo?", "Guys, who is Gevo?")


def test_versions_are_kept_when_names_do_not_decide() -> None:
    both = make_unit("Gevo dibuja", "Gevo draws")
    both.versions = [Reading("a", "Gevo dibuja", "Gevo draws"), Reading("b", "Gevo dibujó")]
    neither = make_unit("hola white", "hello white")
    neither.versions = [Reading("a", "hola white"), Reading("b", "hola guay")]
    prefer_named_versions([both, neither], FIXER)
    assert (both.text, neither.text) == ("Gevo dibuja", "hola white")
