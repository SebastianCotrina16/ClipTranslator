from __future__ import annotations

import threading
from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal


class BackgroundRunner(QObject):
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._job: QObject | None = None
        self._worker: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def job(self) -> QObject | None:
        return self._job

    def start(self, job: QObject, done_signals: Iterable[str]) -> None:
        if self.busy:
            raise RuntimeError("A background job is already running.")
        for name in done_signals:
            getattr(job, name).connect(self._on_done)
        self._job = job
        self._worker = threading.Thread(target=job.run, name=type(job).__name__, daemon=True)
        self._worker.start()

    def _on_done(self, *_: object) -> None:
        self._job = None
        self._worker = None
        self.finished.emit()
