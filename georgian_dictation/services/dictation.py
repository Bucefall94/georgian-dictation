from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from georgian_dictation.asr.base import RecognitionResult
from georgian_dictation.asr.deepgram import DeepgramError, DeepgramNova3Recognizer
from georgian_dictation.asr.nemo_native import NemoNativeRecognizer
from georgian_dictation.models.registry import ModelSpec


class DictationSession(QObject):
    state_changed = Signal(str, str)
    result_ready = Signal(str)
    error = Signal(str)
    ready = Signal()
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.log = logging.getLogger(__name__)
        self._audio: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=512)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._engine: NemoNativeRecognizer | DeepgramNova3Recognizer | None = None
        self._cloud_failure: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(
        self,
        model: ModelSpec,
        model_path: Path | None,
        *,
        backend: str,
        silence_ms: int,
        vad_threshold: float,
        automatic_punctuation: bool,
        streaming_profile: str,
        runtime_dir: str,
        api_key: str | None = None,
    ) -> None:
        if self.running:
            return
        self._stop.clear()
        self._audio = queue.Queue(maxsize=512)
        self._cloud_failure = None
        args = (
            model,
            model_path,
            backend,
            silence_ms,
            vad_threshold,
            automatic_punctuation,
            streaming_profile,
            runtime_dir,
            api_key,
        )
        self._thread = threading.Thread(
            target=self._run, args=args, name="DictationASR", daemon=True
        )
        self._thread.start()

    def feed_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        if self._stop.is_set():
            return
        try:
            self._audio.put_nowait((samples, sample_rate))
        except queue.Full:
            self.log.error("Audio queue overflow; dropping a block")

    def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        try:
            self._audio.put_nowait(None)
        except queue.Full:
            pass

    def wait(self, timeout: float = 10.0) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(
        self,
        model: ModelSpec,
        model_path: Path | None,
        backend: str,
        silence_ms: int,
        vad_threshold: float,
        automatic_punctuation: bool,
        streaming_profile: str,
        runtime_dir: str,
        api_key: str | None,
    ) -> None:
        self.state_changed.emit("loading", "მოდელი იტვირთება…")
        try:
            if model.kind == "cloud":
                self._engine = DeepgramNova3Recognizer(
                    api_key or "",
                    automatic_punctuation=automatic_punctuation,
                )
                self._run_cloud(silence_ms)
                return
            if model_path is None:
                raise RuntimeError("ლოკალური მოდელის ფაილი ვერ მოიძებნა")
            right_context = -1 if streaming_profile == "higher_accuracy" else 1
            self._engine = NemoNativeRecognizer(
                model_path,
                backend=backend,
                endpointing=model.kind == "streaming",
                silence_ms=silence_ms,
                rnnt_right_context=right_context,
                automatic_punctuation=automatic_punctuation,
                runtime_dir=runtime_dir,
            )
            self.ready.emit()
            self.state_changed.emit("listening", "გისმენთ")
            if model.kind == "streaming":
                self._run_streaming()
            else:
                self._run_accurate(silence_ms, vad_threshold)
        except Exception as exc:
            self.log.exception("Dictation session failed")
            self.error.emit(str(exc))
            self.state_changed.emit("error", "შეცდომა")
        finally:
            if self._engine:
                self._engine.close()
                self._engine = None
            self.finished.emit()

    def _run_cloud(self, silence_ms: int) -> None:
        assert isinstance(self._engine, DeepgramNova3Recognizer)
        self.state_changed.emit("loading", "Deepgram Nova-3-ს ვუკავშირდები…")
        self._engine.start_stream(
            self._emit_result,
            self._cloud_error,
            silence_ms=silence_ms,
        )
        self.ready.emit()
        self.state_changed.emit("listening", "გისმენთ · Deepgram Cloud")
        while True:
            item = self._audio.get()
            if item is None:
                break
            samples, rate = item
            self._engine.push(samples, rate)
        self.state_changed.emit("processing", "Deepgram დარჩენილ აუდიოს ამუშავებს…")
        self._engine.finish_stream()
        if self._cloud_failure:
            raise DeepgramError(self._cloud_failure)
        self.state_changed.emit("success", "მზადაა")

    def _cloud_error(self, message: str) -> None:
        self._cloud_failure = message
        self._stop.set()
        try:
            self._audio.put_nowait(None)
        except queue.Full:
            pass

    def _run_streaming(self) -> None:
        assert self._engine is not None
        self._engine.start_stream()
        while True:
            item = self._audio.get()
            if item is None:
                break
            samples, rate = item
            for result in self._engine.push(samples, rate):
                self._emit_result(result)
        self.state_changed.emit("processing", "ვამუშავებ…")
        for result in self._engine.finish_stream():
            self._emit_result(result)
        self._engine.close_stream()
        self.state_changed.emit("success", "მზადაა")

    def _run_accurate(self, silence_ms: int, configured_threshold: float) -> None:
        assert self._engine is not None
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="AccurateASR")
        pending: list[Future[RecognitionResult]] = []
        pre_roll: deque[np.ndarray] = deque(maxlen=3)
        segment: list[np.ndarray] = []
        speech_seen = False
        silence_samples = 0
        sample_rate = 16000
        noise_floor = 0.002

        def submit_segment() -> None:
            nonlocal segment, speech_seen, silence_samples
            if not speech_seen or not segment:
                segment, speech_seen, silence_samples = [], False, 0
                return
            audio = np.concatenate(segment)
            min_samples = int(sample_rate * 0.25)
            if audio.size >= min_samples:
                self.state_changed.emit("processing", "ფრაზას ვამუშავებ…")
                future = executor.submit(self._engine.recognize, audio, sample_rate)
                future.add_done_callback(self._accurate_done)
                pending.append(future)
            segment, speech_seen, silence_samples = [], False, 0

        try:
            while True:
                item = self._audio.get()
                if item is None:
                    break
                samples, sample_rate = item
                rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
                threshold = max(configured_threshold, noise_floor * 3.0)
                is_speech = rms >= threshold
                if not speech_seen:
                    if is_speech:
                        speech_seen = True
                        segment.extend(pre_roll)
                        pre_roll.clear()
                        segment.append(samples)
                    else:
                        noise_floor = noise_floor * 0.97 + rms * 0.03
                        pre_roll.append(samples)
                    continue
                segment.append(samples)
                if is_speech:
                    silence_samples = 0
                else:
                    silence_samples += samples.size
                    if silence_samples >= int(sample_rate * silence_ms / 1000):
                        submit_segment()
                        self.state_changed.emit("listening", "გისმენთ")
            submit_segment()
            if pending:
                self.state_changed.emit("processing", "დარჩენილ ფრაზებს ვამუშავებ…")
            executor.shutdown(wait=True)
            self.state_changed.emit("success", "მზადაა")
        finally:
            executor.shutdown(wait=False, cancel_futures=False)

    def _accurate_done(self, future: Future[RecognitionResult]) -> None:
        try:
            self._emit_result(future.result())
        except Exception as exc:
            self.log.exception("Accurate utterance failed")
            self.error.emit(str(exc))

    def _emit_result(self, result: RecognitionResult) -> None:
        text = result.transcript.strip()
        if result.is_final and text:
            self.result_ready.emit(text)
