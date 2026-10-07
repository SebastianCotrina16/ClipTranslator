from __future__ import annotations

import re
from pathlib import Path

from app.domain.models import Cue
from app.domain.subtitle_formats import Track, to_srt, to_transcript, to_vtt, vocabulary_for
from app.domain.subtitles import CueRules

_UNSAFE_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SUBTITLE_ENCODING = "utf-8-sig"


def safe_stem(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARACTERS.sub("_", name).strip(" .")
    return cleaned or "clip"


def video_name(media: Path, subtitled: bool, without_music: bool) -> str:
    tags = [
        tag for tag, wanted in (("subtitled", subtitled), ("no-music", without_music)) if wanted
    ]
    return ".".join([safe_stem(media.stem), *tags, "mp4"])


class SubtitleFileWriter:
    def __init__(self, rules: CueRules | None = None) -> None:
        self.rules = rules or CueRules()

    def write(
        self,
        cues: list[Cue],
        media: Path,
        source_language: str,
        target_language: str,
        output_dir: Path | None = None,
        vtt: bool = False,
        extras: bool = True,
    ) -> list[Path]:
        folder = output_dir or media.parent
        folder.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(media.stem)
        vocabulary = vocabulary_for(target_language)
        tracks: list[tuple[Path, Track]] = [
            (folder / f"{stem}.{target_language}.srt", Track.TRANSLATION)
        ]
        if extras and source_language != target_language:
            tracks.append((folder / f"{stem}.{source_language}.srt", Track.ORIGINAL))
            tracks.append((folder / f"{stem}.{vocabulary.bilingual}.srt", Track.BILINGUAL))
        written: list[Path] = []
        for path, track in tracks:
            path.write_text(to_srt(cues, track, self.rules), encoding=SUBTITLE_ENCODING)
            written.append(path)
            if vtt:
                vtt_path = path.with_suffix(".vtt")
                vtt_path.write_text(to_vtt(cues, track, self.rules), encoding="utf-8")
                written.append(vtt_path)
        if not extras:
            return written
        transcript = folder / f"{stem}.{vocabulary.transcript}.txt"
        transcript.write_text(
            to_transcript(cues, source_language, target_language), encoding=SUBTITLE_ENCODING
        )
        written.append(transcript)
        return written
