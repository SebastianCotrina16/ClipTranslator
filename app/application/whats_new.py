from __future__ import annotations

import re
from dataclasses import dataclass

from app.application.updates import version_key

_HEADING = re.compile(r"^##\s+(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ReleaseNotes:
    version: str
    text: str


def parse_notes(markdown: str) -> list[ReleaseNotes]:
    headings = list(_HEADING.finditer(markdown))
    notes: list[ReleaseNotes] = []
    for position, heading in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(markdown)
        body = markdown[heading.end() : end].strip()
        if version_key(heading.group(1)) is not None and body:
            notes.append(ReleaseNotes(heading.group(1), body))
    return notes


def unseen_notes(notes: list[ReleaseNotes], last_seen: str, current: str) -> list[ReleaseNotes]:
    current_key = version_key(current)
    if current_key is None:
        return []
    seen_key = version_key(last_seen)
    return [
        note
        for note in notes
        if (key := version_key(note.version)) is not None
        and key <= current_key
        and (key == current_key if seen_key is None else key > seen_key)
    ]


def as_markdown(notes: list[ReleaseNotes]) -> str:
    return "\n\n".join(f"### Version {note.version}\n\n{note.text}" for note in notes)
