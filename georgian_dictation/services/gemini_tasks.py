from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from georgian_dictation.ai.gemini_client import GeminiClient, check_adc


class VertexADCCheck(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.succeeded.emit(check_adc(refresh=True))
        except Exception as exc:
            self.failed.emit(str(exc))


class GeminiConnectionTest(QThread):
    succeeded = Signal(object, str)
    failed = Signal(str)

    def __init__(self, selected_model: str = "", timeout_seconds: int = 20) -> None:
        super().__init__()
        self._selected_model = selected_model
        self._timeout_seconds = timeout_seconds

    def run(self) -> None:
        try:
            check_adc(refresh=True)
            with GeminiClient(timeout_seconds=self._timeout_seconds) as client:
                models, used = client.test_connection(self._selected_model)
            self.succeeded.emit(models, used)
        except Exception as exc:
            self.failed.emit(str(exc))


class GeminiModelLoader(QThread):
    succeeded = Signal(object, str)
    failed = Signal(str)

    def __init__(self, timeout_seconds: int = 20) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds

    def run(self) -> None:
        try:
            check_adc(refresh=True)
            with GeminiClient(timeout_seconds=self._timeout_seconds) as client:
                models, working_default = client.test_connection()
            self.succeeded.emit(models, working_default)
        except Exception as exc:
            self.failed.emit(str(exc))
