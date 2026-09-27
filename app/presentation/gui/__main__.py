from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.config.store import data_dir
from app.infrastructure.logs import configure_file_logging
from app.infrastructure.whisper import quiet_model_downloads
from app.presentation.gui.icons import app_icon
from app.presentation.gui.main_window import MainWindow
from app.presentation.gui.theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    log_file = configure_file_logging(data_dir() / "logs")
    quiet_model_downloads()
    application = QApplication(arguments)
    application.setApplicationName("ClipTranslator")
    application.setWindowIcon(app_icon())
    apply_theme(application, data_dir() / "ui")
    window = MainWindow(log_file=log_file)
    files = [Path(argument) for argument in arguments[1:] if Path(argument).is_file()]
    if files:
        window.open_media(files[0])
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
