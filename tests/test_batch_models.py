from __future__ import annotations

from typing import Any

import pytest

from app import bootstrap
from app.application.pipeline import PipelineServices
from app.config.settings import Settings
from app.infrastructure.llm import ollama
from app.infrastructure.llm.ollama import OllamaModel


class Loaded:
    def __init__(self) -> None:
        self.unloads = 0

    def unload(self) -> None:
        self.unloads += 1


def test_models_are_shared_during_a_batch_and_released_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[Loaded] = []

    def build(settings: Settings) -> PipelineServices:
        def make() -> Loaded:
            made.append(Loaded())
            return made[-1]

        return PipelineServices(None, None, None, make, make, lambda: None)

    monkeypatch.setattr(bootstrap, "build_services", build)
    shared = bootstrap.SharedModels(Settings())
    first = shared.services.create_transcriber()
    assert shared.services.create_transcriber() is first
    model = shared.services.create_language_model()
    assert shared.services.create_language_model() is model
    shared.release_transcriber()
    assert first.unloads == 1 and shared.services.create_transcriber() is not first
    shared.release()
    assert model.unloads == 1 and len(made) == 3


def test_the_context_only_grows_and_model_times_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[int] = []

    def answer(client: Any, url: str, payload: dict[str, Any], name: str) -> dict[str, Any]:
        sent.append(payload["options"]["num_ctx"])
        load = 4e9 if len(sent) == 1 else 1e7
        return {
            "message": {"content": '{"translations": []}'},
            "load_duration": load,
            "prompt_eval_duration": 2e8,
            "eval_duration": 1e9,
        }

    monkeypatch.setattr(ollama, "post_json", answer)
    model = OllamaModel("qwen3.5:9b")
    long_text = "x" * 20_000
    model.complete("system", long_text, {})
    model.complete("system", "short", {})
    assert sent[0] == sent[1] > 4096
    timings = model.take_timings()
    assert timings == {
        "requests": 2,
        "loads": 1,
        "load_seconds": 4.01,
        "read_seconds": 0.4,
        "write_seconds": 2.0,
    }
    assert model.take_timings()["requests"] == 0
    model.unload()
    model.complete("system", "short", {})
    assert sent[-1] == 4096
