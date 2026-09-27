from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

from app.infrastructure.process import HIDDEN_WINDOW, run_hidden

SPEECH_SAMPLE_RATE = 16_000
SEPARATION_SAMPLE_RATE = 44_100


class FfmpegError(RuntimeError):
    pass


@cache
def ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise FfmpegError("ffmpeg was not found.") from None
        return executable


def run_ffmpeg(arguments: list[str]) -> None:
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", *arguments]
    result = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise FfmpegError(f"ffmpeg failed: {result.stderr.strip()}")


class FfmpegAudio:
    sample_rate = SPEECH_SAMPLE_RATE
    separation_sample_rate = SEPARATION_SAMPLE_RATE

    def extract(self, media: Path, output: Path, sample_rate: int, channels: int) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            [
                "-i",
                str(media),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )
        return output

    def resample_for_speech(self, source: Path, output: Path) -> Path:
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                str(SPEECH_SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )
        return output

    def load_mono(self, path: Path) -> np.ndarray:
        samples, _ = sf.read(path, dtype="float32", always_2d=True)
        return samples.mean(axis=1)

    def duration(self, path: Path) -> float:
        info = sf.info(path)
        return info.frames / info.samplerate


BURNED_SUBTITLE_STYLE = "FontName=Segoe UI,FontSize=20,Bold=1,Outline=2,Shadow=0,MarginV=28"
AUDIO_ONLY_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
PROGRESS_KEYS = ("out_time_us=", "out_time_ms=")


def has_video(media: Path) -> bool:
    return media.suffix.lower() not in AUDIO_ONLY_SUFFIXES


def burn_subtitles(
    media: Path,
    subtitles: Path,
    output: Path,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    escaped = subtitles.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    command = [
        ffmpeg_executable(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(media),
        "-vf",
        f"subtitles='{escaped}':force_style='{BURNED_SUBTITLE_STYLE}'",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=errors, text=True, creationflags=HIDDEN_WINDOW
        )
        output_stream = process.stdout
        if output_stream is not None:
            for line in output_stream:
                seconds = _progress_seconds(line)
                if seconds is not None and progress and duration:
                    progress(min(seconds / duration, 1.0))
        process.wait()
        if process.returncode != 0:
            errors.seek(0)
            detail = errors.read().decode("utf-8", "replace").strip()
            raise FfmpegError(f"ffmpeg failed: {detail[-500:]}")
    if progress:
        progress(1.0)
    return output


def _progress_seconds(line: str) -> float | None:
    for key in PROGRESS_KEYS:
        if line.startswith(key):
            try:
                return int(line[len(key) :].strip()) / 1_000_000
            except ValueError:
                return None
    return None
