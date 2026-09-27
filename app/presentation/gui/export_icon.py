from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage

from app.presentation.gui.icons import LOGO, render_svg

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICON_HEADER = struct.Struct("<HHH")
ICON_ENTRY = struct.Struct("<BBBBHHII")


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    offset = ICON_HEADER.size + ICON_ENTRY.size * len(images)
    directory = [ICON_HEADER.pack(0, 1, len(images))]
    payload = []
    for size, png in images:
        dimension = 0 if size >= 256 else size
        directory.append(ICON_ENTRY.pack(dimension, dimension, 0, 0, 1, 32, len(png), offset))
        payload.append(png)
        offset += len(png)
    return b"".join(directory + payload)


def export_icon(target: Path) -> Path:
    images = [(size, png_bytes(render_svg(LOGO, size))) for size in ICON_SIZES]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_ico(images))
    return target


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    target = Path(arguments[0]) if arguments else Path("build") / "icon.ico"
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    export_icon(target)
    del application
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
