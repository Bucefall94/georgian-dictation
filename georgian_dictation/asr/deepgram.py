from __future__ import annotations

import io
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Callable

import numpy as np
import websocket

from georgian_dictation import __version__

from .base import ASREngine, RecognitionResult


DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_STREAM_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_MODEL = "nova-3"
DEEPGRAM_LANGUAGE = "ka"


class DeepgramError(RuntimeError):
    pass


def _query(*, streaming: bool, punctuation: bool, silence_ms: int = 1200) -> str:
    values: dict[str, str] = {
        "model": DEEPGRAM_MODEL,
        "language": DEEPGRAM_LANGUAGE,
        "punctuate": str(bool(punctuation)).lower(),
        "smart_format": str(bool(punctuation)).lower(),
        "mip_opt_out": "true",
    }
    if streaming:
        values.update(
            {
                "encoding": "linear16",
                "sample_rate": "16000",
                "channels": "1",
                "interim_results": "true",
                "endpointing": str(max(10, int(silence_ms))),
                "utterance_end_ms": str(max(1000, int(silence_ms))),
                "vad_events": "true",
            }
        )
    return urllib.parse.urlencode(values)


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    audio = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
    if not audio.size or source_rate == target_rate:
        return audio
    if source_rate <= 0:
        raise DeepgramError("აუდიოს sample rate არასწორია")
    target_size = max(1, round(audio.size * target_rate / source_rate))
    source_positions = np.arange(audio.size, dtype=np.float64)
    target_positions = np.linspace(0, audio.size - 1, target_size, dtype=np.float64)
    return np.interp(target_positions, source_positions, audio).astype(np.float32)


def _linear16(samples: np.ndarray, sample_rate: int) -> bytes:
    audio = _resample(samples, sample_rate)
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = _linear16(samples, sample_rate)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm)
    return output.getvalue()


def _friendly_http_error(error: urllib.error.HTTPError) -> DeepgramError:
    if error.code in (401, 403):
        return DeepgramError("Deepgram API key არასწორია ან საჭირო უფლება არ აქვს")
    if error.code == 429:
        return DeepgramError("Deepgram ლიმიტი ამოიწურა ან მოთხოვნები დროებით შეზღუდულია")
    return DeepgramError(f"Deepgram API-მ დააბრუნა HTTP {error.code}")


class DeepgramNova3Recognizer(ASREngine):
    supports_streaming = True

    def __init__(
        self,
        api_key: str,
        *,
        automatic_punctuation: bool = True,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key.strip()
        if not self.api_key:
            raise DeepgramError("Deepgram API key შენახული არ არის")
        self.automatic_punctuation = automatic_punctuation
        self.timeout = timeout
        self.log = logging.getLogger(__name__)
        self._stream: DeepgramStreamingSession | None = None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.close()

    def health_check(self) -> tuple[bool, str]:
        silence = np.zeros(8000, dtype=np.float32)
        try:
            self.transcribe_segment(silence, 16000)
            return True, "Deepgram Nova-3 / ka კავშირი მუშაობს"
        except DeepgramError as exc:
            return False, str(exc)

    def transcribe_segment(
        self, samples: np.ndarray, sample_rate: int
    ) -> RecognitionResult:
        return self._transcribe_bytes(
            _wav_bytes(samples, sample_rate),
            content_type="audio/wav",
            audio_seconds=len(samples) / max(sample_rate, 1),
        )

    def transcribe_file(self, path: Path) -> RecognitionResult:
        wav_path = Path(path)
        try:
            with wave.open(str(wav_path), "rb") as wav_file:
                audio_seconds = wav_file.getnframes() / max(wav_file.getframerate(), 1)
        except (wave.Error, OSError) as exc:
            raise DeepgramError(f"WAV ფაილი ვერ გაიხსნა: {exc}") from exc
        return self._transcribe_bytes(
            wav_path.read_bytes(),
            content_type="audio/wav",
            audio_seconds=audio_seconds,
        )

    def _transcribe_bytes(
        self, payload: bytes, *, content_type: str, audio_seconds: float
    ) -> RecognitionResult:
        url = f"{DEEPGRAM_LISTEN_URL}?{_query(streaming=False, punctuation=self.automatic_punctuation)}"
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": content_type,
                "Accept": "application/json",
                "User-Agent": f"GeorgianDictation/{__version__}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise _friendly_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise DeepgramError(f"Deepgram-თან კავშირი ვერ დამყარდა: {exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DeepgramError("Deepgram-მა არასწორი პასუხი დააბრუნა") from exc
        try:
            alternative = body["results"]["channels"][0]["alternatives"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepgramError("Deepgram-ის პასუხში transcript ვერ მოიძებნა") from exc
        return RecognitionResult(
            transcript=str(alternative.get("transcript", "")),
            is_final=True,
            audio_seconds=audio_seconds,
            confidence=float(alternative.get("confidence", 0.0) or 0.0),
        )

    def start_stream(
        self,
        on_result: Callable[[RecognitionResult], None],
        on_error: Callable[[str], None],
        *,
        silence_ms: int,
    ) -> None:
        if self._stream:
            return
        self._stream = DeepgramStreamingSession(
            self.api_key,
            on_result,
            on_error,
            automatic_punctuation=self.automatic_punctuation,
            silence_ms=silence_ms,
        )
        self._stream.open()

    def push(self, samples: np.ndarray, sample_rate: int) -> None:
        if not self._stream:
            raise DeepgramError("Deepgram streaming სესია დაწყებული არ არის")
        self._stream.send_audio(samples, sample_rate)

    def finish_stream(self) -> None:
        if self._stream:
            self._stream.finish()

    def close_stream(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None

    def close(self) -> None:
        self.close_stream()

    def __enter__(self) -> "DeepgramNova3Recognizer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class DeepgramStreamingSession:
    def __init__(
        self,
        api_key: str,
        on_result: Callable[[RecognitionResult], None],
        on_error: Callable[[str], None],
        *,
        automatic_punctuation: bool,
        silence_ms: int,
    ) -> None:
        self.api_key = api_key
        self.on_result = on_result
        self.on_error = on_error
        self.automatic_punctuation = automatic_punctuation
        self.silence_ms = silence_ms
        self._socket: websocket.WebSocket | None = None
        self._receiver: threading.Thread | None = None
        self._closing = threading.Event()
        self._finalized = threading.Event()
        self._error: str | None = None

    def open(self) -> None:
        url = f"{DEEPGRAM_STREAM_URL}?{_query(streaming=True, punctuation=self.automatic_punctuation, silence_ms=self.silence_ms)}"
        try:
            self._socket = websocket.create_connection(
                url,
                header=[
                    f"Authorization: Token {self.api_key}",
                    f"User-Agent: GeorgianDictation/{__version__}",
                ],
                timeout=15,
                enable_multithread=True,
            )
            self._socket.settimeout(0.5)
        except websocket.WebSocketBadStatusException as exc:
            if exc.status_code in (401, 403):
                raise DeepgramError(
                    "Deepgram API key არასწორია ან საჭირო უფლება არ აქვს"
                ) from exc
            raise DeepgramError(
                f"Deepgram streaming კავშირი უარყოფილია (HTTP {exc.status_code})"
            ) from exc
        except (OSError, websocket.WebSocketException) as exc:
            raise DeepgramError(f"Deepgram streaming კავშირი ვერ გაიხსნა: {exc}") from exc
        self._receiver = threading.Thread(
            target=self._receive_loop, name="DeepgramReceiver", daemon=True
        )
        self._receiver.start()

    def send_audio(self, samples: np.ndarray, sample_rate: int) -> None:
        if self._error:
            raise DeepgramError(self._error)
        if not self._socket:
            raise DeepgramError("Deepgram streaming კავშირი დახურულია")
        try:
            self._socket.send_binary(_linear16(samples, sample_rate))
        except websocket.WebSocketException as exc:
            raise DeepgramError(f"აუდიო Deepgram-ს ვერ გადაეცა: {exc}") from exc

    def finish(self) -> None:
        if not self._socket:
            return
        self._closing.set()
        try:
            self._socket.send(json.dumps({"type": "Finalize"}))
            self._finalized.wait(timeout=4.0)
            self._socket.send(json.dumps({"type": "CloseStream"}))
            time.sleep(0.05)
        except websocket.WebSocketException:
            pass
        finally:
            self.close()

    def close(self) -> None:
        self._closing.set()
        socket, self._socket = self._socket, None
        if socket:
            try:
                socket.close()
            except websocket.WebSocketException:
                pass
        receiver, self._receiver = self._receiver, None
        if receiver and receiver is not threading.current_thread():
            receiver.join(timeout=2.0)

    def _receive_loop(self) -> None:
        assert self._socket is not None
        while self._socket:
            try:
                raw = self._socket.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException:
                break
            except websocket.WebSocketException as exc:
                if not self._closing.is_set():
                    self._report_error(f"Deepgram streaming შეცდომა: {exc}")
                break
            if not raw:
                break
            if isinstance(raw, bytes):
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message_type = message.get("type")
            if message_type == "Error":
                self._report_error(
                    "Deepgram შეცდომა: " + str(message.get("description") or message.get("message") or "უცნობი შეცდომა")
                )
                break
            if message_type != "Results":
                continue
            if message.get("from_finalize"):
                self._finalized.set()
            if not message.get("is_final"):
                continue
            try:
                alternative = message["channel"]["alternatives"][0]
            except (KeyError, IndexError, TypeError):
                continue
            transcript = str(alternative.get("transcript", "")).strip()
            if transcript:
                self.on_result(
                    RecognitionResult(
                        transcript=transcript,
                        is_final=True,
                        audio_seconds=float(message.get("duration", 0.0) or 0.0),
                        confidence=float(alternative.get("confidence", 0.0) or 0.0),
                    )
                )

    def _report_error(self, message: str) -> None:
        self._error = message
        self.on_error(message)
