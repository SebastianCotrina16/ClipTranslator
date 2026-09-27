from __future__ import annotations

from app.application.ports import LanguageModel, LanguageModelError
from app.config.settings import TranslationSettings
from app.infrastructure.gpu import default_translation_model
from app.infrastructure.llm.cloud import AnthropicModel, OpenAICompatibleModel
from app.infrastructure.llm.ollama import OllamaModel


def create_language_model(settings: TranslationSettings, cpu_threads: int = 0) -> LanguageModel:
    if settings.backend == "anthropic":
        return AnthropicModel(settings.anthropic_model, settings.anthropic_key())
    if settings.backend == "openai":
        return OpenAICompatibleModel(
            settings.openai_model, settings.openai_key(), settings.openai_base_url
        )
    if settings.backend == "ollama":
        return OllamaModel(
            settings.ollama_model or default_translation_model(),
            settings.ollama_url,
            cpu_threads=cpu_threads or None,
        )
    raise LanguageModelError(f"Unknown translation backend: {settings.backend!r}")
