from __future__ import annotations

import json

import httpx
import pytest

from app import bootstrap
from app.application.pipeline import PipelineServices
from app.application.ports import LanguageModelError
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


def streamed(pieces: list[str], **final: float) -> httpx.Response:
    lines = [json.dumps({"message": {"content": piece}, "done": False}) for piece in pieces]
    lines.append(json.dumps({"message": {"content": ""}, "done": True, **final}))
    return httpx.Response(200, content="\n".join(lines).encode())


def test_the_context_only_grows_and_model_times_are_counted() -> None:
    sent: list[int] = []

    def answer(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path.endswith("/api/generate"):
            return httpx.Response(200, json={})
        assert payload["stream"] is True
        sent.append(payload["options"]["num_ctx"])
        load = 4e9 if len(sent) == 1 else 1e7
        return streamed(
            ['{"translations"', ": []}"],
            load_duration=load,
            prompt_eval_duration=2e8,
            eval_duration=1e9,
        )

    model = OllamaModel("qwen3.5:9b")
    model._client = httpx.Client(transport=httpx.MockTransport(answer))
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


def test_a_closed_local_ollama_is_started_in_the_background(monkeypatch) -> None:
    started: list[list[str]] = []
    answers = iter([False, False, True])
    monkeypatch.setattr(OllamaModel, "is_running", lambda self: next(answers))
    monkeypatch.setattr(ollama, "ollama_executable", lambda: "ollama.exe")
    monkeypatch.setattr(
        ollama, "launch_server", lambda executable: started.append([executable, "serve"])
    )
    monkeypatch.setattr(ollama.time, "sleep", lambda seconds: None)
    assert OllamaModel("qwen3.5:9b").start_if_needed()
    assert started == [["ollama.exe", "serve"]]


def test_a_remote_ollama_is_never_started(monkeypatch) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(OllamaModel, "is_running", lambda self: False)
    monkeypatch.setattr(ollama, "ollama_executable", lambda: "ollama.exe")
    monkeypatch.setattr(
        ollama, "launch_server", lambda executable: started.append([executable, "serve"])
    )
    assert not OllamaModel("qwen3.5:9b", "http://192.168.1.20:11434").start_if_needed()
    assert started == []


class FakeServer:
    def __init__(self, running: bool) -> None:
        self.running = running

    def poll(self) -> int | None:
        return None if self.running else 0


def test_only_the_ollama_the_app_started_and_still_runs_is_stopped(monkeypatch) -> None:
    stopped: list[FakeServer] = []
    servers = [FakeServer(True), FakeServer(False)]
    launches = iter(servers)
    monkeypatch.setattr(ollama, "start_in_background", lambda command: next(launches))
    monkeypatch.setattr(ollama, "stop_process_tree", stopped.append)
    ollama.launch_server("ollama.exe")
    ollama.launch_server("ollama.exe")
    assert ollama.stop_launched_servers() == 1
    assert stopped == [servers[0]]
    assert ollama.stop_launched_servers() == 0


def test_the_answer_is_shown_while_the_model_writes_it() -> None:
    pieces = ['{"translations": [{"id": 0, "text": "a"}, ', '{"id": 1, "text": "b"}]}']
    seen: list[str] = []
    model = OllamaModel("qwen3.5:9b")
    model._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: streamed(pieces, eval_duration=1e9))
    )
    answer = model.complete("system", "user", {}, seen.append)
    assert seen == pieces
    assert [entry["id"] for entry in answer["translations"]] == [0, 1]


def test_an_ollama_error_while_streaming_is_reported() -> None:
    model = OllamaModel("qwen3.5:9b")
    model._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'{"error": "model crashed"}')
        )
    )
    with pytest.raises(LanguageModelError, match="model crashed"):
        model.complete("system", "user", {})
