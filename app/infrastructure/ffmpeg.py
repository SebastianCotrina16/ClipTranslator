from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

from app.domain.subtitle_formats import timestamp
from app.domain.subtitle_style import SubtitleStyle, force_style
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


PREVIEW_SECONDS = 60.0
AUDIO_ONLY_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
PROGRESS_KEYS = ("out_time_us=", "out_time_ms=")
REENCODE = ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]
CLEAN_AUDIO = ["-c:a", "aac", "-b:a", "192k"]


def has_video(media: Path) -> bool:
    return media.suffix.lower() not in AUDIO_ONLY_SUFFIXES


def burn_subtitles(
    media: Path,
    subtitles: Path,
    output: Path,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
    style: SubtitleStyle | None = None,
) -> Path:
    return render_video(media, output, subtitles, style, None, duration, progress)


def render_video(
    media: Path,
    output: Path,
    subtitles: Path | None = None,
    style: SubtitleStyle | None = None,
    audio: Path | None = None,
    duration: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    if subtitles is not None:
        video = ["-vf", subtitle_filter(subtitles, style or SubtitleStyle()), *REENCODE]
    else:
        video = ["-c:v", "copy"]
    try:
        _run_with_progress(_video_command(media, output, video, audio), duration, progress)
    except FfmpegError:
        if subtitles is not None:
            raise
        _run_with_progress(_video_command(media, output, REENCODE, audio), duration, progress)
    return output


def _video_command(media: Path, output: Path, video: list[str], audio: Path | None) -> list[str]:
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(media)]
    if audio is None:
        command += [*video, "-c:a", "copy"]
    else:
        command += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", *video, *CLEAN_AUDIO]
    return [*command, "-progress", "pipe:1", "-nostats", str(output)]


def _run_with_progress(
    command: list[str],
    duration: float | None,
    progress: Callable[[float], None] | None,
) -> None:
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


def subtitle_filter(subtitles: Path, style: SubtitleStyle) -> str:
    escaped = subtitles.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{escaped}':force_style='{force_style(style)}'"


def render_preview(
    media: Path, seconds: float, text: str, style: SubtitleStyle | None, output: Path
) -> Path:
    overlay: list[str] = []
    if style is not None:
        subtitles = output.with_suffix(".srt")
        cue = f"1\n{timestamp(0.0)} --> {timestamp(PREVIEW_SECONDS)}\n{text}\n"
        subtitles.write_text(cue, encoding="utf-8")
        overlay = ["-vf", subtitle_filter(subtitles, style)]
    run_ffmpeg(
        [
            "-ss",
            f"{max(seconds, 0.0):.3f}",
            "-i",
            str(media),
            "-frames:v",
            "1",
            *overlay,
            "-update",
            "1",
            str(output),
        ]
    )
    return output


def _progress_seconds(line: str) -> float | None:
    for key in PROGRESS_KEYS:
        if line.startswith(key):
            try:
                return int(line[len(key) :].strip()) / 1_000_000
            except ValueError:
                return None
    return None
