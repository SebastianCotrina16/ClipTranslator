from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageDraw, ImageFont

from app.domain.screen_prompts import Detection, PromptStyle, prompt_key

FONT_FILE = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Nunito.ttf"
FONT_WEIGHT = 700
SEARCH = 160
NEAR_SEARCH = 24
MAX_DIFF = 14.0
TRACK_SECONDS = 1.0
MAX_SPOTS = 6
SAME_SPOT = 10
BUBBLE_DISTANCE = 38
TEXT_SHARE = 0.44
LINE_SPACING = 1.3
RADIUS = 9
MIN_PADDING = 8
WIDEN_MARGIN = 120
EDGE_MARGIN = 90
MIN_FONT = 8
REVEAL_SECONDS = 1.0
REVEAL_REACH_X = 3
REVEAL_REACH_Y = 6
MIN_REVEAL_MATCH = 0.9
MIN_OPACITY = 0.05
FULL_OPACITY = 0.9
MIN_CONTRAST = 15.0
BEHIND_RING = 4


@dataclass(frozen=True)
class Placement:
    text: str
    box: tuple[int, int, int, int]


@cache
def nunito(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_FILE), size)
    font.set_variation_by_axes([FONT_WEIGHT])
    return font


def search(frame: np.ndarray, box: tuple[int, int, int, int], template: np.ndarray, reach: int):
    x0, y0, x1, y1 = box
    height, width = template.shape
    top, bottom = max(y0 - reach, 0), min(y1 + reach, frame.shape[0])
    strip = frame[top:bottom, x0 : x0 + width].mean(axis=2, dtype=np.float32)
    if strip.shape[0] < height or strip.shape[1] < width:
        return None
    windows = sliding_window_view(strip, (height, width))[:, 0]
    scores = np.abs(windows - template).mean(axis=(1, 2))
    best = int(np.argmin(scores))
    if scores[best] > MAX_DIFF:
        return None
    shift = top + best - y0
    return (x0, y0 + shift, x1, y1 + shift)


def locate(frame, box, template, near=None):
    if near is not None:
        moved = (box[0], near, box[2], near + box[3] - box[1])
        found = search(frame, moved, template, NEAR_SEARCH)
        if found is not None:
            return found
    return search(frame, box, template, SEARCH)


def reveal_match(frame: np.ndarray, box, template: np.ndarray):
    x0, y0, x1, y1 = box
    height, width = template.shape
    if template.std() < MIN_CONTRAST:
        return None
    top, left = max(y0 - REVEAL_REACH_Y, 0), max(x0 - REVEAL_REACH_X, 0)
    bottom = min(y1 + REVEAL_REACH_Y, frame.shape[0])
    right = min(x0 + width + REVEAL_REACH_X, frame.shape[1])
    area = frame[top:bottom, left:right].mean(axis=2, dtype=np.float32)
    if area.shape[0] < height or area.shape[1] < width:
        return None
    scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, (dx, dy) = cv2.minMaxLoc(scores)
    if best < MIN_REVEAL_MATCH:
        return None
    found = area[dy : dy + height, dx : dx + width]
    spread = template - template.mean()
    opacity = float(((found - found.mean()) * spread).sum() / (spread**2).sum())
    shifted = (left + dx, top + dy, left + dx + (x1 - x0), top + dy + (y1 - y0))
    return shifted, min(max(opacity, 0.0), 1.0)


def card_colors(frame: np.ndarray, box):
    x0, y0, x1, y1 = box
    above = frame[max(y0 - 4, 0), x0:x1]
    below = frame[min(y1 + 4, frame.shape[0] - 1), x0:x1]
    ring = np.concatenate([above, below]).astype(np.int16)
    bright = ring[ring.mean(axis=1) > 150]
    if len(bright) < 5:
        return None, None
    background = np.median(bright, axis=0)
    inside = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.int16)
    spread = inside.max(axis=1) - inside.min(axis=1)
    dark = inside[(inside.mean(axis=1) < 128) & (spread < 40)]
    ink = np.median(dark, axis=0) if len(dark) > 10 else np.array([60, 60, 60])
    return background, ink


def card_bounds(frame: np.ndarray, box, background):
    x0, y0, x1, y1 = box
    height, width = frame.shape[:2]
    middle_row, middle_column = (y0 + y1) // 2, (x0 + x1) // 2
    row = np.abs(frame[middle_row].astype(np.int16) - background).max(axis=1) < BUBBLE_DISTANCE
    column = (
        np.abs(frame[:, middle_column].astype(np.int16) - background).max(axis=1) < BUBBLE_DISTANCE
    )
    left, right, top, bottom = x0, x1, y0, y1
    while left > 0 and row[left - 1]:
        left -= 1
    while right < width - 1 and row[right + 1]:
        right += 1
    while top > 0 and column[top - 1]:
        top -= 1
    while bottom < height - 1 and column[bottom + 1]:
        bottom += 1
    return left, top, right, bottom


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, anchor="lm")
    return right - left


def wrap(draw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if text_width(draw, trial, font) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(draw, text: str, size: int, width: int, max_lines: int):
    while size > MIN_FONT:
        font = nunito(size)
        lines = wrap(draw, text, font, width)
        widest = max(text_width(draw, line, font) for line in lines)
        if len(lines) <= max_lines and widest <= width:
            return font, lines, widest
        size -= 1
    font = nunito(MIN_FONT)
    return font, wrap(draw, text, font, width), width


class PromptRenderer:
    def __init__(
        self,
        detections: list[Detection],
        templates: list[np.ndarray],
        translations: dict[str, str],
        fps: float,
        style: PromptStyle,
    ) -> None:
        self.style = style
        self.fps = fps
        self.translations = translations
        usable = [
            (detection, template)
            for detection, template in zip(detections, templates, strict=True)
            if translations.get(prompt_key(detection.text))
        ]
        self._by_frame: dict[int, list[tuple[Detection, np.ndarray]]] = {}
        for detection, template in usable:
            self._by_frame.setdefault(detection.frame, []).append((detection, template))
        self._scanned = sorted(self._by_frame)
        boxes = [detection.box for detection, _ in usable]
        self._center = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2 if boxes else 0
        self._min_x = int(min(b[0] for b in boxes) - WIDEN_MARGIN) if boxes else 0
        self._last_seen: dict[int, int] = {}
        self._probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    @property
    def active(self) -> bool:
        return bool(self._scanned)

    def apply(self, index: int, frame: np.ndarray) -> list[Placement]:
        placed: list[Placement] = []
        for detection, template in self._candidates(index):
            track = id(template)
            where = locate(frame, detection.box, template, self._last_seen.get(track))
            opacity = 1.0
            if where is None and self._may_be_appearing(index, detection):
                revealed = reveal_match(frame, detection.box, template)
                if revealed is not None:
                    where, opacity = revealed
            if where is None or opacity < MIN_OPACITY:
                self._last_seen.pop(track, None)
                continue
            if opacity >= FULL_OPACITY:
                self._last_seen[track] = where[1]
            height = where[3] - where[1]
            if any(
                abs(where[1] - p.box[1]) < height and abs(where[0] - p.box[0]) < 40 for p in placed
            ):
                continue
            if where[1] < 4 or where[3] > frame.shape[0] - 5:
                continue
            translation = self.translations[prompt_key(detection.text)]
            fading = opacity < FULL_OPACITY and len(detection.look) == 10
            look = detection.look if fading else None
            drawn = self._draw(frame, where, translation, detection.lines, look, opacity)
            if drawn:
                placed.append(Placement(translation, where))
        return placed

    def _may_be_appearing(self, index: int, detection: Detection) -> bool:
        window = self.fps * REVEAL_SECONDS
        return detection.frame - window <= index <= detection.frame + window

    def _candidates(self, index: int):
        reach = int(self.fps * TRACK_SECONDS)
        low = np.searchsorted(self._scanned, index - reach)
        high = np.searchsorted(self._scanned, index + reach, side="right")
        nearby = sorted(self._scanned[low:high], key=lambda scanned: abs(scanned - index))
        chosen: dict[str, list[int]] = {}
        for scanned in nearby:
            for detection, template in self._by_frame[scanned]:
                spots = chosen.setdefault(prompt_key(detection.text), [])
                top = detection.box[1]
                if len(spots) >= MAX_SPOTS or any(abs(top - y) < SAME_SPOT for y in spots):
                    continue
                spots.append(top)
                yield detection, template

    def _draw(
        self,
        frame: np.ndarray,
        box,
        translation: str,
        lines_before: int,
        look: tuple[int, ...] | None = None,
        opacity: float = 1.0,
    ) -> bool:
        x0, y0, x1, y1 = box
        if look:
            background, ink = np.array(look[0:3], float), np.array(look[3:6], float)
            left, top = x0 - look[6], y0 - look[7]
            right, bottom = x1 + look[8], y1 + look[9]
        else:
            background, ink = card_colors(frame, box)
            if background is None:
                return False
            left, top, right, bottom = card_bounds(frame, box, background)
        padding = max(x0 - left, MIN_PADDING)
        if lines_before > 1:
            pitch = (y1 - y0) / lines_before
            size = int(round(pitch * 0.95))
        else:
            size = int(round((bottom - top) * TEXT_SHARE))
            pitch = size * LINE_SPACING
        on_right = (left + right) / 2 > self._center
        new_left, new_right = left, right
        if self.style is PromptStyle.WIDEN:
            needed = self._natural_width(
                translation, size, right - left - 2 * padding, lines_before
            )
            needed += 2 * padding
            if needed > right - left:
                if on_right:
                    new_left = max(right - needed, self._min_x)
                else:
                    new_right = min(left + needed, frame.shape[1] - EDGE_MARGIN)
        room = (new_right - new_left) - 2 * padding
        font, lines, used = fit_text(self._probe, translation, size, room, max(lines_before, 1))
        a0, a1 = max(new_left - 2, 0), min(new_right + 2, frame.shape[1])
        b0, b1 = max(top - 2, 0), min(bottom + 2, frame.shape[0])
        region = frame[b0:b1, a0:a1]
        tile = Image.fromarray(region[:, :, ::-1].copy())
        draw = ImageDraw.Draw(tile)
        fill = tuple(int(value) for value in background[::-1])
        if look:
            draw.rounded_rectangle(
                [new_left - a0, top - b0, new_right - a0, bottom - b0], radius=RADIUS, fill=fill
            )
        elif (new_left, new_right) != (left, right):
            clipped_top, clipped_bottom = y0 - top < 4, bottom - y1 < 4
            box_top = top - b0 - (RADIUS if clipped_top else 0)
            box_bottom = bottom - b0 + (RADIUS if clipped_bottom else 0)
            draw.rounded_rectangle(
                [new_left - a0, box_top, new_right - a0, box_bottom], radius=RADIUS, fill=fill
            )
            draw.rectangle(
                [
                    max(left - a0 - 3, new_left - a0 + RADIUS),
                    box_top + 2,
                    min(right - a0, new_right - a0) - RADIUS,
                    box_bottom - 2,
                ],
                fill=fill,
            )
        else:
            cover_left = x0 - 3 if lines_before == 1 else left + 4
            cover_right = max(x0 + used + 6, x1 + 3) if lines_before == 1 else right - 4
            draw.rectangle([cover_left - a0, y0 - b0 - 3, cover_right - a0, y1 - b0 + 3], fill=fill)
        color = tuple(int(value) for value in ink[::-1])
        first = (y0 + y1) / 2 - pitch * (len(lines) - 1) / 2
        for number, line in enumerate(lines):
            y = first + number * pitch - b0
            if lines_before > 1:
                draw.text(
                    ((new_left + new_right) / 2 - a0, y), line, font=font, fill=color, anchor="mm"
                )
            else:
                draw.text((new_left + padding - a0, y), line, font=font, fill=color, anchor="lm")
        painted = np.array(tile)[:, :, ::-1]
        if not look:
            region[:] = painted
            return True
        shape = Image.new("L", tile.size, 0)
        ImageDraw.Draw(shape).rounded_rectangle(
            [new_left - a0, top - b0, new_right - a0, bottom - b0], radius=RADIUS, fill=255
        )
        mask = (np.array(shape, np.float32) / 255.0)[:, :, None]
        behind = self._behind(frame, (new_left, top, new_right, bottom))
        faded = (1.0 - opacity) * behind + opacity * painted.astype(np.float32)
        region[:] = (region * (1.0 - mask) + faded * mask).round().astype(np.uint8)
        return True

    def _behind(self, frame: np.ndarray, card) -> np.ndarray:
        left, top, right, bottom = card
        height, width = frame.shape[:2]
        strips = [
            frame[max(top - BEHIND_RING, 0) : max(top, 0), max(left, 0) : min(right, width)],
            frame[
                min(bottom, height) : min(bottom + BEHIND_RING, height),
                max(left, 0) : min(right, width),
            ],
            frame[max(top, 0) : min(bottom, height), max(left - BEHIND_RING, 0) : max(left, 0)],
            frame[
                max(top, 0) : min(bottom, height),
                min(right, width) : min(right + BEHIND_RING, width),
            ],
        ]
        pixels = np.concatenate([strip.reshape(-1, 3) for strip in strips if strip.size])
        return np.median(pixels, axis=0).astype(np.float32)

    def _natural_width(self, text: str, size: int, width: int, lines_before: int) -> int:
        font = nunito(size)
        if lines_before <= 1:
            return text_width(self._probe, text, font)
        wrapped = wrap(self._probe, text, font, width)
        widest = max(text_width(self._probe, line, font) for line in wrapped)
        if len(wrapped) > lines_before:
            widest = int(widest * len(wrapped) / lines_before * 1.1)
        return widest
