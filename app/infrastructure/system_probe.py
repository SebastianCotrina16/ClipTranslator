from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sys
from pathlib import Path

import httpx

from app.application.setup_advisor import SystemReport
from app.infrastructure.gpu import cuda_available, detect_gpu, expose_cuda_libraries
from app.infrastructure.whisper import vad_model_path

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_ram_gb() -> float:
    if sys.platform == "win32":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys / 1024**3
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        return 0.0


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "desconocida"


def onnx_runtime_uses_cuda() -> bool:
    expose_cuda_libraries()
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    model = vad_model_path()
    if model is None or "CUDAExecutionProvider" not in ort.get_available_providers():
        return False
    options = ort.SessionOptions()
    options.log_severity_level = 4
    try:
        session = ort.InferenceSession(str(model), options, providers=["CUDAExecutionProvider"])
    except Exception:
        return False
    return "CUDAExecutionProvider" in session.get_providers()


def ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(default) if default.exists() else None


def ollama_models(url: str = DEFAULT_OLLAMA_URL) -> list[str] | None:
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return [entry["name"] for entry in response.json().get("models", [])]


def scan(data_dir: Path, ollama_url: str = DEFAULT_OLLAMA_URL) -> SystemReport:
    gpu = detect_gpu()
    disk_probe = data_dir if data_dir.exists() else Path(data_dir.anchor or ".")
    installed = ollama_models(ollama_url)
    return SystemReport(
        os_name=f"{platform.system()} {platform.release()}",
        cpu=cpu_name(),
        cores=os.cpu_count() or 1,
        ram_gb=total_ram_gb(),
        gpu=gpu,
        cuda_whisper=gpu is not None and cuda_available(),
        cuda_onnx=gpu is not None and onnx_runtime_uses_cuda(),
        disk_free_gb=shutil.disk_usage(disk_probe).free / 1024**3,
        ollama_installed=installed is not None or ollama_executable() is not None,
        ollama_running=installed is not None,
        ollama_models=installed or [],
    )
