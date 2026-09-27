from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from app.presentation.gui.icons import stroke_svg


@dataclass(frozen=True)
class Palette:
    background_top: str = "#0d0a1a"
    background_middle: str = "#170f2e"
    background_bottom: str = "#2a1450"
    surface: str = "rgba(255, 255, 255, 0.045)"
    surface_hover: str = "rgba(255, 255, 255, 0.08)"
    field: str = "rgba(10, 6, 24, 0.55)"
    border: str = "rgba(255, 255, 255, 0.09)"
    border_focus: str = "#a78bfa"
    accent_start: str = "#7c3aed"
    accent_end: str = "#c026d3"
    accent_soft: str = "rgba(167, 139, 250, 0.22)"
    text: str = "#efeaff"
    text_muted: str = "#a79cc9"
    warning: str = "#f6c177"
    danger: str = "#ff7a9c"
    success: str = "#6ee7c8"


PALETTE = Palette()


def accent_gradient(p: Palette = PALETTE) -> str:
    return (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent_start}, stop:1 {p.accent_end})"
    )


def background_gradient(p: Palette = PALETTE) -> str:
    return (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {p.background_top}, stop:0.55 {p.background_middle}, "
        f"stop:1 {p.background_bottom})"
    )


def _write_asset(folder: Path, name: str, svg: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.svg"
    path.write_text(svg, encoding="utf-8")
    return path.as_posix()


def stylesheet(assets: Path, p: Palette = PALETTE) -> str:
    chevron = _write_asset(assets, "chevron", stroke_svg("chevron", p.text_muted))
    check = _write_asset(assets, "check", stroke_svg("check", "#ffffff", 3))
    return f"""
    * {{ color: {p.text}; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {background_gradient(p)}; }}
    QWidget#root, QWidget#transparent {{ background: transparent; }}
    QFrame#card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 16px;
    }}
    QFrame#dropZone {{
        background: {p.surface};
        border: 2px dashed rgba(167, 139, 250, 0.45);
        border-radius: 16px;
    }}
    QFrame#dropZone[active="true"] {{
        background: {p.accent_soft};
        border-color: {p.border_focus};
    }}
    QFrame#notice {{
        background: rgba(246, 193, 119, 0.10);
        border: 1px solid rgba(246, 193, 119, 0.35);
        border-radius: 12px;
    }}
    QLabel {{ background: transparent; }}
    QFrame#banner {{
        background: {p.accent_soft};
        border: 1px solid rgba(167, 139, 250, 0.55);
        border-radius: 12px;
    }}
    QListWidget {{
        background: {p.field};
        border: 1px solid {p.border};
        border-radius: 12px;
        padding: 6px;
        outline: 0;
    }}
    QListWidget::item {{ padding: 8px; border-radius: 8px; }}
    QListWidget::item:selected {{ background: {p.accent_soft}; }}
    QListWidget::item:hover {{ background: {p.surface_hover}; }}
    QDoubleSpinBox {{
        background: {p.field};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 6px 8px;
    }}
    QLabel#title {{ font-size: 17pt; font-weight: 700; }}
    QLabel#subtitle, QLabel#muted {{ color: {p.text_muted}; }}
    QLabel#section {{
        color: {p.text_muted}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px;
    }}
    QLabel#noticeText {{ color: {p.warning}; background: transparent; border: 0; }}
    QLabel#percent {{ color: {p.text_muted}; font-weight: 600; }}
    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {p.surface_hover}; border-color: rgba(167,139,250,0.5); }}
    QPushButton:pressed {{ background: {p.accent_soft}; }}
    QPushButton:disabled {{ color: rgba(239, 234, 255, 0.35); background: rgba(255,255,255,0.02); }}
    QPushButton#primary {{
        background: {accent_gradient(p)};
        border: 0;
        padding: 11px 18px;
        font-size: 10.5pt;
    }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #d946ef);
    }}
    QPushButton#primary:disabled {{ background: rgba(124, 58, 237, 0.30); }}
    QPushButton#danger {{ color: {p.danger}; border-color: rgba(255, 122, 156, 0.4); }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; }}
    QPushButton#ghost:hover {{ background: {p.surface_hover}; }}
    QLineEdit, QComboBox {{
        background: {p.field};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 8px 10px;
        selection-background-color: {p.accent_start};
    }}
    QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: {p.border_focus}; }}
    QComboBox::drop-down {{ border: 0; width: 28px; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{
        background: #1b1332;
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 4px;
        outline: 0;
        selection-background-color: {p.accent_soft};
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border-radius: 6px;
        border: 1px solid rgba(255,255,255,0.25); background: {p.field};
    }}
    QCheckBox::indicator:checked {{
        background: {accent_gradient(p)}; border: 0; image: url("{check}");
    }}
    QProgressBar {{
        background: rgba(255, 255, 255, 0.06);
        border: 0;
        border-radius: 5px;
        min-height: 10px;
        max-height: 10px;
    }}
    QProgressBar::chunk {{ background: {accent_gradient(p)}; border-radius: 5px; }}
    QTableView {{
        background: transparent;
        alternate-background-color: rgba(255, 255, 255, 0.025);
        border: 0;
        gridline-color: transparent;
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
    }}
    QTableView::item {{ padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.04); }}
    QHeaderView::section {{
        background: transparent;
        color: {p.text_muted};
        border: 0;
        border-bottom: 1px solid {p.border};
        padding: 8px;
        font-weight: 700;
        font-size: 8.5pt;
    }}
    QTableCornerButton::section {{ background: transparent; border: 0; }}
    QHeaderView {{ background: transparent; border: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.14); border-radius: 3px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: rgba(167,139,250,0.5); }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 4px; }}
    QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.14); border-radius: 3px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; border: 0; width: 0; height: 0;
    }}
    QSlider::groove:horizontal {{
        height: 4px; background: rgba(255,255,255,0.12); border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {accent_gradient(p)}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: #ffffff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
    }}
    QSplitter::handle {{ background: transparent; }}
    QToolTip {{
        background: #1b1332; color: {p.text}; border: 1px solid {p.border};
        border-radius: 8px; padding: 6px;
    }}
    QMessageBox QLabel {{ min-width: 320px; }}
    """


def apply_theme(application: QApplication, assets: Path) -> None:
    application.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    application.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(PALETTE.background_middle))
    palette.setColor(QPalette.ColorRole.Base, QColor("#140d26"))
    palette.setColor(QPalette.ColorRole.Text, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1b1332"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1b1332"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PALETTE.accent_start))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(PALETTE.text_muted))
    application.setPalette(palette)
    application.setStyleSheet(stylesheet(assets))
