from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.application.setup_advisor import GpuSummary

LARGE_VRAM_MB = 10_000
HUGE_VRAM_MB = 20_000


@dataclass(frozen=True)
class WhisperDefaults:
    device: str
    compute_type: str
    model: str


@cache
def expose_cuda_libraries() -> list[Path]:
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    folders: list[Path] = []
    for root in spec.submodule_search_locations:
        for folder in sorted(Path(root).glob("*/bin")):
            folders.append(folder)
            if sys.platform == "win32":
                os.add_dll_directory(str(folder))
    if folders:
        os.environ["PATH"] = os.pathsep.join([*map(str, folders), os.environ.get("PATH", "")])
    return folders


def _query(field: str) -> list[str] | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        output = subprocess.run(
            [executable, f"--query-gpu={field}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    lines = output.strip().splitlines()
    return [part.strip() for part in lines[0].rsplit(",", field.count(","))] if lines else None


@cache
def detect_gpu() -> GpuSummary | None:
    values = _query("name,memory.total,driver_version")
    if not values or len(values) != 3:
        return None
    name, vram, driver = values
    try:
        return GpuSummary(name=name, vram_mb=int(float(vram)), driver=driver)
    except ValueError:
        return None


def free_vram_mb() -> int | None:
    values = _query("memory.free")
    try:
        return int(float(values[0])) if values else None
    except ValueError:
        return None


def sustained_utilization(samples: int = 5, interval: float = 0.2) -> int | None:
    readings: list[int] = []
    for index in range(samples):
        if index:
            time.sleep(interval)
        values = _query("utilization.gpu")
        try:
            readings.append(int(float(values[0])))
        except (TypeError, ValueError, IndexError):
            return None
    return min(readings) if readings else None


def cuda_available() -> bool:
    expose_cuda_libraries()
    try:
        import ctranslate2
    except ImportError:
        return False
    return ctranslate2.get_cuda_device_count() > 0


def whisper_defaults() -> WhisperDefaults:
    gpu = detect_gpu()
    if gpu is not None and cuda_available():
        compute_type = "float16" if gpu.vram_mb >= LARGE_VRAM_MB else "int8_float16"
        return WhisperDefaults("cuda", compute_type, "large-v3")
    return WhisperDefaults("cpu", "int8", "large-v3-turbo")


def default_translation_model() -> str:
    gpu = detect_gpu()
    if gpu is None:
        return "qwen3.5:4b"
    return "qwen3.5:27b" if gpu.vram_mb >= HUGE_VRAM_MB else "qwen3.5:9b"


def describe_hardware() -> str:
    gpu = detect_gpu()
    defaults = whisper_defaults()
    gpu_text = f"{gpu.name} ({gpu.vram_mb} MB)" if gpu else "sin GPU NVIDIA"
    return f"{gpu_text} → Whisper {defaults.model} en {defaults.device} ({defaults.compute_type})"
