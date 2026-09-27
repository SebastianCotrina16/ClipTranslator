from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.application.ports import FractionCallback, SeparationResult
from app.infrastructure.gpu import detect_gpu
from app.infrastructure.separation.mdx import MdxSeparator, download_model, separate_file

GPU_STALL_SECONDS = 45.0
CPU_STALL_SECONDS = 300.0
PROGRESS_PREFIX = "PROGRESS "
GPU_STALL_WARNING = (
    "La separación de voz en la GPU no respondió ({error}); se repitió en la CPU. "
    "Suele pasar si un juego u otro programa está usando mucho la GPU."
)


class SeparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerOutcome:
    succeeded: bool
    error: str = ""


class IsolatedVocalSeparator:
    def __init__(
        self,
        model_name: str,
        models_dir: Path,
        low_impact: bool = True,
        threads: int = 0,
        gpu_stall_seconds: float = GPU_STALL_SECONDS,
        cpu_stall_seconds: float = CPU_STALL_SECONDS,
    ) -> None:
        self.model_name = model_name
        self.models_dir = models_dir
        self.low_impact = low_impact
        self.threads = threads
        self.gpu_stall_seconds = gpu_stall_seconds
        self.cpu_stall_seconds = cpu_stall_seconds

    def separate(
        self, stereo_wav: Path, output: Path, progress: FractionCallback | None = None
    ) -> SeparationResult:
        download_model(self.model_name, self.models_dir)
        warning = ""
        if detect_gpu() is not None:
            outcome = self._run_worker(stereo_wav, output, "cuda", self.gpu_stall_seconds, progress)
            if outcome.succeeded:
                return SeparationResult(output, "cuda")
            warning = GPU_STALL_WARNING.format(error=outcome.error)
        outcome = self._run_worker(stereo_wav, output, "cpu", self.cpu_stall_seconds, progress)
        if not outcome.succeeded:
            raise SeparationError(f"La separación de voz falló: {outcome.error}")
        return SeparationResult(output, "cpu", warning)

    def _command(self, source: Path, output: Path, device: str) -> list[str]:
        batch_size = 1 if self.low_impact else 4
        return [
            sys.executable,
            "-m",
            "app.infrastructure.separation.worker",
            str(source),
            str(output),
            "--model",
            self.model_name,
            "--models-dir",
            str(self.models_dir),
            "--device",
            device,
            "--batch-size",
            str(batch_size),
            "--threads",
            str(self.threads),
        ]

    def _creation_flags(self) -> int:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if self.low_impact:
            flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        return flags

    def _run_worker(
        self,
        source: Path,
        output: Path,
        device: str,
        stall_seconds: float,
        progress: FractionCallback | None,
    ) -> WorkerOutcome:
        last_activity = [time.monotonic()]
        with tempfile.TemporaryFile() as error_log:
            process = subprocess.Popen(
                self._command(source, output, device),
                stdout=subprocess.PIPE,
                stderr=error_log,
                text=True,
                creationflags=self._creation_flags(),
            )

            output = process.stdout
            if output is None:
                process.kill()
                raise SeparationError("No se pudo leer el progreso de la separación.")

            def follow_progress() -> None:
                for line in output:
                    if line.startswith(PROGRESS_PREFIX):
                        last_activity[0] = time.monotonic()
                        if progress:
                            progress(float(line.removeprefix(PROGRESS_PREFIX)))

            reader = threading.Thread(target=follow_progress, daemon=True)
            reader.start()
            while process.poll() is None:
                if time.monotonic() - last_activity[0] > stall_seconds:
                    process.kill()
                    process.wait()
                    return WorkerOutcome(False, f"sin progreso durante {stall_seconds:.0f} s")
                time.sleep(0.25)
            reader.join(timeout=2)
            if process.returncode != 0:
                error_log.seek(0)
                tail = error_log.read().decode("utf-8", "replace").strip().splitlines()[-3:]
                return WorkerOutcome(False, " | ".join(tail) or f"código {process.returncode}")
        return WorkerOutcome(True)


def _report_progress(fraction: float) -> None:
    print(f"{PROGRESS_PREFIX}{fraction:.4f}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Separación de voz en un proceso aparte")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=0)
    args = parser.parse_args()
    _report_progress(0.0)
    separator = MdxSeparator(
        args.model, args.models_dir, args.device, max(args.batch_size, 1), args.threads
    )
    separate_file(args.source, args.output, separator, _report_progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
