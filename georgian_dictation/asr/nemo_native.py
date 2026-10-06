from __future__ import annotations

import ctypes as ct
import os
import wave
from pathlib import Path

import numpy as np

from .base import RecognitionResult
from .runtime import find_nemo_cli


class NemoError(RuntimeError):
    pass


class BackendConfig(ct.Structure):
    _fields_ = [("size", ct.c_size_t), ("gpu", ct.c_int32)]


class ModelConfig(ct.Structure):
    _fields_ = [("size", ct.c_size_t), ("path", ct.c_char_p), ("name", ct.c_char_p)]


class StreamingConfig(ct.Structure):
    _fields_ = [
        ("size", ct.c_size_t),
        ("chunk_size", ct.c_float),
        ("ctc_left_padding", ct.c_float),
        ("ctc_right_padding", ct.c_float),
        ("rnnt_right_context", ct.c_int32),
    ]


class EndpointingConfig(ct.Structure):
    _fields_ = [
        ("size", ct.c_size_t),
        ("enable", ct.c_bool),
        ("vad_based", ct.c_bool),
        ("stop_history_eou_ms", ct.c_int32),
    ]


class RecognizerConfig(ct.Structure):
    _fields_ = [
        ("size", ct.c_size_t),
        ("backend", ct.c_void_p),
        ("model", ct.c_void_p),
        ("streaming", ct.c_void_p),
        ("decoder", ct.c_void_p),
        ("vad", ct.c_void_p),
        ("endpointing", ct.c_void_p),
        ("postproc", ct.c_void_p),
        ("diar", ct.c_void_p),
        ("batching", ct.c_void_p),
    ]


class RecognitionOptions(ct.Structure):
    _fields_ = [
        ("size", ct.c_size_t),
        ("request_id", ct.c_char_p),
        ("language_code", ct.c_char_p),
        ("interim_results", ct.c_bool),
        ("enable_word_time_offsets", ct.c_bool),
        ("enable_automatic_punctuation", ct.c_bool),
        ("verbatim_transcripts", ct.c_bool),
        ("profanity_filter", ct.c_bool),
        ("stop_history_eou_ms", ct.c_int32),
        ("speech_contexts", ct.c_void_p),
        ("speech_context_count", ct.c_size_t),
        ("max_alternatives", ct.c_int32),
        ("enable_speaker_diarization", ct.c_bool),
        ("max_speaker_count", ct.c_int32),
    ]


class NemoNativeRecognizer:
    """Thin ctypes wrapper over NeMo-Speech.cpp's stable v1 C ABI."""

    def __init__(
        self,
        model_path: Path,
        *,
        backend: str = "cuda",
        endpointing: bool = False,
        silence_ms: int = 1200,
        rnnt_right_context: int = 1,
        automatic_punctuation: bool = True,
        runtime_dir: str = "",
    ) -> None:
        self.model_path = Path(model_path)
        self.backend = backend
        self.automatic_punctuation = automatic_punctuation
        self._dll_dir_cookie = None
        self._lib = self._load_library(runtime_dir)
        self._bind()
        self._handle = ct.c_void_p()
        self._stream = ct.c_void_p()

        model_bytes = os.fsencode(str(self.model_path))
        backend_cfg = BackendConfig(ct.sizeof(BackendConfig), -1 if backend == "cpu" else 0)
        model_cfg = ModelConfig(ct.sizeof(ModelConfig), model_bytes, None)
        streaming_cfg = StreamingConfig(
            ct.sizeof(StreamingConfig), 0.16, 1.92, 1.92, rnnt_right_context
        )
        endpoint_cfg = EndpointingConfig(
            ct.sizeof(EndpointingConfig), endpointing, False, int(silence_ms)
        )
        cfg = RecognizerConfig(
            ct.sizeof(RecognizerConfig),
            ct.cast(ct.pointer(backend_cfg), ct.c_void_p),
            ct.cast(ct.pointer(model_cfg), ct.c_void_p),
            ct.cast(ct.pointer(streaming_cfg), ct.c_void_p),
            None,
            None,
            ct.cast(ct.pointer(endpoint_cfg), ct.c_void_p),
            None,
            None,
            None,
        )
        status = self._lib.nemo_speech_asr_create(ct.byref(cfg), ct.byref(self._handle))
        self._check(status, "მოდელის ჩატვირთვა ვერ მოხერხდა")

    def _load_library(self, runtime_dir: str) -> ct.CDLL:
        cli = find_nemo_cli(runtime_dir)
        if not cli:
            raise NemoError("NeMo-Speech.cpp runtime ვერ მოიძებნა")
        bin_dir = cli.parent
        dll_path = bin_dir / "nemo_speech_asr_c.dll"
        if not dll_path.is_file():
            raise NemoError(f"ASR DLL ვერ მოიძებნა: {dll_path}")
        if hasattr(os, "add_dll_directory"):
            self._dll_dir_cookie = os.add_dll_directory(str(bin_dir))
        return ct.CDLL(str(dll_path))

    def _bind(self) -> None:
        lib = self._lib
        lib.nemo_speech_asr_create.argtypes = [ct.POINTER(RecognizerConfig), ct.POINTER(ct.c_void_p)]
        lib.nemo_speech_asr_create.restype = ct.c_int
        lib.nemo_speech_asr_destroy.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_recognition_options_default.argtypes = []
        lib.nemo_speech_asr_recognition_options_default.restype = RecognitionOptions
        lib.nemo_speech_asr_recognize_f32.argtypes = [
            ct.c_void_p,
            ct.POINTER(RecognitionOptions),
            ct.POINTER(ct.c_float),
            ct.c_size_t,
            ct.c_int32,
            ct.POINTER(ct.c_void_p),
        ]
        lib.nemo_speech_asr_recognize_f32.restype = ct.c_int
        lib.nemo_speech_asr_streaming_recognize.argtypes = [
            ct.c_void_p,
            ct.POINTER(RecognitionOptions),
            ct.POINTER(ct.c_void_p),
        ]
        lib.nemo_speech_asr_streaming_recognize.restype = ct.c_int
        lib.nemo_speech_asr_stream_push_f32.argtypes = [
            ct.c_void_p, ct.POINTER(ct.c_float), ct.c_size_t, ct.c_int32
        ]
        lib.nemo_speech_asr_stream_push_f32.restype = ct.c_int
        lib.nemo_speech_asr_stream_force_endpoint.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_stream_force_endpoint.restype = ct.c_int
        lib.nemo_speech_asr_stream_finish.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_stream_finish.restype = ct.c_int
        lib.nemo_speech_asr_stream_next.argtypes = [ct.c_void_p, ct.POINTER(ct.c_void_p)]
        lib.nemo_speech_asr_stream_next.restype = ct.c_int
        lib.nemo_speech_asr_stream_close.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_result_is_final.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_result_is_final.restype = ct.c_bool
        lib.nemo_speech_asr_result_audio_processed.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_result_audio_processed.restype = ct.c_float
        lib.nemo_speech_asr_result_alternative_count.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_result_alternative_count.restype = ct.c_size_t
        lib.nemo_speech_asr_result_transcript.argtypes = [ct.c_void_p, ct.c_size_t]
        lib.nemo_speech_asr_result_transcript.restype = ct.c_char_p
        lib.nemo_speech_asr_result_confidence.argtypes = [ct.c_void_p, ct.c_size_t]
        lib.nemo_speech_asr_result_confidence.restype = ct.c_float
        lib.nemo_speech_asr_result_destroy.argtypes = [ct.c_void_p]
        lib.nemo_speech_asr_last_error.argtypes = []
        lib.nemo_speech_asr_last_error.restype = ct.c_char_p
        lib.nemo_speech_asr_version.argtypes = []
        lib.nemo_speech_asr_version.restype = ct.c_char_p

    def _check(self, status: int, context: str) -> None:
        if status == 0:
            return
        raw = self._lib.nemo_speech_asr_last_error()
        detail = raw.decode("utf-8", errors="replace") if raw else f"status={status}"
        raise NemoError(f"{context}: {detail}")

    def _options(self, *, interim: bool = False) -> RecognitionOptions:
        options = self._lib.nemo_speech_asr_recognition_options_default()
        options.language_code = b"ka"
        options.interim_results = interim
        options.enable_automatic_punctuation = self.automatic_punctuation
        return options

    @staticmethod
    def _samples(samples: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)

    def recognize(self, samples: np.ndarray, sample_rate: int) -> RecognitionResult:
        audio = self._samples(samples)
        result = ct.c_void_p()
        options = self._options()
        status = self._lib.nemo_speech_asr_recognize_f32(
            self._handle,
            ct.byref(options),
            audio.ctypes.data_as(ct.POINTER(ct.c_float)),
            audio.size,
            sample_rate,
            ct.byref(result),
        )
        self._check(status, "ტრანსკრიფცია ვერ შესრულდა")
        if not result:
            return RecognitionResult("", True, audio.size / max(sample_rate, 1), 0.0)
        return self._consume_result(result)

    def start_stream(self) -> None:
        if self._stream:
            return
        options = self._options(interim=False)
        status = self._lib.nemo_speech_asr_streaming_recognize(
            self._handle, ct.byref(options), ct.byref(self._stream)
        )
        self._check(status, "Streaming სესია ვერ დაიწყო")

    def push(self, samples: np.ndarray, sample_rate: int) -> list[RecognitionResult]:
        if not self._stream:
            raise NemoError("Streaming სესია დაწყებული არ არის")
        audio = self._samples(samples)
        status = self._lib.nemo_speech_asr_stream_push_f32(
            self._stream,
            audio.ctypes.data_as(ct.POINTER(ct.c_float)),
            audio.size,
            sample_rate,
        )
        self._check(status, "აუდიოს მიწოდება ვერ მოხერხდა")
        return self._drain()

    def force_endpoint(self) -> list[RecognitionResult]:
        if not self._stream:
            return []
        self._check(
            self._lib.nemo_speech_asr_stream_force_endpoint(self._stream),
            "ფრაზის დასრულება ვერ მოხერხდა",
        )
        return self._drain()

    def finish_stream(self) -> list[RecognitionResult]:
        if not self._stream:
            return []
        self._check(
            self._lib.nemo_speech_asr_stream_finish(self._stream),
            "Streaming სესიის დასრულება ვერ მოხერხდა",
        )
        return self._drain()

    def _drain(self) -> list[RecognitionResult]:
        results: list[RecognitionResult] = []
        while self._stream:
            ptr = ct.c_void_p()
            status = self._lib.nemo_speech_asr_stream_next(self._stream, ct.byref(ptr))
            self._check(status, "ASR შედეგის მიღება ვერ მოხერხდა")
            if not ptr:
                break
            results.append(self._consume_result(ptr))
        return results

    def _consume_result(self, result: ct.c_void_p) -> RecognitionResult:
        try:
            count = self._lib.nemo_speech_asr_result_alternative_count(result)
            raw = self._lib.nemo_speech_asr_result_transcript(result, 0) if count else b""
            return RecognitionResult(
                transcript=raw.decode("utf-8", errors="replace") if raw else "",
                is_final=bool(self._lib.nemo_speech_asr_result_is_final(result)),
                audio_seconds=float(self._lib.nemo_speech_asr_result_audio_processed(result)),
                confidence=float(self._lib.nemo_speech_asr_result_confidence(result, 0)) if count else 0.0,
            )
        finally:
            self._lib.nemo_speech_asr_result_destroy(result)

    def recognize_wav(self, path: Path) -> RecognitionResult:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
        if width != 2:
            raise NemoError("Diagnostics მხარს უჭერს PCM 16-bit WAV ფაილს")
        pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        return self.recognize(pcm, rate)

    def close_stream(self) -> None:
        if self._stream:
            self._lib.nemo_speech_asr_stream_close(self._stream)
            self._stream = ct.c_void_p()

    def close(self) -> None:
        self.close_stream()
        if self._handle:
            self._lib.nemo_speech_asr_destroy(self._handle)
            self._handle = ct.c_void_p()
        if self._dll_dir_cookie is not None:
            self._dll_dir_cookie.close()
            self._dll_dir_cookie = None

    def __enter__(self) -> "NemoNativeRecognizer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

