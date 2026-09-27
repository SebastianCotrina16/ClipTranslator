from __future__ import annotations

from functools import cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

LOGO = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#8b5cf6"/>
      <stop offset="1" stop-color="#d946ef"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#g)"/>
  <path d="M16 20h32a4 4 0 0 1 4 4v14a4 4 0 0 1-4 4H30l-8 7v-7h-6a4 4 0 0 1-4-4V24a4 4 0 0 1 4-4z"
        fill="#ffffff" fill-opacity="0.95"/>
  <rect x="20" y="27" width="16" height="3.5" rx="1.75" fill="#7c3aed"/>
  <rect x="20" y="33" width="24" height="3.5" rx="1.75" fill="#c026d3"/>
</svg>
"""

_STROKE_ICONS = {
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M8 4v16M16 4v16M3 9h5M3 15h5M16 9h5M16 15h5"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8'
        "l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5"
        " 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3"
        "a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1"
        "a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0"
        " 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0"
        ' 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'
    ),
    "sparkles": (
        '<path d="M12 3l1.8 4.9L18.5 9.7l-4.7 1.8L12 16.4l-1.8-4.9L5.5 9.7l4.7-1.8z"/>'
        '<path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'
    ),
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "play": '<path d="M7 5v14l11-7z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "earlier": '<path d="M11 17l-5-5 5-5"/><path d="M18 17l-5-5 5-5"/>',
    "later": '<path d="M13 17l5-5-5-5"/><path d="M6 17l5-5-5-5"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "queue": '<path d="M4 6h16M4 12h16M4 18h10"/>',
}


def stroke_svg(name: str, color: str, width: float = 2.0) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
        f"{_STROKE_ICONS[name]}</svg>"
    )


def render_svg(svg: str, size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


@cache
def icon(name: str, color: str = "#ece8ff") -> QIcon:
    result = QIcon()
    for size in (16, 20, 24, 32, 48):
        result.addPixmap(QPixmap.fromImage(render_svg(stroke_svg(name, color), size)))
    return result


@cache
def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(QPixmap.fromImage(render_svg(LOGO, size)))
    return result


def logo_pixmap(size: int) -> QPixmap:
    return QPixmap.fromImage(render_svg(LOGO, size))
