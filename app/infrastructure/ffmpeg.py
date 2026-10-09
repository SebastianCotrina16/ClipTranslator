from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from functools import cache, lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from app.domain.audio_leveling import Leveling
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
REENCODE = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium"]
CLEAN_AUDIO = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
PREVIEW_AUDIO_SECONDS = 10.0
LOUDNESS_RATE = 8_000
MEASURED_CACHE = 16
MEASURED_FIELDS = {
    "measured_I": "input_i",
    "measured_TP": "input_tp",
    "measured_LRA": "input_lra",
    "measured_thresh": "input_thresh",
    "offset": "target_offset",
}
JSON_BLOCK = re.compile(r"\{[^{}]*\}")
VIDEO_SIZE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})")
VIDEO_RATE = re.compile(r"([\d.]+) (?:fps|tbr)")
DURATION = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")
FrameFilter = Callable[[int, np.ndarray], object]


def video_info(media: Path) -> tuple[int, int, float, float]:
    command = [ffmpeg_executable(), "-hide_banner", "-i", str(media)]
    details = run_hidden(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    report = details.stderr or ""
    size, rate, length = (
        VIDEO_SIZE.search(report),
        VIDEO_RATE.search(report),
        DURATION.search(report),
    )
    if size is None or rate is None:
        raise FfmpegError(f"Could not read the video size of {media.name}.")
    hours, minutes, seconds = (float(part) for part in length.groups()) if length else (0, 0, 0)
    return (
        int(size.group(1)),
        int(size.group(2)),
        float(rate.group(1)),
        hours * 3600 + minutes * 60 + seconds,
    )


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
    leveling: Leveling | None = None,
    frame_filter: FrameFilter | None = None,
) -> Path:
    if frame_filter is not None:
        audio_filter = loudness_filter(audio or media, leveling) if leveling else None
        draw = (subtitles, style or SubtitleStyle()) if subtitles is not None else None
        return _render_frames(media, output, draw, audio, audio_filter, progress, frame_filter)
    if subtitles is not None:
        video = ["-vf", subtitle_filter(subtitles, style or SubtitleStyle()), *REENCODE]
    else:
        video = ["-c:v", "copy"]
    audio_filter = loudness_filter(audio or media, leveling) if leveling else None
    try:
        command = _video_command(media, output, video, audio, audio_filter)
        _run_with_progress(command, duration, progress)
    except FfmpegError:
        if subtitles is not None:
            raise
        command = _video_command(media, output, REENCODE, audio, audio_filter)
        _run_with_progress(command, duration, progress)
    return output


def _video_command(
    media: Path, output: Path, video: list[str], audio: Path | None, leveling: str | None
) -> list[str]:
    command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(media)]
    if audio is not None:
        command += ["-i", str(audio)]
    if audio is None and leveling is None:
        command += [*video, "-c:a", "copy"]
    else:
        source = "1:a:0" if audio is not None else "0:a:0"
        command += ["-map", "0:v:0", "-map", source, *video]
        command += ["-af", leveling] if leveling else []
        command += CLEAN_AUDIO
    return [*command, "-progress", "pipe:1", "-nostats", str(output)]


def _render_frames(
    media: Path,
    output: Path,
    subtitles: tuple[Path, SubtitleStyle] | None,
    audio: Path | None,
    audio_filter: str | None,
    progress: Callable[[float], None] | None,
    frame_filter: FrameFilter,
) -> Path:
    width, height, fps, duration = video_info(media)
    total = max(int(duration * fps), 1)
    reader_command = [ffmpeg_executable(), "-v", "error", "-i", str(media), "-f", "rawvideo"]
    reader_command += ["-pix_fmt", "bgr24", "-"]
    writer_command = [ffmpeg_executable(), "-hide_banner", "-loglevel", "error", "-y"]
    writer_command += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}"]
    writer_command += ["-r", f"{fps}", "-i", "-", "-i", str(audio or media), "-map", "0:v:0"]
    writer_command += ["-map", "1:a:0?"]
    if subtitles is not None:
        writer_command += ["-vf", subtitle_filter(*subtitles)]
    writer_command += REENCODE
    if audio is not None or audio_filter:
        writer_command += ["-af", audio_filter] if audio_filter else []
        writer_command += CLEAN_AUDIO
    else:
        writer_command += ["-c:a", "copy"]
    writer_command += ["-shortest", str(output)]
    size = width * height * 3
    with tempfile.TemporaryFile() as errors:
        reader = subprocess.Popen(
            reader_command, stdout=subprocess.PIPE, creationflags=HIDDEN_WINDOW
        )
        writer = subprocess.Popen(
            writer_command, stdin=subprocess.PIPE, stderr=errors, creationflags=HIDDEN_WINDOW
        )
        index = 0
        try:
            while reader.stdout is not None and writer.stdin is not None:
                raw = reader.stdout.read(size)
                if len(raw) < size:
                    break
                frame = np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
                frame_filter(index, frame)
                writer.stdin.write(frame.tobytes())
                index += 1
                if progress and index % 10 == 0:
                    progress(min(index / total, 1.0))
        except BrokenPipeError:
            pass
        finally:
            reader.kill()
            reader.wait()
            if writer.stdin is not None:
                writer.stdin.close()
            writer.wait()
        if writer.returncode != 0:
            errors.seek(0)
            detail = errors.read().decode("utf-8", "replace").strip()
            raise FfmpegError(f"ffmpeg failed: {detail[-500:]}")
    if progress:
        progress(1.0)
    return output


def loudness_filter(source: Path, leveling: Leveling) -> str:
    stat = source.stat()
    measured = _measured(str(source), stat.st_size, stat.st_mtime, leveling)
    chain = [leveling.compressor] if leveling.compressor else []
    values = "".join(f":{name}={measured[key]}" for name, key in MEASURED_FIELDS.items())
    chain.append(f"loudnorm={leveling.loudness}{values if measured else ''}")
    return ",".join(chain)


@lru_cache(maxsize=MEASURED_CACHE)
def _measured(source: str, size: int, modified: float, leveling: Leveling) -> dict[str, str]:
    return measure_loudness(Path(source), leveling.compressor, leveling.loudness) or {}


def measure_loudness(
    source: Path, before: str = "", loudness: str = Leveling().loudness
) -> dict[str, str] | None:
    meter = f"loudnorm={loudness}:print_format=json"
    command = [ffmpeg_executable(), "-hide_banner", "-nostats", "-i", str(source), "-vn"]
    command += ["-af", f"{before},{meter}" if before else meter, "-f", "null", "-"]
    result = run_hidden(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    blocks = JSON_BLOCK.findall(result.stderr or "")
    if result.returncode != 0 or not blocks:
        return None
    try:
        report = json.loads(blocks[-1])
        measured = {key: str(report[key]) for key in MEASURED_FIELDS.values()}
    except (json.JSONDecodeError, KeyError):
        return None
    if not all(math.isfinite(float(value)) for value in measured.values()):
        return None
    return measured


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


def loudest_moment(source: Path, seconds: float = PREVIEW_AUDIO_SECONDS) -> float:
    command = [ffmpeg_executable(), "-v", "error", "-i", str(source), "-vn", "-ac", "1"]
    command += ["-ar", str(LOUDNESS_RATE), "-f", "f32le", "-"]
    result = run_hidden(command, capture_output=True)
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    window = int(seconds * LOUDNESS_RATE)
    if result.returncode != 0 or len(samples) <= window:
        return 0.0
    energy = np.concatenate([[0.0], np.cumsum(samples.astype(np.float64) ** 2)])
    totals = energy[window:] - energy[:-window]
    return float(np.argmax(totals[:: LOUDNESS_RATE // 10])) / 10


def render_audio_preview(
    source: Path,
    start: float,
    leveling: Leveling | None,
    output: Path,
    seconds: float = PREVIEW_AUDIO_SECONDS,
) -> Path:
    audio_filter = ["-af", loudness_filter(source, leveling)] if leveling else []
    run_ffmpeg(
        [
            "-ss",
            f"{max(start - 2.0, 0.0):.3f}",
            "-t",
            f"{seconds + 2.0:.3f}",
            "-i",
            str(source),
            "-vn",
            *audio_filter,
            "-ss",
            "2" if start >= 2.0 else f"{start:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(output),
        ]
    )
    return output
