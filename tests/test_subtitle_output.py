from __future__ import annotations

from pathlib import Path

from app.domain.models import Cue
from app.domain.subtitle_formats import Track, clock, timestamp, to_srt, to_transcript, to_vtt
from app.infrastructure.subtitle_files import SubtitleFileWriter, safe_stem


def sample_cues() -> list[Cue]:
    return [
        Cue(1, 1.0, 2.5, "Is that a cat?", "¿Es un gato?", 0),
        Cue(
            2,
            3.0,
            6.0,
            "This is the worst drawing I have ever seen in my life",
            "Este es el peor dibujo que he visto en mi vida",
            1,
        ),
        Cue(3, 7.0, 8.0, "untranslated", "", 2, ["sin_traduccion"]),
    ]


def test_timestamp() -> None:
    assert timestamp(0) == "00:00:00,000"
    assert timestamp(3661.5) == "01:01:01,500"
    assert timestamp(59.9996) == "00:01:00,000"
    assert timestamp(1.25, ".") == "00:00:01.250"


def test_clock() -> None:
    assert clock(190.4) == "3:10"
    assert clock(5) == "0:05"
    assert clock(3725) == "1:02:05"


def test_translation_srt_wraps_and_skips_empty() -> None:
    srt = to_srt(sample_cues(), Track.TRANSLATION)
    assert srt.startswith("1\n00:00:01,000 --> 00:00:02,500\n¿Es un gato?\n")
    assert "Este es el peor dibujo\nque he visto en mi vida" in srt
    assert "\n3\n" not in srt


def test_original_srt_keeps_every_cue() -> None:
    assert "\n3\n00:00:07,000 --> 00:00:08,000\nuntranslated\n" in to_srt(
        sample_cues(), Track.ORIGINAL
    )


def test_bilingual_srt_has_both_languages() -> None:
    assert "Is that a cat?\n¿Es un gato?" in to_srt(sample_cues(), Track.BILINGUAL)


def test_vtt_header_and_dot_times() -> None:
    vtt = to_vtt(sample_cues())
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:01.000 --> 00:00:02.500" in vtt


def test_transcript_merges_cues_of_the_same_sentence() -> None:
    cues = [
        Cue(1, 190.0, 195.0, "Hi, my name", "Hola, me llamo", 0),
        Cue(2, 195.1, 210.0, "is Juan", "Juan", 0),
        Cue(3, 211.0, 212.0, "ok", "", 1, ["sin_traduccion"]),
    ]
    text = to_transcript(cues, "en")
    assert "[3:10 - 3:30]\n  EN: Hi, my name is Juan\n  ES: Hola, me llamo Juan" in text
    assert "ES: (sin traducción)" in text
    assert "revisar: sin_traduccion" in text


def test_transcript_uses_english_labels_for_other_targets() -> None:
    cues = [
        Cue(1, 190.0, 210.0, "Oi, meu nome é Juan", "Hi, my name is Juan", 0),
        Cue(2, 211.0, 212.0, "ok", "", 1, ["sin_traduccion"]),
    ]
    text = to_transcript(cues, "pt", "en")
    assert "[3:10 - 3:30]\n  PT: Oi, meu nome é Juan\n  EN: Hi, my name is Juan" in text
    assert "EN: (not translated)" in text
    assert "check: sin_traduccion" in text


def test_writer_names_files_for_spanish_target(tmp_path: Path) -> None:
    files = SubtitleFileWriter().write(sample_cues(), tmp_path / "clip.mp4", "en", "es")
    assert [f.name for f in files] == [
        "clip.es.srt",
        "clip.en.srt",
        "clip.bilingue.srt",
        "clip.transcripcion.txt",
    ]
    assert files[0].read_bytes().startswith(b"\xef\xbb\xbf")


def test_writer_names_files_for_english_target(tmp_path: Path) -> None:
    files = SubtitleFileWriter().write(sample_cues(), tmp_path / "clip.mp4", "pt", "en")
    assert [f.name for f in files] == [
        "clip.en.srt",
        "clip.pt.srt",
        "clip.bilingual.srt",
        "clip.transcript.txt",
    ]


def test_writer_same_language_writes_only_target_and_transcript(tmp_path: Path) -> None:
    files = SubtitleFileWriter().write(sample_cues(), tmp_path / "clip.mp4", "es", "es")
    assert [f.name for f in files] == ["clip.es.srt", "clip.transcripcion.txt"]


def test_safe_stem_removes_path_and_reserved_characters() -> None:
    assert safe_stem('a<b>:c"d|e?f*g') == "a_b__c_d_e_f_g"
    assert safe_stem("..") == "clip"
