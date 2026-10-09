from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.application.ports import FractionCallback
from app.domain.screen_prompts import (
    Box,
    Detection,
    PromptScan,
    group_lines,
    is_album_title,
    is_button,
    is_players_title,
    is_readable,
    union,
)
from app.infrastructure.ffmpeg import ffmpeg_executable, video_info
from app.infrastructure.process import HIDDEN_WINDOW
from app.infrastructure.prompt_renderer import card_bounds, card_colors

log = logging.getLogger(__name__)

MODEL_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx"
OCR_MODELS = {
    "detect": (
        f"{MODEL_BASE}/PP-OCRv6/det/PP-OCRv6_det_small.onnx",
        "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    ),
    "read": (
        f"{MODEL_BASE}/PP-OCRv5/rec/eslav_PP-OCRv5_rec_mobile.onnx",
        "08705d6721849b1347d26187f15a5e362c431963a2a62bfff4feac578c489aab",
    ),
}
SCANS_PER_SECOND = 2
CARD_RING = 7
LIGHT = 185
MAX_SPREAD = 40
MAX_TINT = 30
SIDE_GAP = 8
TITLE_TOLERANCE = 25
CHUNK = 1 << 16
LOOK_VERSION = 1


class OcrModelError(RuntimeError):
    pass


def ocr_model_path(models_dir: Path, name: str) -> Path:
    url, _ = OCR_MODELS[name]
    return models_dir / "ocr" / url.rsplit("/", 1)[1]


def ocr_models_ready(models_dir: Path) -> bool:
    return all(ocr_model_path(models_dir, name).is_file() for name in OCR_MODELS)


def download_ocr_models(models_dir: Path, progress: FractionCallback | None = None) -> None:
    names = [name for name in OCR_MODELS if not ocr_model_path(models_dir, name).is_file()]
    for number, name in enumerate(names):
        url, digest = OCR_MODELS[name]
        target = ocr_model_path(models_dir, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        hasher = hashlib.sha256()
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(CHUNK):
                    handle.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress((number + done / total) / len(names))
        if hasher.hexdigest() != digest:
            partial.unlink(missing_ok=True)
            raise OcrModelError(f"The text reader model {target.name} did not download correctly.")
        partial.replace(target)
    if progress:
        progress(1.0)


def corners(points: Any) -> Box:
    return (
        float(points[:, 0].min()),
        float(points[:, 1].min()),
        float(points[:, 0].max()),
        float(points[:, 1].max()),
    )


def on_light_card(image: np.ndarray, box: Box) -> bool:
    x0, y0, x1, y1 = (int(round(value)) for value in box)
    height, width = image.shape[:2]
    a0, b0 = max(x0 - CARD_RING, 0), max(y0 - CARD_RING, 0)
    a1, b1 = min(x1 + CARD_RING, width), min(y1 + CARD_RING, height)
    patch = image[b0:b1, a0:a1].astype(np.int16)
    mask = np.ones(patch.shape[:2], bool)
    mask[max(y0 - b0, 0) : y1 - b0, max(x0 - a0, 0) : x1 - a0] = False
    ring = patch[mask]
    if len(ring) == 0:
        return False
    gray = ring.mean(axis=1)
    tint = (ring.max(axis=1) - ring.min(axis=1)).mean()
    spread = np.percentile(gray, 90) - np.percentile(gray, 10)
    return bool(np.median(gray) >= LIGHT and spread <= MAX_SPREAD and tint < MAX_TINT)


def inside_card(image: np.ndarray, box: Box) -> bool:
    x0, y0, x1, y1 = (int(value) for value in box)
    middle = min(max((y0 + y1) // 2, 0), image.shape[0] - 1)
    sides = [image[middle, x] for x in (x0 - SIDE_GAP, x1 + SIDE_GAP) if 0 <= x < image.shape[1]]
    if len(sides) < 2:
        return False
    return all(
        int(pixel.mean()) > LIGHT and int(pixel.max()) - int(pixel.min()) < MAX_TINT
        for pixel in sides
    )


def sampled_frames(
    media: Path, width: int, height: int, every: int
) -> Iterator[tuple[int, np.ndarray]]:
    command = [
        ffmpeg_executable(),
        "-v",
        "error",
        "-i",
        str(media),
        "-vf",
        f"select='not(mod(n\\,{every}))'",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-",
    ]
    reader = subprocess.Popen(command, stdout=subprocess.PIPE, creationflags=HIDDEN_WINDOW)
    size = width * height * 3
    number = 0
    try:
        while True:
            raw = reader.stdout.read(size) if reader.stdout else b""
            if len(raw) < size:
                return
            yield number * every, np.frombuffer(raw, np.uint8).reshape(height, width, 3)
            number += 1
    finally:
        reader.kill()
        reader.wait()


class PromptScanner:
    def __init__(self, models_dir: Path, use_gpu: bool) -> None:
        self.models_dir = models_dir
        self.use_gpu = use_gpu
        self._detector: Any = None
        self._reader: Any = None

    def prepare(self, progress: FractionCallback | None = None) -> None:
        if not ocr_models_ready(self.models_dir):
            download_ocr_models(self.models_dir, progress)

    def store(self, scan: PromptScan, path: Path) -> dict[str, Any]:
        np.savez_compressed(path, *scan.templates)
        return {
            "width": scan.width,
            "height": scan.height,
            "fps": scan.fps,
            "templates": path.name,
            "detections": [asdict(detection) for detection in scan.detections],
        }

    def load(self, data: dict[str, Any], folder: Path) -> PromptScan:
        with np.load(folder / data["templates"]) as stored:
            templates = [stored[f"arr_{number}"] for number in range(len(stored.files))]
        detections = [
            Detection(
                item["frame"],
                tuple(item["box"]),
                item["text"],
                item.get("lines", 1),
                tuple(item.get("look", ())),
            )
            for item in data["detections"]
        ]
        return PromptScan(data["width"], data["height"], data["fps"], detections, templates)

    @property
    def cache_identity(self) -> dict[str, Any]:
        return {
            "models": {name: digest for name, (_, digest) in OCR_MODELS.items()},
            "rate": SCANS_PER_SECOND,
            "look": LOOK_VERSION,
        }

    def scan(self, media: Path, progress: FractionCallback | None = None) -> PromptScan:
        width, height, fps, duration = video_info(media)
        every = max(round(fps / SCANS_PER_SECOND), 1)
        result = PromptScan(width, height, fps, [], [])
        layout: dict[str, Any] | None = None
        total = max(int(duration * fps / every), 1)
        for count, (index, frame) in enumerate(sampled_frames(media, width, height, every)):
            if layout is None:
                layout = self._layout(frame)
            if layout is not None:
                for detection, template in self._read_album(frame, index, layout):
                    result.detections.append(detection)
                    result.templates.append(template)
            if progress:
                progress(min((count + 1) / total, 1.0))
        return result

    def _engines(self) -> tuple[Any, Any]:
        if self._detector is None:
            self._detector = self._engine(self.use_gpu)
            self._reader = self._engine(False)
        return self._detector, self._reader

    def _engine(self, gpu: bool) -> Any:
        if not ocr_models_ready(self.models_dir):
            raise OcrModelError("The text reader models are not downloaded.")
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec, ModelType, OCRVersion

        params: dict[str, Any] = {
            "Global.log_level": "error",
            "Global.use_cls": False,
            "Det.model_path": str(ocr_model_path(self.models_dir, "detect")),
            "Rec.model_path": str(ocr_model_path(self.models_dir, "read")),
            "Rec.lang_type": LangRec.ESLAV,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        }
        if gpu:
            params |= {
                "EngineConfig.onnxruntime.use_cuda": True,
                "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
            }
        return RapidOCR(params=params)

    def _layout(self, frame: np.ndarray) -> dict[str, Any] | None:
        _, reader = self._engines()
        result = reader(frame, use_cls=False)
        if result.boxes is None:
            return None
        listed = [
            (corners(points), text) for points, text in zip(result.boxes, result.txts, strict=False)
        ]
        album = next((box for box, text in listed if is_album_title(text)), None)
        players = next((box for box, text in listed if is_players_title(text)), None)
        if album is None or players is None:
            return None
        return {"left": int(players[2]), "title": album}

    def _read_line(self, image: np.ndarray, box: Box) -> str:
        _, reader = self._engines()
        x0, y0, x1, y1 = (int(value) for value in box)
        crop = np.ascontiguousarray(image[max(y0, 0) : y1, max(x0, 0) : x1])
        if crop.size == 0:
            return ""
        result = reader(crop, use_det=False, use_cls=False, use_rec=True)
        return result.txts[0] if result.txts else ""

    def _read_album(
        self, frame: np.ndarray, index: int, layout: dict[str, Any]
    ) -> Iterator[tuple[Detection, np.ndarray]]:
        detector, _ = self._engines()
        left = layout["left"]
        view = np.ascontiguousarray(frame[:, left:])
        found = detector(view, use_det=True, use_cls=False, use_rec=False)
        if found.boxes is None:
            return
        boxes = [corners(points) for points in found.boxes]
        tx0, ty0, tx1, _ = layout["title"]
        title = next(
            (
                box
                for box in boxes
                if abs(box[1] - ty0) < TITLE_TOLERANCE
                and box[0] + left < tx1
                and box[2] + left > tx0
            ),
            None,
        )
        if title is None or not is_album_title(self._read_line(view, title)):
            return
        below = [box for box in boxes if box[1] > title[3]]
        for group in group_lines(below, lambda box: inside_card(view, box)):
            area = union(group)
            if not on_light_card(view, area):
                continue
            text = " ".join(part for part in (self._read_line(view, box) for box in group) if part)
            if not is_readable(text) or is_button(text):
                continue
            box = (
                int(area[0]) + left,
                int(area[1]),
                int(round(area[2])) + left,
                int(round(area[3])),
            )
            template = frame[box[1] : box[3], box[0] : box[2]].mean(axis=2).astype(np.float32)
            yield Detection(index, box, text, len(group), bubble_look(frame, box)), template


def bubble_look(frame: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, ...]:
    background, ink = card_colors(frame, box)
    if background is None:
        return ()
    left, top, right, bottom = card_bounds(frame, box, background)
    offsets = (box[0] - left, box[1] - top, right - box[2], bottom - box[3])
    return (*(int(value) for value in background), *(int(value) for value in ink), *offsets)


def gpu_available() -> bool:
    try:
        import onnxruntime
    except ImportError:
        return False
    return "CUDAExecutionProvider" in onnxruntime.get_available_providers()


def create_prompt_scanner(models_dir: Path) -> PromptScanner:
    use_gpu = gpu_available()
    if use_gpu:
        from app.infrastructure.gpu import expose_cuda_libraries

        expose_cuda_libraries()
    return PromptScanner(models_dir, use_gpu)
