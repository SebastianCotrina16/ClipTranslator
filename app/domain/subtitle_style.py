from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
FONT_NAME = "Segoe UI"
BOX_PADDING = 5
OUTLINE_WIDTH = 2
EDGE_MARGIN = 28

TEXT_COLORS = {
    "White": "#FFFFFF",
    "Yellow": "#FFE14D",
    "Cyan": "#5CE1FF",
    "Green": "#8CFF7A",
}
FONT_SIZES = {
    "Small": 16,
    "Medium": 20,
    "Large": 24,
    "Extra large": 28,
}
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 48


class Background(StrEnum):
    OUTLINE = "outline"
    BOX = "box"


class Position(StrEnum):
    BOTTOM = "bottom"
    TOP = "top"


ALIGNMENTS = {Position.BOTTOM: 2, Position.TOP: 6}


@dataclass(frozen=True)
class SubtitleStyle:
    text_color: str = "#FFFFFF"
    background: Background = Background.BOX
    box_opacity: int = 60
    font_size: int = 20
    position: Position = Position.BOTTOM

    @classmethod
    def from_values(
        cls,
        text_color: str,
        background: str,
        box_opacity: int,
        font_size: int,
        position: str,
    ) -> SubtitleStyle:
        default = cls()
        return cls(
            text_color=text_color.upper() if HEX_COLOR.match(text_color) else default.text_color,
            background=_choice(Background, background, default.background),
            box_opacity=min(max(box_opacity, 0), 100),
            font_size=min(max(font_size, MIN_FONT_SIZE), MAX_FONT_SIZE),
            position=_choice(Position, position, default.position),
        )


def _choice[T: StrEnum](kind: type[T], value: str, default: T) -> T:
    try:
        return kind(value)
    except ValueError:
        return default


def ass_color(hex_color: str, opacity: int = 100) -> str:
    red, green, blue = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    alpha = round((100 - opacity) * 255 / 100)
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def force_style(style: SubtitleStyle) -> str:
    fields = {
        "FontName": FONT_NAME,
        "FontSize": str(style.font_size),
        "Bold": "1",
        "PrimaryColour": ass_color(style.text_color),
        "Alignment": str(ALIGNMENTS[style.position]),
        "MarginV": str(EDGE_MARGIN),
        "Shadow": "0",
    }
    if style.background is Background.BOX:
        box = ass_color("#000000", style.box_opacity)
        fields |= {
            "BorderStyle": "3",
            "Outline": str(BOX_PADDING),
            "OutlineColour": box,
            "BackColour": box,
        }
    else:
        fields |= {
            "BorderStyle": "1",
            "Outline": str(OUTLINE_WIDTH),
            "OutlineColour": ass_color("#000000"),
        }
    return ",".join(f"{key}={value}" for key, value in fields.items())
