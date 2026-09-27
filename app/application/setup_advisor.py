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
    ModelOption("large-v3", "Whisper large-v3", 3.1, "máxima precisión"),
    ModelOption("large-v2", "Whisper large-v2", 3.1, "alternativa; a veces inventa menos texto"),
    ModelOption("large-v3-turbo", "Whisper large-v3-turbo", 1.6, "más rápido, menos preciso"),
    ModelOption("medium", "Whisper medium", 1.5, "solo para equipos modestos"),
)

TRANSLATION_MODELS = (
    ModelOption("qwen3.5:4b", "Qwen 3.5 4B", 3.4, "ligero; calidad justa con jerga"),
    ModelOption("qwen3.5:9b", "Qwen 3.5 9B", 6.6, "buen equilibrio"),
    ModelOption("qwen3.5:27b", "Qwen 3.5 27B", 17.0, "la mejor calidad local"),
)


class ModelFit(StrEnum):
    FITS_GPU = "cabe en tu GPU"
    PARTLY_GPU = "casi cabe: una parte irá a la CPU (más lento)"
    CPU_ONLY = "irá en la CPU (lento)"
    TOO_BIG = "no cabe en tu equipo"


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
            "Sin GPU compatible la transcripción irá en la CPU: un clip de 5 min puede "
            "tardar bastante más que en tiempo real."
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
            "La traducción local irá en la CPU y la calidad del modelo pequeño es limitada; "
            "si tienes una clave de API (Anthropic/OpenAI) la traducción será mejor."
        )
    if report.ram_gb and report.ram_gb < 8:
        warnings.append(f"Solo hay {report.ram_gb:.0f} GB de RAM; los modelos grandes irán justos.")
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
            f"El driver de NVIDIA ({report.gpu.driver or '?'}) es antiguo para CUDA 12: "
            "actualízalo desde nvidia.com para usar la GPU."
        )
    if report.gpu is not None and not report.gpu_usable:
        warnings.append("Hay una GPU NVIDIA pero no se pudo usar con CUDA; se usará la CPU.")
    return warnings


def translation_model_size(key: str) -> float | None:
    return next((option.size_gb for option in TRANSLATION_MODELS if option.key == key), None)


def whisper_model_size(key: str) -> float | None:
    return next((option.size_gb for option in WHISPER_MODELS if option.key == key), None)
