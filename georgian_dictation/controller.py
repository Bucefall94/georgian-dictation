from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from georgian_dictation.ai.processor import AIProcessor, ProcessingResult, apply_failure_action
from georgian_dictation.asr.runtime import RuntimeStatus, inspect_runtime
from georgian_dictation.audio.capture import AudioCapture
from georgian_dictation.config.credentials import CredentialError
from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.hotkeys.windows import GlobalHotkey
from georgian_dictation.insertion.windows import TextInserter
from georgian_dictation.models.registry import ModelRegistry
from georgian_dictation.services.dictation import DictationSession
from georgian_dictation.ui.overlay import ListeningOverlay


class ApplicationController(QObject):
    status_changed = Signal(str, str)
    active_changed = Signal(bool)
    error = Signal(str)
    hotkey_status = Signal(bool, str)
    transcript_inserted = Signal(str)
    transcript_processed = Signal(object)
    credentials_required = Signal()
    _ai_completed = Signal(object)

    def __init__(
        self,
        settings: SettingsStore,
        registry: ModelRegistry,
        overlay: ListeningOverlay,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.registry = registry
        self.overlay = overlay
        self.log = logging.getLogger(__name__)
        self.audio = AudioCapture()
        self.session = DictationSession()
        self.inserter = TextInserter()
        self.hotkey = GlobalHotkey()
        self.ai_processor = AIProcessor()
        # A single worker preserves final-segment order during long dictation.
        self._ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="GeminiText")
        self.processing_history: deque[ProcessingResult] = deque(maxlen=100)
        self.runtime_status: RuntimeStatus = inspect_runtime(
            self.settings.get("advanced", "nemo_runtime_dir", "")
        )
        self._active = False
        self._capturing = False
        self._session_had_error = False
        self._stt_finished = False
        self._pending_ai = 0
        self._last_good_hotkey = (
            self.settings.get("hotkey", "sequence", "F8"),
            self.settings.get("hotkey", "mode", "toggle"),
        )
        self.audio.level_changed.connect(self.overlay.set_level)
        self.audio.error.connect(self._fail)
        self.session.state_changed.connect(self._on_session_state)
        self.session.result_ready.connect(self._on_result)
        self.session.error.connect(self._on_session_error)
        self.session.finished.connect(self._on_session_finished)
        self.inserter.error.connect(self.error)
        self._ai_completed.connect(self._on_ai_completed)

    @property
    def active(self) -> bool:
        return self._active

    def initialize(self) -> None:
        model = self.registry.selected()
        if model.kind == "cloud" and not self.registry.is_installed(model):
            self.status_changed.emit("error", "Deepgram API key ჯერ შენახული არ არის")
        elif model.kind != "cloud" and not self.runtime_status.available:
            self.status_changed.emit("error", self.runtime_status.message)
        elif not self.registry.is_installed(model):
            self.status_changed.emit("error", "არჩეული მოდელი დაყენებული არ არის")
        else:
            self.status_changed.emit("idle", "მზადაა")
        self.apply_hotkey(
            self.settings.get("hotkey", "sequence", "F8"),
            self.settings.get("hotkey", "mode", "toggle"),
            persist=False,
        )

    def apply_hotkey(self, sequence: str, mode: str, *, persist: bool = True) -> None:
        sequence = sequence.strip()
        if not sequence:
            self.hotkey_status.emit(False, "Hotkey ცარიელია")
            return
        old = self._last_good_hotkey
        thread = self.hotkey.register(sequence, mode)
        thread.activated.connect(self._hotkey_pressed)
        thread.deactivated.connect(self._hotkey_released)

        def registered() -> None:
            self._last_good_hotkey = (sequence, mode)
            if persist:
                self.settings.set("hotkey", "sequence", sequence, save=False)
                self.settings.set("hotkey", "mode", mode)
            self.hotkey_status.emit(True, f"აქტიურია: {sequence}")

        def failed(message: str) -> None:
            self.hotkey_status.emit(False, message)
            self.error.emit(message)
            if (sequence, mode) != old:
                QTimer.singleShot(100, lambda: self.apply_hotkey(*old, persist=False))

        thread.registered.connect(registered)
        thread.registration_failed.connect(failed)
        thread.start()

    def _hotkey_pressed(self) -> None:
        mode = self.settings.get("hotkey", "mode", "toggle")
        if mode == "push_to_talk":
            self.start_dictation()
        elif self._capturing:
            self.stop_dictation()
        elif not self._active:
            self.start_dictation()

    def _hotkey_released(self) -> None:
        if self.settings.get("hotkey", "mode") == "push_to_talk" and self._capturing:
            self.stop_dictation()

    def start_dictation(self) -> None:
        if self._active:
            return
        model = self.registry.selected()
        if model.kind != "cloud" and not self.runtime_status.available:
            self._fail(self.runtime_status.message)
            return
        deepgram_key: str | None = None
        if model.kind == "cloud":
            try:
                deepgram_key = self.registry.credentials.read()
            except CredentialError as exc:
                self._fail(str(exc))
                return
            if not deepgram_key:
                self._fail(
                    "Deepgram API key ჯერ შენახული არ არის. Advanced გვერდზე ჩასვით და შეინახეთ key."
                )
                self.credentials_required.emit()
                return
        model_path = self.registry.path_for(model)
        if not self.registry.is_installed(model):
            self._fail(f"მოდელი დაყენებული არ არის: {model.name}")
            return
        self._active = True
        self._capturing = True
        self._session_had_error = False
        self._stt_finished = False
        self._pending_ai = 0
        self.active_changed.emit(True)
        self.status_changed.emit("listening", "გისმენთ")
        self.overlay.show_state("listening", "Listening")
        self.session.start(
            model,
            model_path,
            backend=self.settings.get("advanced", "backend", "cuda"),
            silence_ms=int(self.settings.get("audio", "silence_ms", 1200)),
            vad_threshold=float(self.settings.get("audio", "vad_threshold", 0.012)),
            automatic_punctuation=bool(
                self.settings.get("dictation", "automatic_punctuation", True)
            ),
            streaming_profile=self.settings.get(
                "advanced", "streaming_profile", "fastest"
            ),
            runtime_dir=self.settings.get("advanced", "nemo_runtime_dir", ""),
            api_key=deepgram_key,
        )
        try:
            device_id = self.settings.get("audio", "device_id")
            self.audio.start(device_id, self.session.feed_audio)
        except RuntimeError:
            self.session.stop()
            self._active = False
            self._capturing = False
            self.active_changed.emit(False)

    def stop_dictation(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self.audio.stop()
        self.status_changed.emit("transcribing", "მეტყველებას ტექსტად ვაქცევ…")
        self.overlay.show_state("transcribing", "Transcribing")
        self.session.stop()

    def _on_session_state(self, state: str, detail: str) -> None:
        mapped = "transcribing" if state == "processing" else state
        self.status_changed.emit(mapped, detail)
        if self._active and state != "success":
            self.overlay.show_state(mapped, detail)

    def _on_result(self, text: str) -> None:
        raw = text.strip()
        if not raw:
            return
        mode = self.settings.get("ai", "mode", "off")
        if mode == "off":
            self._on_ai_completed(
                ProcessingResult(raw, raw, "off", "", 0.0, "off")
            )
            return
        self._pending_ai += 1
        self.status_changed.emit("ai_processing", "Gemini ტექსტს ამუშავებს…")
        self.overlay.show_state("ai_processing", "AI Processing")
        future = self._ai_executor.submit(
            self.ai_processor.process,
            raw,
            mode=mode,
            model=self.settings.get("ai", "gemini_model", ""),
            timeout_seconds=int(self.settings.get("ai", "timeout_seconds", 20)),
            aggressiveness=self.settings.get("ai", "aggressiveness", "conservative"),
        )
        future.add_done_callback(lambda done, original=raw: self._ai_future_done(done, original))

    def _ai_future_done(self, future: Future[ProcessingResult], raw: str) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self.log.error("AI post-processing worker failed (%s)", exc.__class__.__name__)
            result = ProcessingResult(
                raw,
                raw,
                self.settings.get("ai", "mode", "smart_correction"),
                self.settings.get("ai", "gemini_model", ""),
                0.0,
                "failed",
                str(exc),
            )
        self._ai_completed.emit(result)

    def _on_ai_completed(self, result: ProcessingResult) -> None:
        if result.mode != "off":
            self._pending_ai = max(0, self._pending_ai - 1)
        self.processing_history.append(result)
        self.transcript_processed.emit(result)
        action = self.settings.get("ai", "failure_action", "insert_raw")
        text, copy_raw = apply_failure_action(result, action)
        if copy_raw:
            self.inserter.copy_to_clipboard(result.raw_transcript)
            self.status_changed.emit("error", "AI ვერ შესრულდა · RAW ტექსტი clipboard-ში დაკოპირდა")
            self.overlay.show_state("error", "RAW copied")
            self.error.emit(result.error)
        elif text is None:
            self.status_changed.emit("error", "AI ვერ შესრულდა · RAW ტექსტი Diagnostics-ში შენარჩუნდა")
            self.overlay.show_state("error", "AI Error")
            self.error.emit(result.error)
        else:
            if result.status == "failed":
                self.error.emit(result.error)
            self._insert_text(text, result.raw_transcript)
        if self._stt_finished and self._pending_ai == 0:
            self._finish_session()
        elif self._capturing and self._pending_ai == 0:
            QTimer.singleShot(220, lambda: self.overlay.show_state("listening", "Listening"))

    def _insert_text(self, text: str, raw: str) -> None:
        insert_text = text.strip()
        if not insert_text:
            return
        if self.settings.get("dictation", "trailing_space", True):
            insert_text += " "
        self.status_changed.emit("typing", "ვწერ…")
        self.overlay.show_state("typing", "Typing")
        method = self.settings.get("dictation", "insertion_method", "auto")
        if self.inserter.insert(insert_text, method):
            self.transcript_inserted.emit(raw)

    def _on_session_error(self, message: str) -> None:
        self._session_had_error = True
        self._fail(message)

    def _on_session_finished(self) -> None:
        self.audio.stop()
        self._capturing = False
        self._stt_finished = True
        if self._pending_ai:
            self.status_changed.emit("ai_processing", "Gemini-ის დარჩენილ ტექსტს ვამუშავებ…")
            self.overlay.show_state("ai_processing", "AI Processing")
            return
        self._finish_session()

    def _finish_session(self) -> None:
        if not self._active:
            return
        self._active = False
        self._capturing = False
        self.active_changed.emit(False)
        if self._session_had_error:
            self.status_changed.emit("error", "სესია შეცდომით დასრულდა")
        else:
            self.status_changed.emit("idle", "მზადაა")
            self.overlay.show_state("success", "Done")

    def _fail(self, message: str) -> None:
        self.log.error(message)
        self.status_changed.emit("error", message)
        self.overlay.show_state("error", "Error")
        self.error.emit(message)

    def shutdown(self) -> None:
        self.audio.stop()
        self.session.stop()
        self.session.wait(10)
        self._ai_executor.shutdown(wait=False, cancel_futures=False)
        self.hotkey.unregister()
