from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config.store import models_dir, whisper_models_dir
from app.infrastructure.ffmpeg import FfmpegAudio
from app.infrastructure.llm.ollama import OllamaModel
from app.infrastructure.process import run_hidden, start_hidden
from app.infrastructure.separation.mdx import download_model, model_file
from app.infrastructure.system_probe import ollama_executable, ollama_models
from app.infrastructure.whisper import (
    FasterWhisperTranscriber,
    WhisperOptions,
    download_whisper_model,
    is_model_downloaded,
)

TEST_SENTENCE = (
    "Oh my god, look at this drawing. It is a cat riding a bicycle on the moon. "
    "That is the best thing I have seen today."
)
TEST_KEYWORDS = ("drawing", "cat", "bicycle", "moon")
WHISPER_WINDOW_SECONDS = 30.0
OLLAMA_START_SECONDS = 30
SPEECH_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$voice.SetOutputToWaveFile($env:CLIPTRANSLATOR_TEST_WAV);"
    "$voice.Speak($env:CLIPTRANSLATOR_TEST_TEXT);"
    "$voice.Dispose()"
)
WINGET_OLLAMA = [
    "winget",
    "install",
    "--id",
    "Ollama.Ollama",
    "-e",
    "--silent",
    "--accept-source-agreements",
    "--accept-package-agreements",
]

FractionCallback = Callable[[float], None]


class SetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelfTestResult:
    compute_type: str
    speed: float | None
    transcript: str


def whisper_ready(model: str) -> bool:
    return is_model_downloaded(model, whisper_models_dir())


def isolation_ready(model: str) -> bool:
    return model_file(model, models_dir()).exists()


def download_transcription_model(model: str, progress: FractionCallback | None = None) -> None:
    download_whisper_model(model, whisper_models_dir(), progress)


def download_isolation_model(model: str, progress: FractionCallback | None = None) -> None:
    download_model(model, models_dir(), progress)


def install_ollama() -> None:
    result = run_hidden(WINGET_OLLAMA, capture_output=True, text=True)
    if result.returncode != 0:
        raise SetupError("Ollama could not be installed with winget. Install it from ollama.com.")


def start_ollama(url: str) -> None:
    if ollama_models(url) is not None:
        return
    executable = ollama_executable()
    if executable is None:
        raise SetupError("Ollama is not installed.")
    start_hidden([executable, "serve"])
    for _ in range(OLLAMA_START_SECONDS):
        time.sleep(1)
        if ollama_models(url) is not None:
            return
    raise SetupError("Ollama did not start. Open it from the Start menu and try again.")


def pull_translation_model(
    model: str, url: str, progress: Callable[[float, str], None] | None = None
) -> None:
    OllamaModel(model, url).pull(progress)


def _synthesize_test_audio(folder: Path) -> Path | None:
    if sys.platform != "win32":
        return None
    wav = folder / "test.wav"
    environment = {
        **os.environ,
        "CLIPTRANSLATOR_TEST_WAV": str(wav),
        "CLIPTRANSLATOR_TEST_TEXT": TEST_SENTENCE,
    }
    result = run_hidden(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", SPEECH_SCRIPT],
        capture_output=True,
        timeout=60,
        env=environment,
    )
    return wav if result.returncode == 0 and wav.exists() else None


def run_speech_self_test(model: str, device: str, compute_type: str) -> SelfTestResult:
    audio = FfmpegAudio()
    with tempfile.TemporaryDirectory() as folder:
        spoken = _synthesize_test_audio(Path(folder))
        if spoken is None:
            return SelfTestResult(compute_type, None, "")
        wav = audio.resample_for_speech(spoken, Path(folder) / "test16.wav")
        samples, duration = audio.load_mono(wav), audio.duration(wav)
    candidates = [compute_type]
    if device == "cuda" and compute_type != "int8":
        candidates.append("int8")
    for candidate in candidates:
        result = _transcribe_test(model, device, candidate, samples, duration)
        if result is not None:
            return result
    raise SetupError("Whisper did not work with any configuration on this computer.")


def _transcribe_test(
    model: str, device: str, compute_type: str, samples: object, duration: float
) -> SelfTestResult | None:
    transcriber = FasterWhisperTranscriber(
        WhisperOptions(model=model, device=device, compute_type=compute_type),
        whisper_models_dir(),
    )
    try:
        transcriber.transcribe(samples, "en")
        elapsed = float("inf")
        for _ in range(2):
            started = time.perf_counter()
            segments = transcriber.transcribe(samples, "en")
            elapsed = min(elapsed, time.perf_counter() - started)
    except (RuntimeError, ValueError):
        return None
    finally:
        transcriber.unload()
    text = " ".join(segment.text for segment in segments).lower().strip()
    if sum(word in text for word in TEST_KEYWORDS) < len(TEST_KEYWORDS) - 1:
        return None
    speed = max(duration, WHISPER_WINDOW_SECONDS) / max(elapsed, 1e-6)
    return SelfTestResult(compute_type, speed, text)
