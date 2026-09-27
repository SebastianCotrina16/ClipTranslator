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


class ModelFit(StrEnum):
    FITS_GPU = "fits in your GPU"
    PARTLY_GPU = "almost fits: part runs on the CPU (slower)"
    CPU_ONLY = "runs on the CPU (slow)"
    TOO_BIG = "too big for this computer"


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
    fits: dict[str, ModelFit] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def model_fit(size_gb: float, report: SystemReport) -> ModelFit:
    if report.gpu_usable:
        if size_gb <= report.vram_gb * 0.9:
            return ModelFit.FITS_GPU
        if size_gb <= report.vram_gb * 1.2 and report.ram_gb >= 12:
            return ModelFit.PARTLY_GPU
    if size_gb + 4 <= report.ram_gb:
        return ModelFit.CPU_ONLY
    return ModelFit.TOO_BIG


def recommend(report: SystemReport) -> Recommendation:
    warnings = _hardware_warnings(report)
    if report.gpu_usable and report.vram_gb >= 3.5:
        device = "cuda"
        compute_type = "float16" if report.vram_gb >= 10 else "int8_float16"
        whisper_model = "large-v3"
    else:
        device, compute_type = "cpu", "int8"
        whisper_model = "large-v3-turbo" if report.ram_gb >= 8 else "medium"
        warnings.append(
            "Without a compatible GPU, transcription runs on the CPU: a 5-minute clip can "
            "take much longer than real time."
        )
    fits = {option.key: model_fit(option.size_gb, report) for option in TRANSLATION_MODELS}
    on_gpu = [
        option
        for option in TRANSLATION_MODELS
        if fits[option.key] in (ModelFit.FITS_GPU, ModelFit.PARTLY_GPU)
    ]
    if on_gpu:
        translation_model = max(on_gpu, key=lambda option: option.size_gb).key
    else:
        translation_model = TRANSLATION_MODELS[0].key
        warnings.append(
            "Local translation runs on the CPU and the small model has limited quality; "
            "an API key (Anthropic/OpenAI) gives better translations."
        )
    if report.ram_gb and report.ram_gb < 8:
        warnings.append(f"Only {report.ram_gb:.0f} GB of RAM; large models will be tight.")
    return Recommendation(
        whisper_model=whisper_model,
        device=device,
        compute_type=compute_type,
        separation=True,
        translation_model=translation_model,
        fits=fits,
        warnings=warnings,
    )


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
