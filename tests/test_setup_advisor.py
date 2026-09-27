from __future__ import annotations

from app.application.setup_advisor import (
    GpuSummary,
    ModelFit,
    PerformanceTier,
    SystemReport,
    model_fit,
    plan_from,
    recommend,
)
from app.config.settings import Settings
from app.config.setup import apply_plan

RTX_4090 = GpuSummary("NVIDIA GeForce RTX 4090", 24564, "610.74")
RTX_3060 = GpuSummary("NVIDIA GeForce RTX 3060", 12288, "560.94")
GTX_1660 = GpuSummary("NVIDIA GeForce GTX 1660", 6144, "560.94")
OLD_DRIVER = GpuSummary("NVIDIA GeForce GTX 1660", 6144, "472.12")


def machine(
    gpu: GpuSummary | None = None,
    ram_gb: float = 16,
    cuda: bool = True,
    vram_free_gb: float | None = None,
) -> SystemReport:
    return SystemReport(
        os_name="Windows 11",
        cpu="test",
        cores=8,
        ram_gb=ram_gb,
        gpu=gpu,
        cuda_whisper=gpu is not None and cuda,
        cuda_onnx=gpu is not None and cuda,
        disk_free_gb=200,
        ollama_installed=True,
        ollama_running=True,
        vram_free_gb=vram_free_gb,
    )


def test_high_end_gpu_keeps_room_for_other_apps() -> None:
    recommendation = recommend(machine(RTX_4090, ram_gb=64))
    assert recommendation.tier is PerformanceTier.HIGH
    assert (recommendation.whisper_model, recommendation.compute_type) == ("large-v3", "float16")
    assert recommendation.translation_model == "qwen3.5:9b"
    assert recommendation.fits["qwen3.5:27b"] is ModelFit.TIGHT
    assert recommendation.warnings == []


def test_mid_range_gpu() -> None:
    recommendation = recommend(machine(RTX_3060))
    assert recommendation.tier is PerformanceTier.MID
    assert recommendation.translation_model == "qwen3.5:9b"


def test_gtx_1660_gets_a_model_that_fits_entirely() -> None:
    recommendation = recommend(machine(GTX_1660))
    assert recommendation.tier is PerformanceTier.ENTRY
    assert recommendation.compute_type == "int8_float16"
    assert recommendation.translation_model == "qwen3.5:4b"
    assert recommendation.fits["qwen3.5:4b"] is ModelFit.COMFORTABLE
    assert recommendation.fits["qwen3.5:9b"] is ModelFit.PARTLY_GPU
    assert recommendation.fits["qwen3.5:27b"] is ModelFit.TOO_BIG


def test_cpu_only() -> None:
    recommendation = recommend(machine(None))
    assert recommendation.tier is PerformanceTier.CPU
    assert (recommendation.whisper_model, recommendation.device) == ("large-v3-turbo", "cpu")
    assert recommendation.translation_model == "qwen3.5:4b"
    assert any("API" in warning for warning in recommendation.warnings)


def test_cpu_only_with_little_ram_uses_medium() -> None:
    recommendation = recommend(machine(None, ram_gb=6))
    assert recommendation.whisper_model == "medium"
    assert any("RAM" in warning for warning in recommendation.warnings)


def test_old_driver_warns_and_uses_cpu() -> None:
    recommendation = recommend(machine(OLD_DRIVER, cuda=False))
    assert recommendation.device == "cpu"
    assert any("driver" in warning for warning in recommendation.warnings)


def test_busy_gpu_right_now_is_reported() -> None:
    busy = recommend(machine(RTX_4090, ram_gb=64, vram_free_gb=4.0))
    assert any("other programs are using" in warning for warning in busy.warnings)
    idle = recommend(machine(RTX_4090, ram_gb=64, vram_free_gb=22.0))
    assert not any("other programs" in warning for warning in idle.warnings)


def test_summary_explains_the_headroom() -> None:
    assert "30%" in recommend(machine(GTX_1660)).summary


def test_driver_versions() -> None:
    assert machine(RTX_4090).driver_ok
    assert not machine(OLD_DRIVER).driver_ok
    assert machine(GpuSummary("x", 8000, "527.41")).driver_ok


def test_model_fit_levels() -> None:
    report = machine(GTX_1660)
    assert model_fit(3.4, report) is ModelFit.COMFORTABLE
    assert model_fit(5.0, report) is ModelFit.TIGHT
    assert model_fit(6.6, report) is ModelFit.PARTLY_GPU
    assert model_fit(10.0, report) is ModelFit.CPU_ONLY
    assert model_fit(17.0, report) is ModelFit.TOO_BIG


def test_plan_is_saved_with_low_impact_mode() -> None:
    plan = plan_from(recommend(machine(GTX_1660)), "en")
    plan.low_impact = False
    settings = apply_plan(Settings(), plan)
    assert settings.performance.low_impact is False
    assert settings.translation.ollama_model == "qwen3.5:4b"
    assert settings.translation.target_language == "en"
