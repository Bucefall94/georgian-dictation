from __future__ import annotations

import logging
import re
import threading
import time
import wave
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from georgian_dictation.ai.processor import AIProcessor
from georgian_dictation.asr.deepgram import DeepgramNova3Recognizer
from georgian_dictation.asr.nemo_native import NemoNativeRecognizer
from georgian_dictation.models.registry import ModelSpec


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[\wა-ჰ]+", text.casefold(), flags=re.UNICODE)


def word_error_rate(reference: str, hypothesis: str) -> float | None:
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    if not ref:
        return None
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ref_word != hyp_word),
                )
            )
        previous = current
    return previous[-1] / len(ref)


class DiagnosticsRunner(QObject):
    model_started = Signal(str)
    result = Signal(str, str, str, float, float, str, float, str, str)
    error = Signal(str, str)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.log = logging.getLogger(__name__)
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def run_models(
        self,
        wav_path: Path,
        models: list[tuple[ModelSpec, Path | None]],
        *,
        backend: str,
        reference: str,
        runtime_dir: str,
        api_key: str | None = None,
        ai_mode: str = "off",
        gemini_model: str = "",
        ai_timeout_seconds: int = 20,
        ai_aggressiveness: str = "conservative",
        ai_failure_action: str = "insert_raw",
    ) -> None:
        if self.running:
            return
        self._thread = threading.Thread(
            target=self._run,
            args=(
                wav_path,
                models,
                backend,
                reference,
                runtime_dir,
                api_key,
                ai_mode,
                gemini_model,
                ai_timeout_seconds,
                ai_aggressiveness,
                ai_failure_action,
            ),
            name="Diagnostics",
            daemon=True,
        )
        self._thread.start()

    def _run(
        self,
        wav_path: Path,
        models: list[tuple[ModelSpec, Path | None]],
        backend: str,
        reference: str,
        runtime_dir: str,
        api_key: str | None,
        ai_mode: str,
        gemini_model: str,
        ai_timeout_seconds: int,
        ai_aggressiveness: str,
        ai_failure_action: str,
    ) -> None:
        ai_processor = AIProcessor()
        try:
            with wave.open(str(wav_path), "rb") as wav:
                duration = wav.getnframes() / max(wav.getframerate(), 1)
            for model, path in models:
                self.model_started.emit(model.id)
                try:
                    started = time.perf_counter()
                    if model.kind == "cloud":
                        with DeepgramNova3Recognizer(api_key or "") as recognizer:
                            recognized = recognizer.transcribe_file(wav_path)
                    else:
                        if path is None:
                            raise RuntimeError("ლოკალური მოდელის ფაილი ვერ მოიძებნა")
                        with NemoNativeRecognizer(
                            path,
                            backend=backend,
                            automatic_punctuation=True,
                            runtime_dir=runtime_dir,
                        ) as recognizer:
                            recognized = recognizer.recognize_wav(wav_path)
                    elapsed = time.perf_counter() - started
                    rtf = elapsed / duration if duration else 0.0
                    processed = ai_processor.process(
                        recognized.transcript,
                        mode=ai_mode,
                        model=gemini_model,
                        timeout_seconds=ai_timeout_seconds,
                        aggressiveness=ai_aggressiveness,
                    )
                    final_text = processed.processed_text
                    if processed.status == "failed":
                        fallback_label = {
                            "copy_raw": "Fallback · RAW clipboard policy",
                            "show_error_keep": "Error · RAW kept",
                        }.get(ai_failure_action, "Fallback · RAW inserted")
                        ai_status = f"{fallback_label}: {processed.error}"
                    elif processed.status == "off":
                        ai_status = "AI Off"
                    else:
                        ai_status = "Success"
                    wer = word_error_rate(reference, final_text)
                    wer_text = "—" if wer is None else f"{wer * 100:.2f}%"
                    self.result.emit(
                        model.id,
                        recognized.transcript,
                        final_text,
                        elapsed,
                        rtf,
                        wer_text,
                        processed.latency_seconds,
                        processed.model or "—",
                        ai_status,
                    )
                except Exception as exc:
                    self.log.exception("Diagnostic failed for %s", model.id)
                    self.error.emit(model.id, str(exc))
        finally:
            self.finished.emit()
