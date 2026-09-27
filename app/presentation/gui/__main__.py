from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.infrastructure.whisper import quiet_model_downloads
from app.presentation.gui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    quiet_model_downloads()
    application = QApplication(arguments)
    application.setApplicationName("ClipTranslator")
    window = MainWindow()
    files = [Path(argument) for argument in arguments[1:] if Path(argument).is_file()]
    if files:
        window.open_media(files[0])
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
