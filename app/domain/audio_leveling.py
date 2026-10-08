from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

QUIETEST_TARGET = -20
LOUDEST_TARGET = -10
RECOMMENDED_TARGET = -14


class Tame(StrEnum):
    OFF = "off"
    LIGHT = "light"
    MEDIUM = "medium"
    STRONG = "strong"


COMPRESSORS = {
    Tame.OFF: "",
    Tame.LIGHT: "acompressor=threshold=-24dB:ratio=3:attack=5:release=200:makeup=1",
    Tame.MEDIUM: "acompressor=threshold=-28dB:ratio=4:attack=4:release=200:makeup=1",
    Tame.STRONG: "acompressor=threshold=-32dB:ratio=6:attack=3:release=250:makeup=1",
}
TAME_CHOICES = {
    Tame.OFF: ("Off", "Screams and laughs keep their full strength."),
    Tame.LIGHT: ("Light (recommended)", "Softens screams a little. Sounds natural."),
    Tame.MEDIUM: ("Medium", "Screams are clearly softer than they were."),
    Tame.STRONG: (
        "Strong",
        "Screams and normal talking end up almost as loud. Can sound flat.",
    ),
}
TARGET_HINTS = (
    (-17, "Quiet, like TV"),
    (-16, "Podcasts and Spotify"),
    (-13, "YouTube, TikTok, Instagram (recommended)"),
    (-11, "Loud"),
    (LOUDEST_TARGET, "Very loud, can sound harsh"),
)


def target_hint(target: int) -> str:
    return next(hint for limit, hint in TARGET_HINTS if target <= limit)


@dataclass(frozen=True)
class Leveling:
    target: int = RECOMMENDED_TARGET
    tame: Tame = Tame.LIGHT

    @classmethod
    def from_values(cls, target: int, tame: str) -> Leveling:
        try:
            chosen = Tame(tame)
        except ValueError:
            chosen = Tame.LIGHT
        return cls(min(max(target, QUIETEST_TARGET), LOUDEST_TARGET), chosen)

    @property
    def compressor(self) -> str:
        return COMPRESSORS[self.tame]

    @property
    def loudness(self) -> str:
        return f"I={self.target}:TP=-1.5:LRA=11"
