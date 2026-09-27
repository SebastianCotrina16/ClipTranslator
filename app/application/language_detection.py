from __future__ import annotations

from collections import defaultdict

import numpy as np

from app.application.ports import SpeechDetector, Transcriber
from app.domain.models import LanguageDetection

WINDOW_SECONDS = 30.0


def window_offsets(total: int, window: int, count: int = 3) -> list[int]:
    if total <= window or count == 1:
        return [0]
    last = total - window
    return sorted({round(last * index / (count - 1)) for index in range(count)})


class LanguageDetector:
    def __init__(
        self,
        transcriber: Transcriber,
        speech_detector: SpeechDetector,
        sample_rate: int,
        windows: int = 3,
    ) -> None:
        self._transcriber = transcriber
        self._speech_detector = speech_detector
        self._sample_rate = sample_rate
        self._windows = windows

    def detect(self, audio: np.ndarray) -> LanguageDetection:
        speech = self._speech_detector.speech_only(audio)
        size = int(WINDOW_SECONDS * self._sample_rate)
        offsets = window_offsets(len(speech), size, self._windows)
        scores: dict[str, float] = defaultdict(float)
        windows: list[tuple[float, str, float]] = []
        for offset in offsets:
            guess = self._transcriber.detect_language(speech[offset : offset + size])
            windows.append((offset / self._sample_rate, guess.language, guess.probability))
            for code, probability in guess.all_probabilities:
                scores[code] += probability
        ranked = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        best, score = ranked[0]
        top = [(code, value / len(offsets)) for code, value in ranked[:5]]
        return LanguageDetection(best, score / len(offsets), windows, top)
