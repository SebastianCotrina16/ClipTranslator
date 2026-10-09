from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from typing import Any

import httpx

from app.application.ports import LanguageModelError
from app.application.setup_advisor import translation_model_size
from app.infrastructure.gpu import free_vram_mb
from app.infrastructure.llm.http import parse_json_object, post_json, validated_base_url

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
VRAM_HEADROOM = 1.1
MIN_CONTEXT = 4096
MAX_CONTEXT = 65536


NANOSECONDS = 1e9
RELOAD_SECONDS = 1.0
TIMING_FIELDS = {
    "load_seconds": "load_duration",
    "read_seconds": "prompt_eval_duration",
    "write_seconds": "eval_duration",
}


def empty_timings() -> dict[str, float]:
    return {"requests": 0, "loads": 0, **{name: 0.0 for name in TIMING_FIELDS}}


def context_size_for(system: str, user: str) -> int:
    estimated_tokens = (len(system) + len(user)) // 3
    needed = estimated_tokens * 3 + 512
    size = MIN_CONTEXT
    while size < needed and size < MAX_CONTEXT:
        size *= 2
    return size


class OllamaModel:
    def __init__(
        self,
        model: str,
        url: str = "http://127.0.0.1:11434",
        temperature: float = 0.3,
        cpu_threads: int | None = None,
    ) -> None:
        self.model = model
        self.url = validated_base_url(url, require_tls_for_remote=False)
        self.temperature = temperature
        self.cpu_threads = cpu_threads
        self._client = httpx.Client(timeout=httpx.Timeout(1800.0, connect=10.0))
        self._context = 0
        self._timings = empty_timings()

    @property
    def description(self) -> str:
        return f"Ollama {self.model}"

    def is_running(self) -> bool:
        try:
            self._client.get(f"{self.url}/api/version", timeout=5).raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    def installed_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.url}/api/tags", timeout=10)
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        return [entry["name"] for entry in response.json().get("models", [])]

    def is_loaded(self) -> bool:
        try:
            response = self._client.get(f"{self.url}/api/ps", timeout=5)
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        names = {entry.get("name") for entry in response.json().get("models", [])}
        return self.model in names or f"{self.model}:latest" in names

    def prepare(self, progress: Callable[[float, str], None] | None = None) -> list[str]:
        if not self.is_running():
            raise LanguageModelError(
                f"Ollama is not responding. Open it (or install it from {OLLAMA_DOWNLOAD_URL}) "
                "or choose API translation in Settings."
            )
        warnings = [] if self.is_loaded() else self._vram_warnings()
        self.pull(progress)
        return warnings

    def pull(self, progress: Callable[[float, str], None] | None = None) -> None:
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted in self.installed_models():
            return
        try:
            with self._client.stream(
                "POST", f"{self.url}/api/pull", json={"model": self.model, "stream": True}
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    self._handle_pull_event(line, progress)
        except httpx.HTTPError as error:
            raise LanguageModelError(f"Could not download {self.model}: {error}") from error

    @staticmethod
    def _handle_pull_event(line: str, progress: Callable[[float, str], None] | None) -> None:
        if not line:
            return
        event = json.loads(line)
        if "error" in event:
            raise LanguageModelError(f"Ollama: {event['error']}")
        if progress and event.get("total"):
            progress(event.get("completed", 0) / event["total"], event.get("status", ""))

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self._context = max(self._context, context_size_for(system, user))
        options: dict[str, Any] = {
            "temperature": self.temperature,
            "num_ctx": self._context,
        }
        if self.cpu_threads:
            options["num_thread"] = self.cpu_threads
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "options": options,
        }
        try:
            data = post_json(self._client, f"{self.url}/api/chat", payload, "Ollama")
        except LanguageModelError as error:
            if "think" not in str(error):
                raise
            payload.pop("think")
            data = post_json(self._client, f"{self.url}/api/chat", payload, "Ollama")
        self._record(data)
        return parse_json_object(data["message"]["content"])

    def take_timings(self) -> dict[str, float]:
        taken, self._timings = self._timings, empty_timings()
        return {name: round(value, 2) for name, value in taken.items()}

    def _record(self, data: dict[str, Any]) -> None:
        self._timings["requests"] += 1
        for name, field in TIMING_FIELDS.items():
            self._timings[name] += data.get(field, 0) / NANOSECONDS
        self._timings["loads"] += data.get("load_duration", 0) / NANOSECONDS > RELOAD_SECONDS

    def unload(self) -> None:
        self._context = 0
        with contextlib.suppress(httpx.HTTPError):
            self._client.post(
                f"{self.url}/api/generate", json={"model": self.model, "keep_alive": 0}
            )

    def _vram_warnings(self) -> list[str]:
        size = translation_model_size(self.model)
        free = free_vram_mb()
        if size is None or free is None or free / 1024 >= size * VRAM_HEADROOM:
            return []
        return [
            f"Only {free / 1024:.1f} GB free on the GPU and {self.model} needs about "
            f"{size * VRAM_HEADROOM:.0f} GB: part of it will run on the CPU and translation "
            "will be much slower. Close programs using the GPU (games, OBS, "
            "hardware-accelerated browsers) or choose a smaller model."
        ]
