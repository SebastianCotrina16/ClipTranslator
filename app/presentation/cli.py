from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.application.pipeline import CACHEABLE_STAGES, Pipeline, PipelineError
from app.application.ports import LanguageModelError
from app.bootstrap import create_pipeline
from app.config.settings import Settings
from app.config.store import SettingsStore
from app.domain.languages import InvalidLanguageCodeError, parse_language_code
from app.infrastructure.ffmpeg import FfmpegError, burn_subtitles
from app.infrastructure.gpu import describe_hardware, sustained_utilization
from app.infrastructure.process import use_utf8_console
from app.infrastructure.separation.mdx import ModelDownloadError
from app.infrastructure.separation.worker import SeparationError

BUSY_GPU_PERCENT = 50
EXPECTED_ERRORS = (
    FileNotFoundError,
    InvalidLanguageCodeError,
    LanguageModelError,
    SeparationError,
    ModelDownloadError,
    PipelineError,
    FfmpegError,
    OSError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cliptranslator",
        description="Transcribe un clip y genera subtítulos traducidos (.srt).",
    )
    parser.add_argument("media", type=Path, help="Video o audio")
    parser.add_argument("-l", "--language", help="Idioma de origen (en, pt, ja...)")
    parser.add_argument("-t", "--to", dest="target", help="Idioma de destino (es, en, pt...)")
    parser.add_argument("-c", "--context", default="", help="Qué pasa en el clip")
    parser.add_argument("--prompt", help="Nombres propios para Whisper")
    parser.add_argument("-o", "--out-dir", type=Path, help="Carpeta de salida")
    parser.add_argument("--vtt", action="store_true", help="Exportar también .vtt")
    parser.add_argument("--burn", action="store_true", help="Quemar los subtítulos en el video")
    parser.add_argument("--no-separation", action="store_true", help="No separar la voz")
    parser.add_argument("--whisper-model", help="large-v3, large-v2, large-v3-turbo...")
    parser.add_argument("--device", choices=["cuda", "cpu"], help="Dispositivo para Whisper")
    parser.add_argument("--compute-type", help="float16, int8_float16, int8...")
    parser.add_argument("--translator", choices=["ollama", "anthropic", "openai"])
    parser.add_argument("--ollama-model", help="Modelo de Ollama")
    parser.add_argument(
        "--force", action="append", choices=CACHEABLE_STAGES, default=[], help="Rehacer etapa"
    )
    parser.add_argument("--config", type=Path, help="Archivo de configuración TOML")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    if args.no_separation:
        settings.separation.enabled = False
    if args.whisper_model:
        settings.transcription.model = args.whisper_model
    if args.device:
        settings.transcription.device = args.device
    if args.compute_type:
        settings.transcription.compute_type = args.compute_type
    if args.translator:
        settings.translation.backend = args.translator
    if args.ollama_model:
        settings.translation.ollama_model = args.ollama_model
    if args.target:
        settings.translation.target_language = parse_language_code(args.target)
    return settings


def print_progress(stage: str, fraction: float, message: str) -> None:
    ending = "\n" if fraction >= 1.0 else "\r"
    print(f"  [{fraction * 100:5.1f}%] {message:<60}", end=ending, flush=True)


def warn_if_gpu_busy() -> None:
    busy = sustained_utilization()
    if busy is not None and busy >= BUSY_GPU_PERCENT:
        print(
            f"Aviso: la GPU ya está al {busy}% por otro programa (¿un juego?). Todo irá más "
            "lento; si la separación de voz se atasca, se repetirá en la CPU."
        )


def process(pipeline: Pipeline, args: argparse.Namespace) -> list[Path]:
    pipeline.isolate_speech()
    if args.language:
        pipeline.set_language(parse_language_code(args.language))
    else:
        detection = pipeline.detect_language()
        top = ", ".join(f"{code} {probability:.0%}" for code, probability in detection.top[:3])
        print(f"Idioma detectado: {detection.language} ({top})")
    pipeline.transcribe(args.prompt)
    pipeline.translate(args.context)
    pipeline.build_cues()
    files = pipeline.export(args.out_dir, vtt=args.vtt)
    if args.burn:
        print("Quemando subtítulos en el video...")
        burned = files[0].with_name(f"{files[0].stem.rsplit('.', 1)[0]}.subtitulado.mp4")
        files.append(burn_subtitles(pipeline.state.media, files[0], burned))
    return files


def print_summary(pipeline: Pipeline, files: list[Path]) -> None:
    for warning in pipeline.state.warnings:
        print(f"Aviso: {warning}")
    for name, value in pipeline.state.backends.items():
        print(f"{name}: {value}")
    cues = pipeline.state.cues
    flagged = sum(1 for cue in cues if cue.flags)
    print(f"{len(cues)} subtítulos ({flagged} marcados para revisar)")
    for path in files:
        print(f"  → {path}")
    print(f"Carpeta de trabajo: {pipeline.state.work_dir}")


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = apply_overrides(SettingsStore(args.config).load(), args)
        print(f"Hardware: {describe_hardware()}")
        warn_if_gpu_busy()
        pipeline = create_pipeline(args.media, settings, print_progress, set(args.force))
        files = process(pipeline, args)
    except EXPECTED_ERRORS as error:
        if args.verbose:
            raise
        print(f"\nError: {error}", file=sys.stderr)
        return 1
    print_summary(pipeline, files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
