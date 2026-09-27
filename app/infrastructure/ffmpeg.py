from __future__ import annotations

import shutil
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

from app.infrastructure.process import run_hidden

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


def burn_subtitles(media: Path, subtitles: Path, output: Path) -> Path:
    escaped = subtitles.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    run_ffmpeg(
        [
            "-i",
            str(media),
            "-vf",
            f"subtitles='{escaped}'",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-c:a",
            "copy",
            str(output),
        ]
    )
    return output
