from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MIN_DRIVER_VERSION = (527, 41)
SEPARATION_MODEL_GB = 0.07


@dataclass(frozen=True)
class ModelOption:
    key: str
    label: str
    size_gb: float
    note: str


WHISPER_MODELS = (
    ModelOption("large-v3", "Whisper large-v3", 3.1, "highest accuracy"),
    ModelOption("large-v2", "Whisper large-v2", 3.1, "alternative; sometimes invents less text"),
    ModelOption("large-v3-turbo", "Whisper large-v3-turbo", 1.6, "faster, less accurate"),
    ModelOption("medium", "Whisper medium", 1.5, "only for modest hardware"),
)

TRANSLATION_MODELS = (
    ModelOption("qwen3.5:4b", "Qwen 3.5 4B", 3.4, "light; weaker with slang"),
    ModelOption("qwen3.5:9b", "Qwen 3.5 9B", 6.6, "good balance"),
    ModelOption("qwen3.5:27b", "Qwen 3.5 27B", 17.0, "best local quality"),
)


COMFORTABLE_VRAM_SHARE = 0.7
TIGHT_VRAM_SHARE = 0.9
PARTIAL_VRAM_SHARE = 1.2
VRAM_HEADROOM = 1.1
MIN_GPU_VRAM_GB = 3.5
FAST_WHISPER_VRAM_GB = 10


class ModelFit(StrEnum):
    COMFORTABLE = "fits with room to spare"
    TIGHT = "fits, but leaves little room for other apps"
    PARTLY_GPU = "does not fit: part runs on the CPU (slower)"
    CPU_ONLY = "runs on the CPU (slow)"
    TOO_BIG = "too big for this computer"


class PerformanceTier(StrEnum):
    HIGH = "High-end GPU"
    MID = "Mid-range GPU"
    ENTRY = "Entry-level GPU"
    CPU = "No compatible GPU"


@dataclass(frozen=True)
class GpuSummary:
    name: str
    vram_mb: int
    driver: str = ""


@dataclass
class SystemReport:
    os_name: str
    cpu: str
    cores: int
    ram_gb: float
    gpu: GpuSummary | None
    cuda_whisper: bool
    cuda_onnx: bool
    disk_free_gb: float
    ollama_installed: bool
    ollama_running: bool
    ollama_models: list[str] = field(default_factory=list)
    vram_free_gb: float | None = None

    @property
    def vram_gb(self) -> float:
        return self.gpu.vram_mb / 1024 if self.gpu else 0.0

    @property
    def gpu_usable(self) -> bool:
        return self.gpu is not None and self.cuda_whisper

    @property
    def driver_ok(self) -> bool:
        if self.gpu is None or not self.gpu.driver:
            return False
        try:
            version = tuple(int(part) for part in self.gpu.driver.split(".")[:2])
        except ValueError:
            return False
        return version >= MIN_DRIVER_VERSION


@dataclass
class Recommendation:
    whisper_model: str
    device: str
    compute_type: str
    separation: bool
    translation_model: str
    tier: PerformanceTier = PerformanceTier.CPU
    summary: str = ""
    low_impact: bool = True
    fits: dict[str, ModelFit] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def model_fit(size_gb: float, report: SystemReport) -> ModelFit:
    if report.gpu_usable:
        if size_gb <= report.vram_gb * COMFORTABLE_VRAM_SHARE:
            return ModelFit.COMFORTABLE
        if size_gb <= report.vram_gb * TIGHT_VRAM_SHARE:
            return ModelFit.TIGHT
        if size_gb <= report.vram_gb * PARTIAL_VRAM_SHARE and report.ram_gb >= 12:
            return ModelFit.PARTLY_GPU
    if size_gb + 4 <= report.ram_gb:
        return ModelFit.CPU_ONLY
    return ModelFit.TOO_BIG


def tier_for(report: SystemReport) -> PerformanceTier:
    if not report.gpu_usable or report.vram_gb < MIN_GPU_VRAM_GB:
        return PerformanceTier.CPU
    if report.vram_gb >= 16:
        return PerformanceTier.HIGH
    if report.vram_gb >= 8:
        return PerformanceTier.MID
    return PerformanceTier.ENTRY


def recommend(report: SystemReport) -> Recommendation:
    warnings = _hardware_warnings(report)
    tier = tier_for(report)
    if tier is PerformanceTier.CPU:
        device, compute_type = "cpu", "int8"
        whisper_model = "large-v3-turbo" if report.ram_gb >= 8 else "medium"
        warnings.append(
            "Without a compatible GPU, transcription runs on the CPU: a 5-minute clip can "
            "take much longer than real time."
        )
    else:
        device = "cuda"
        compute_type = "float16" if report.vram_gb >= FAST_WHISPER_VRAM_GB else "int8_float16"
        whisper_model = "large-v3"
    fits = {option.key: model_fit(option.size_gb, report) for option in TRANSLATION_MODELS}
    translation_model = _smooth_translation_model(fits)
    if fits[translation_model] not in (ModelFit.COMFORTABLE, ModelFit.TIGHT):
        warnings.append(
            "Local translation runs on the CPU and the small model has limited quality; "
            "an API key (Anthropic/OpenAI) gives better translations."
        )
    warnings += _busy_gpu_warnings(report, translation_model)
    if report.ram_gb and report.ram_gb < 8:
        warnings.append(f"Only {report.ram_gb:.0f} GB of RAM; large models will be tight.")
    return Recommendation(
        whisper_model=whisper_model,
        device=device,
        compute_type=compute_type,
        separation=True,
        translation_model=translation_model,
        tier=tier,
        summary=_summary(report, tier),
        low_impact=True,
        fits=fits,
        warnings=warnings,
    )


def _smooth_translation_model(fits: dict[str, ModelFit]) -> str:
    comfortable = [o for o in TRANSLATION_MODELS if fits[o.key] is ModelFit.COMFORTABLE]
    if comfortable:
        return max(comfortable, key=lambda option: option.size_gb).key
    tight = [o for o in TRANSLATION_MODELS if fits[o.key] is ModelFit.TIGHT]
    if tight:
        return min(tight, key=lambda option: option.size_gb).key
    return TRANSLATION_MODELS[0].key


def _summary(report: SystemReport, tier: PerformanceTier) -> str:
    if tier is PerformanceTier.CPU:
        return (
            f"{tier}: everything runs on the processor. The recommended models are the "
            "lightest ones that still give good results."
        )
    return (
        f"{tier} with {report.vram_gb:.0f} GB of memory. The recommended models leave about "
        f"{1 - COMFORTABLE_VRAM_SHARE:.0%} of the GPU free, so games, OBS and the desktop "
        "stay smooth while subtitles are generated."
    )


def _busy_gpu_warnings(report: SystemReport, translation_model: str) -> list[str]:
    size = translation_model_size(translation_model)
    if report.vram_free_gb is None or size is None or not report.gpu_usable:
        return []
    if report.vram_free_gb >= size * VRAM_HEADROOM:
        return []
    used = report.vram_gb - report.vram_free_gb
    return [
        f"Right now other programs are using {used:.0f} GB of GPU memory. Close them "
        "before generating subtitles, or translation will be slower."
    ]


def _hardware_warnings(report: SystemReport) -> list[str]:
    warnings: list[str] = []
    if report.gpu is not None and not report.driver_ok:
        warnings.append(
            f"The NVIDIA driver ({report.gpu.driver or '?'}) is too old for CUDA 12: "
            "update it from nvidia.com to use the GPU."
        )
    if report.gpu is not None and not report.gpu_usable:
        warnings.append("An NVIDIA GPU was found but CUDA could not use it; the CPU will be used.")
    return warnings


def translation_model_size(key: str) -> float | None:
    return next((option.size_gb for option in TRANSLATION_MODELS if option.key == key), None)


def whisper_model_size(key: str) -> float | None:
    return next((option.size_gb for option in WHISPER_MODELS if option.key == key), None)


@dataclass
class SetupPlan:
    whisper_model: str
    device: str
    compute_type: str
    voice_isolation: bool
    target_language: str
    backend: str
    translation_model: str = ""
    api_model: str = ""
    api_key: str = field(default="", repr=False)
    api_base_url: str = ""
    low_impact: bool = True

    @property
    def uses_ollama(self) -> bool:
        return self.backend == "ollama"


def plan_from(recommendation: Recommendation, target_language: str) -> SetupPlan:
    return SetupPlan(
        whisper_model=recommendation.whisper_model,
        device=recommendation.device,
        compute_type=recommendation.compute_type,
        voice_isolation=recommendation.separation,
        target_language=target_language,
        backend="ollama",
        translation_model=recommendation.translation_model,
        low_impact=recommendation.low_impact,
    )


def pending_download_gb(
    plan: SetupPlan,
    whisper_ready: bool,
    isolation_ready: bool,
    installed_translation_models: list[str],
) -> float:
    size = 0.0 if whisper_ready else whisper_model_size(plan.whisper_model) or 0.0
    if plan.voice_isolation and not isolation_ready:
        size += SEPARATION_MODEL_GB
    if plan.uses_ollama and plan.translation_model not in installed_translation_models:
        size += translation_model_size(plan.translation_model) or 0.0
    return size
