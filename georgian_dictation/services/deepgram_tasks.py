from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from georgian_dictation.asr.deepgram import DeepgramNova3Recognizer


class DeepgramConnectionTest(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self._api_key = api_key

    def run(self) -> None:
        try:
            with DeepgramNova3Recognizer(self._api_key, timeout=25.0) as recognizer:
                ok, message = recognizer.health_check()
            if ok:
                self.succeeded.emit(message)
            else:
                self.failed.emit(message)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self._api_key = ""
