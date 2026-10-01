from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import REVIEW_FLAGS, Flag, Segment, Unit
from app.domain.text import collapse_spaces, normalize_for_comparison

KNOWN_HALLUCINATIONS = (
    "subtitulos por la comunidad de amaraorg",
    "subtitulos realizados por la comunidad de amaraorg",
    "subtitulado por",
    "gracias por ver",
    "suscribete",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "subtitles by",
    "amaraorg",
    "untertitel im auftrag des zdf",
    "sous-titrage",
    "sous-titres",
    "societe radio-canada",
    "merci davoir regarde",
    "obrigado por assistir",
    "legendas pela comunidade amaraorg",
    "ご視聴ありがとうございました",
    "продолжение следует",
    "редактор субтитров",
    "字幕由amaraorg社区提供",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
)
NORMALIZED_HALLUCINATIONS = tuple(normalize_for_comparison(p) for p in KNOWN_HALLUCINATIONS)


@dataclass(frozen=True)
class QualityThresholds:
    no_speech_probability: float = 0.6
    low_average_logprob: float = -1.0
    high_compression_ratio: float = 2.4
    low_word_probability: float = 0.3
    min_repeats: int = 4


class HallucinationDetector:
    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self._limits = thresholds or QualityThresholds()

    def flag(self, segments: list[Segment]) -> list[Segment]:
        for segment in segments:
            kept = [flag for flag in segment.flags if flag in REVIEW_FLAGS]
            segment.flags = kept + self.flags_for(segment)
        return segments

    def flags_for(self, segment: Segment) -> list[str]:
        normalized = normalize_for_comparison(segment.text)
        if not normalized:
            return [Flag.EMPTY]
        limits = self._limits
        flags: list[str] = []
        low_confidence = segment.avg_logprob < limits.low_average_logprob
        if low_confidence and segment.no_speech_prob > limits.no_speech_probability:
            flags.append(Flag.NO_SPEECH)
        elif low_confidence or self._low_word_probability(segment):
            flags.append(Flag.LOW_CONFIDENCE)
        if segment.compression_ratio > limits.high_compression_ratio or self.is_repetitive(
            segment.text
        ):
            flags.append(Flag.REPETITIVE)
        if any(phrase in normalized for phrase in NORMALIZED_HALLUCINATIONS):
            flags.append(Flag.KNOWN_PHRASE)
        return flags

    def is_repetitive(self, text: str) -> bool:
        words = normalize_for_comparison(text).split()
        repeats_needed = self._limits.min_repeats
        if len(words) < repeats_needed:
            return False
        for size in range(1, 5):
            for start in range(len(words) - size * repeats_needed + 1):
                pattern = words[start : start + size]
                repeats, position = 1, start + size
                while words[position : position + size] == pattern:
                    repeats += 1
                    position += size
                if repeats >= repeats_needed and size * repeats >= max(4, len(words) // 2):
                    return True
        return False

    def _low_word_probability(self, segment: Segment) -> bool:
        if not segment.words:
            return False
        mean = sum(word.probability for word in segment.words) / len(segment.words)
        return mean < self._limits.low_word_probability


def apply_corrections(units: list[Unit], corrections: dict[str, str]) -> None:
    for unit in units:
        corrected = corrections.get(str(unit.id))
        if not corrected or collapse_spaces(corrected) == collapse_spaces(unit.text):
            continue
        unit.asr_text, unit.text = unit.text, corrected
        if normalize_for_comparison(corrected) != normalize_for_comparison(unit.asr_text):
            unit.flags = sorted({*unit.flags, Flag.CORRECTED})
