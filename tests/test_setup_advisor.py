from __future__ import annotations

from app.application.setup_advisor import GpuSummary, ModelFit, SystemReport, model_fit, recommend

RTX_4090 = GpuSummary("NVIDIA GeForce RTX 4090", 24564, "610.74")
GTX_1660 = GpuSummary("NVIDIA GeForce GTX 1660", 6144, "560.94")
OLD_DRIVER = GpuSummary("NVIDIA GeForce GTX 1660", 6144, "472.12")


def machine(gpu: GpuSummary | None = None, ram_gb: float = 16, cuda: bool = True) -> SystemReport:
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
    )


def test_rtx_4090() -> None:
    recommendation = recommend(machine(RTX_4090, ram_gb=64))
    assert (recommendation.whisper_model, recommendation.device, recommendation.compute_type) == (
        "large-v3",
        "cuda",
        "float16",
    )
    assert recommendation.translation_model == "qwen3.5:27b"
    assert recommendation.warnings == []


def test_gtx_1660() -> None:
    recommendation = recommend(machine(GTX_1660))
    assert recommendation.compute_type == "int8_float16"
    assert recommendation.translation_model == "qwen3.5:9b"
    assert recommendation.fits["qwen3.5:9b"] is ModelFit.PARTLY_GPU
    assert recommendation.fits["qwen3.5:27b"] is ModelFit.TOO_BIG


def test_cpu_only() -> None:
    recommendation = recommend(machine(None))
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


def test_driver_versions() -> None:
    assert machine(RTX_4090).driver_ok
    assert not machine(OLD_DRIVER).driver_ok
    assert machine(GpuSummary("x", 8000, "527.41")).driver_ok


def test_model_fit_levels() -> None:
    report = machine(GTX_1660)
    assert model_fit(3.4, report) is ModelFit.FITS_GPU
    assert model_fit(6.6, report) is ModelFit.PARTLY_GPU
    assert model_fit(10.0, report) is ModelFit.CPU_ONLY
    assert model_fit(17.0, report) is ModelFit.TOO_BIG
