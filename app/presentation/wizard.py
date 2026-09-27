from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from app.application.setup_advisor import (
    SEPARATION_MODEL_GB,
    TRANSLATION_MODELS,
    WHISPER_MODELS,
    Recommendation,
    SystemReport,
    recommend,
    translation_model_size,
    whisper_model_size,
)
from app.bootstrap import whisper_models_dir
from app.config.settings import ANTHROPIC_KEY_VARIABLE, OPENAI_KEY_VARIABLE, Settings
from app.config.store import SettingsStore, data_dir, models_dir
from app.domain.languages import TARGET_LANGUAGES, InvalidLanguageCodeError, parse_language_code
from app.infrastructure.ffmpeg import FfmpegAudio
from app.infrastructure.llm.ollama import OLLAMA_DOWNLOAD_URL, OllamaModel
from app.infrastructure.process import use_utf8_console
from app.infrastructure.separation.mdx import download_model as download_separation_model
from app.infrastructure.separation.mdx import model_file
from app.infrastructure.system_probe import ollama_executable, ollama_models, scan
from app.infrastructure.whisper import (
    FasterWhisperTranscriber,
    WhisperOptions,
    download_whisper_model,
    is_model_downloaded,
)
from app.presentation.console import Console

TEST_SENTENCE = (
    "Oh my god, look at this drawing. It is a cat riding a bicycle on the moon. "
    "That is the best thing I have seen today."
)
TEST_KEYWORDS = ("drawing", "cat", "bicycle", "moon")
WHISPER_WINDOW_SECONDS = 30.0
OLLAMA_START_TIMEOUT = 30
SPEECH_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$voice.SetOutputToWaveFile($env:CLIPTRANSLATOR_TEST_WAV);"
    "$voice.Speak($env:CLIPTRANSLATOR_TEST_TEXT);"
    "$voice.Dispose()"
)


@dataclass
class Choices:
    whisper_model: str
    separation: bool
    target_language: str
    backend: str
    translation_model: str


def yes_no(flag: bool) -> str:
    return "sí" if flag else "no"


def print_report(report: SystemReport) -> None:
    print("\nTu equipo:")
    print(f"  Sistema:  {report.os_name}")
    print(f"  CPU:      {report.cpu} ({report.cores} hilos)")
    print(f"  RAM:      {report.ram_gb:.0f} GB")
    if report.gpu:
        driver = f"driver {report.gpu.driver}" + ("" if report.driver_ok else " (antiguo)")
        print(f"  GPU:      {report.gpu.name}, {report.vram_gb:.0f} GB, {driver}")
        print(
            f"  CUDA:     Whisper {yes_no(report.cuda_whisper)}, "
            f"separación de voz {yes_no(report.cuda_onnx)}"
        )
    else:
        print("  GPU:      no hay GPU NVIDIA (se usará la CPU)")
    print(f"  Disco:    {report.disk_free_gb:.0f} GB libres")
    if report.ollama_running:
        print(f"  Ollama:   en ejecución; modelos: {', '.join(report.ollama_models) or 'ninguno'}")
    elif report.ollama_installed:
        print("  Ollama:   instalado pero no está abierto")
    else:
        print("  Ollama:   no instalado")


def choose_whisper(console: Console, recommendation: Recommendation) -> str:
    print("\n1) Transcripción (Whisper)")
    labels = []
    for option in WHISPER_MODELS:
        tag = "  ← recomendado" if option.key == recommendation.whisper_model else ""
        cached = " (ya descargado)" if is_model_downloaded(option.key, whisper_models_dir()) else ""
        labels.append(f"{option.key:<16} {option.size_gb:>4.1f} GB  {option.note}{cached}{tag}")
    default = [option.key for option in WHISPER_MODELS].index(recommendation.whisper_model)
    return WHISPER_MODELS[console.choose("   Elige", labels, default)].key


def choose_target_language(console: Console, current: str) -> str:
    print("\n3) Idioma al que traducir / Language to translate into")
    codes = list(TARGET_LANGUAGES)
    labels = [f"{TARGET_LANGUAGES[code]} ({code})" for code in codes]
    labels.append("Otro / Other (código ISO, p. ej. de, it, ja)")
    default = codes.index(current) if current in codes else 0
    index = console.choose("   Elige / Choose", labels, default)
    if index < len(codes):
        return codes[index]
    while True:
        try:
            return parse_language_code(console.ask("   Código / Code", current))
        except InvalidLanguageCodeError as error:
            print(f"   {error}")


def choose_translation(
    console: Console, recommendation: Recommendation, report: SystemReport
) -> tuple[str, str]:
    print("\n4) Traducción")
    labels = []
    for option in TRANSLATION_MODELS:
        tag = "  ← recomendado" if option.key == recommendation.translation_model else ""
        installed = " (ya instalado)" if option.key in report.ollama_models else ""
        fit = recommendation.fits[option.key]
        labels.append(
            f"Ollama {option.key:<12} {option.size_gb:>4.1f} GB  {option.note}; {fit}"
            f"{installed}{tag}"
        )
    labels += [
        "Otro modelo de Ollama (escribes el nombre)",
        "API de Anthropic: la mejor calidad, necesita clave y cuesta céntimos por clip",
        "API de OpenAI o compatible: necesita clave",
    ]
    keys = [option.key for option in TRANSLATION_MODELS]
    index = console.choose("   Elige", labels, keys.index(recommendation.translation_model))
    if index < len(keys):
        return "ollama", keys[index]
    if index == len(keys):
        name = console.ask(
            "   Nombre del modelo (p. ej. gemma4:12b)", recommendation.translation_model
        )
        return "ollama", name
    return ("anthropic", "") if index == len(keys) + 1 else ("openai", "")


def configure_api(console: Console, settings: Settings, backend: str) -> None:
    translation = settings.translation
    variable = ANTHROPIC_KEY_VARIABLE if backend == "anthropic" else OPENAI_KEY_VARIABLE
    if backend == "openai":
        translation.openai_base_url = console.ask("   URL base", translation.openai_base_url)
        translation.openai_model = console.ask_required("   Modelo", translation.openai_model)
    else:
        translation.anthropic_model = console.ask_required("   Modelo", translation.anthropic_model)
    if os.environ.get(variable):
        print(f"   Se usará la clave de la variable de entorno {variable}.")
        return
    print(
        f"   La clave se guardará en {SettingsStore().path} (solo en este equipo).\n"
        f"   Si prefieres no guardarla, déjala vacía y define la variable {variable}."
    )
    key = console.ask_secret("   Clave (no se muestra): ")
    if backend == "anthropic":
        translation.anthropic_api_key = key
    else:
        translation.openai_api_key = key


def ensure_ollama_running(console: Console, report: SystemReport, url: str) -> bool:
    if report.ollama_running:
        return True
    if not report.ollama_installed and not install_ollama(console):
        return False
    executable = ollama_executable()
    if executable:
        print("   Abriendo Ollama...")
        subprocess.Popen(
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for _ in range(OLLAMA_START_TIMEOUT):
            time.sleep(1)
            if ollama_models(url) is not None:
                return True
    print("   Ollama no responde. Ábrelo desde el menú Inicio y vuelve a intentarlo.")
    return False


def install_ollama(console: Console) -> bool:
    print("\n   Ollama no está instalado (es el programa que ejecuta el traductor local).")
    if not console.confirm("   ¿Instalarlo ahora con winget?"):
        webbrowser.open(OLLAMA_DOWNLOAD_URL)
        print("   Instálalo desde la página que se abrió y vuelve a ejecutar el asistente.")
        return False
    result = subprocess.run(
        [
            "winget",
            "install",
            "--id",
            "Ollama.Ollama",
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
    )
    if result.returncode != 0:
        print("   No se pudo instalar Ollama con winget.")
        return False
    return True


def pending_download_gb(choices: Choices, report: SystemReport, model_name: str) -> float:
    size = 0.0
    if not is_model_downloaded(choices.whisper_model, whisper_models_dir()):
        size += whisper_model_size(choices.whisper_model) or 0.0
    if choices.separation and not model_file(model_name, models_dir()).exists():
        size += SEPARATION_MODEL_GB
    if choices.backend == "ollama" and choices.translation_model not in report.ollama_models:
        size += translation_model_size(choices.translation_model) or 0.0
    return size


def download_everything(
    console: Console, choices: Choices, settings: Settings, report: SystemReport
) -> bool:
    print("\nDescargando...")
    print(f"   Whisper {choices.whisper_model}...")
    download_whisper_model(choices.whisper_model, whisper_models_dir())
    if choices.separation:
        download_separation_model(
            settings.separation.model,
            models_dir(),
            lambda f: print(f"\r   Separación de voz... {f:5.1%}", end="", flush=True),
        )
        print()
    if choices.backend != "ollama":
        return True
    url = settings.translation.ollama_url
    if not ensure_ollama_running(console, report, url):
        return False
    OllamaModel(choices.translation_model, url).pull(
        lambda f, status: print(f"\r   Ollama: {status} {f:5.1%}{' ' * 20}", end="", flush=True)
    )
    print()
    return True


def synthesize_test_audio(folder: Path) -> Path | None:
    if sys.platform != "win32":
        return None
    wav = folder / "prueba.wav"
    environment = {
        **os.environ,
        "CLIPTRANSLATOR_TEST_WAV": str(wav),
        "CLIPTRANSLATOR_TEST_TEXT": TEST_SENTENCE,
    }
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", SPEECH_SCRIPT],
        capture_output=True,
        timeout=60,
        env=environment,
    )
    return wav if result.returncode == 0 and wav.exists() else None


def self_test(model: str, device: str, compute_type: str) -> tuple[str, float | None]:
    audio = FfmpegAudio()
    with tempfile.TemporaryDirectory() as folder:
        spoken = synthesize_test_audio(Path(folder))
        if spoken is None:
            print("   (No hay voz de Windows disponible; se omite la prueba.)")
            return compute_type, None
        wav = audio.resample_for_speech(spoken, Path(folder) / "prueba16.wav")
        samples, duration = audio.load_mono(wav), audio.duration(wav)
    candidates = [compute_type] + (["int8"] if device == "cuda" and compute_type != "int8" else [])
    for candidate in candidates:
        print(f"   Probando Whisper {model} en {device} ({candidate})...")
        transcriber = FasterWhisperTranscriber(
            WhisperOptions(model=model, device=device, compute_type=candidate),
            whisper_models_dir(),
        )
        try:
            transcriber.transcribe(samples, "en")
            elapsed = float("inf")
            for _ in range(2):
                started = time.perf_counter()
                segments = transcriber.transcribe(samples, "en")
                elapsed = min(elapsed, time.perf_counter() - started)
        except (RuntimeError, ValueError) as error:
            print(f"   Falló: {error}")
            continue
        finally:
            transcriber.unload()
        text = " ".join(segment.text for segment in segments).lower().strip()
        print(f'   Resultado: "{text}"')
        if sum(word in text for word in TEST_KEYWORDS) >= len(TEST_KEYWORDS) - 1:
            return candidate, max(duration, WHISPER_WINDOW_SECONDS) / max(elapsed, 1e-6)
        print("   El resultado no es correcto con esta configuración.")
    raise RuntimeError("Whisper no funcionó con ninguna configuración.")


def collect_choices(
    console: Console, settings: Settings, report: SystemReport, recommendation: Recommendation
) -> Choices:
    whisper_model = choose_whisper(console, recommendation)
    print("\n2) Separación de voz (quita música y efectos antes de transcribir, 67 MB)")
    if not report.cuda_onnx:
        print("   Sin GPU tarda unos minutos por clip, pero suele mejorar la transcripción.")
    separation = console.confirm("   ¿Activarla?", recommendation.separation)
    target = choose_target_language(console, settings.translation.target_language)
    backend, translation_model = choose_translation(console, recommendation, report)
    if backend != "ollama":
        configure_api(console, settings, backend)
    return Choices(whisper_model, separation, target, backend, translation_model)


def run(assume_defaults: bool = False) -> int:
    console = Console(assume_defaults)
    store = SettingsStore()
    settings = store.load()
    print("=== ClipTranslator: configuración inicial ===")
    print("Analizando tu equipo...")
    report = scan(data_dir(), settings.translation.ollama_url)
    recommendation = recommend(report)
    print_report(report)
    if recommendation.warnings:
        print("\nAvisos:")
        for warning in recommendation.warnings:
            print(f"  - {warning}")
    choices = collect_choices(console, settings, report, recommendation)
    size = pending_download_gb(choices, report, settings.separation.model)
    model_label = choices.translation_model if choices.backend == "ollama" else choices.backend
    print(
        f"\nResumen: Whisper {choices.whisper_model} en {recommendation.device} "
        f"({recommendation.compute_type}), separación {yes_no(choices.separation)}, "
        f"traducción {model_label} → {choices.target_language}."
    )
    print(f"Hay que descargar unos {size:.1f} GB (tienes {report.disk_free_gb:.0f} GB libres).")
    if size > report.disk_free_gb * 0.9:
        print("No hay espacio suficiente en el disco. Libera espacio o elige modelos más pequeños.")
        return 1
    if not console.confirm("¿Continuar?"):
        return 1
    if not download_everything(console, choices, settings, report):
        return 1
    print("\nPrueba rápida de transcripción:")
    compute_type, speed = self_test(
        choices.whisper_model, recommendation.device, recommendation.compute_type
    )
    if compute_type != recommendation.compute_type:
        print(f"   Se usará {compute_type}, que sí funciona en tu GPU.")
    if speed:
        print(
            f"   Velocidad aproximada: {speed:.0f}x tiempo real (≈{5 / speed:.1f} min de "
            "transcripción por clip de 5 min, sin contar separación ni traducción)."
        )
    settings.transcription.model = choices.whisper_model
    settings.transcription.device = recommendation.device
    settings.transcription.compute_type = compute_type
    settings.separation.enabled = choices.separation
    settings.translation.target_language = choices.target_language
    settings.translation.backend = choices.backend
    if choices.backend == "ollama":
        settings.translation.ollama_model = choices.translation_model
    print(f"\nListo. Configuración guardada en {store.save(settings)}")
    print("Para cambiarla, vuelve a ejecutar el asistente (ClipTranslator.bat --setup).")
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="cliptranslator-setup")
    parser.add_argument("-y", "--yes", action="store_true", help="Aceptar las recomendaciones")
    args = parser.parse_args(argv)
    try:
        return run(args.yes)
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
