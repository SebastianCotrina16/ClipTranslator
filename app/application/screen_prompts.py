from __future__ import annotations

import json
from collections.abc import Iterable

from app.application.ports import LanguageModel
from app.application.translation import RESPONSE_SCHEMAS, Task, validate_response
from app.domain.languages import english_name
from app.domain.models import Cue
from app.domain.names import NameFixer
from app.domain.screen_prompts import Detection, canonical_keys, prompt_key

SPEECH_BEFORE = 4.0
SPEECH_AFTER = 6.0


def spoken_around(cues: Iterable[Cue], seconds: float) -> str:
    near = [
        cue.original
        for cue in cues
        if cue.end >= seconds - SPEECH_BEFORE and cue.start <= seconds + SPEECH_AFTER
    ]
    return " ".join(near)


def unique_prompts(detections: Iterable[Detection], fps: float) -> dict[str, tuple[str, float]]:
    first: dict[str, tuple[str, float]] = {}
    for detection in sorted(detections, key=lambda found: found.frame):
        first.setdefault(
            prompt_key(detection.text), (detection.text, detection.frame / max(fps, 1.0))
        )
    return first


def build_request(prompts: list[tuple[str, str]], target_language: str) -> str:
    items = [
        {"id": number, "text": text, "said_around_it": speech}
        for number, (text, speech) in enumerate(prompts)
    ]
    target = english_name(target_language)
    ids = ", ".join(str(item["id"]) for item in items)
    return "\n\n".join(
        [
            f"Translate these Gartic Phone prompts into {target}.",
            '"said_around_it" is what the players said while the prompt was on screen. Use it '
            "only to understand ambiguous words; do NOT translate it.",
            "Prompts:\n" + json.dumps({"prompts": items}, ensure_ascii=False),
            f'Answer with {{"translations": [{{"id": ..., "text": ...}}]}} in {target}, with '
            f"exactly these ids: {ids}.",
        ]
    )


def translate_prompts(
    model: LanguageModel,
    detections: list[Detection],
    fps: float,
    cues: list[Cue],
    target_language: str,
    system_prompt: str,
    names: NameFixer,
) -> dict[str, str]:
    found = unique_prompts(detections, fps)
    mapping = canonical_keys(found)
    complete = [key for key in found if mapping[key] == key]
    if not complete:
        return {}
    prompts = [(found[key][0], spoken_around(cues, found[key][1])) for key in complete]
    answer = model.complete(
        system_prompt, build_request(prompts, target_language), RESPONSE_SCHEMAS[Task.TRANSLATE]
    )
    texts = validate_response(list(range(len(complete))), answer).texts
    translations: dict[str, str] = {}
    for number, key in enumerate(complete):
        text = names.fix(texts.get(number)) or ""
        if text and prompt_key(text) != key:
            translations[key] = text
    for key, whole in mapping.items():
        if key != whole and whole in translations:
            translations[key] = translations[whole]
    return translations
