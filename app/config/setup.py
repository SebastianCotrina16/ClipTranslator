from __future__ import annotations

from app.application.setup_advisor import SetupPlan
from app.config.settings import Settings


def apply_plan(settings: Settings, plan: SetupPlan) -> Settings:
    settings.transcription.model = plan.whisper_model
    settings.transcription.device = plan.device
    settings.transcription.compute_type = plan.compute_type
    settings.separation.enabled = plan.voice_isolation
    settings.performance.low_impact = plan.low_impact
    settings.translation.target_language = plan.target_language
    settings.translation.backend = plan.backend
    if plan.backend == "ollama":
        settings.translation.ollama_model = plan.translation_model
    elif plan.backend == "anthropic":
        settings.translation.anthropic_model = plan.api_model
        settings.translation.anthropic_api_key = plan.api_key
    else:
        settings.translation.openai_model = plan.api_model
        settings.translation.openai_api_key = plan.api_key
        settings.translation.openai_base_url = (
            plan.api_base_url or settings.translation.openai_base_url
        )
    return settings
