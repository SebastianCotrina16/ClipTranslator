from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.application.ports import LanguageModelError
from app.infrastructure.llm.http import parse_json_object, post_json, validated_base_url

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 16000
TOOL_NAME = "subtitulos"


def required_model_name(model: str, service: str) -> str:
    name = model.strip()
    if not name:
        raise LanguageModelError(
            f"Falta el nombre del modelo de {service}. Configúralo con el asistente."
        )
    return name


class AnthropicModel:
    def __init__(self, model: str, api_key: str, temperature: float = 0.3) -> None:
        if not api_key:
            raise LanguageModelError("Falta la clave de la API de Anthropic (ANTHROPIC_API_KEY).")
        self.model = required_model_name(model, "Anthropic")
        self.temperature = temperature
        self._client = httpx.Client(
            timeout=httpx.Timeout(600.0, connect=10.0),
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
        )

    @property
    def description(self) -> str:
        return f"Anthropic {self.model}"

    def prepare(self, progress: Callable[[float, str], None] | None = None) -> list[str]:
        return []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Entrega el resultado de los segmentos.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        data = post_json(self._client, ANTHROPIC_URL, payload, "Anthropic")
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                return block["input"]
        raise LanguageModelError("Anthropic no devolvió el resultado esperado.")

    def unload(self) -> None:
        return None


class OpenAICompatibleModel:
    def __init__(self, model: str, api_key: str, base_url: str, temperature: float = 0.3) -> None:
        self.model = required_model_name(model, "la API compatible con OpenAI")
        self.base_url = validated_base_url(base_url, require_tls_for_remote=True)
        self.temperature = temperature
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0), headers=headers)

    @property
    def description(self) -> str:
        return f"OpenAI-compatible {self.model} ({self.base_url})"

    def prepare(self, progress: Callable[[float, str], None] | None = None) -> list[str]:
        return []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "translations", "schema": schema, "strict": True},
            },
        }
        data = post_json(self._client, f"{self.base_url}/chat/completions", payload, "API")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LanguageModelError("La API devolvió una respuesta inesperada.") from error
        return parse_json_object(content)

    def unload(self) -> None:
        return None
