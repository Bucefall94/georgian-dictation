from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class InputDevice:
    id: int | None
    name: str
    hostapi: str
    default_sample_rate: int
    channels: int

    @property
    def label(self) -> str:
        suffix = f" · {self.hostapi}" if self.hostapi else ""
        return f"{self.name}{suffix}"


def list_input_devices() -> list[InputDevice]:
    hostapis = sd.query_hostapis()
    devices: list[InputDevice] = []
    default_input = sd.default.device[0] if sd.default.device else -1
    for index, info in enumerate(sd.query_devices()):
        if int(info["max_input_channels"]) < 1:
            continue
        host_index = int(info["hostapi"])
        host_name = hostapis[host_index]["name"] if host_index < len(hostapis) else ""
        name = str(info["name"])
        if index == default_input:
            name += " (ნაგულისხმევი)"
        devices.append(
            InputDevice(
                id=index,
                name=name,
                hostapi=str(host_name),
                default_sample_rate=int(float(info["default_samplerate"])),
                channels=int(info["max_input_channels"]),
            )
        )
    return devices


class AudioCapture(QObject):
    level_changed = Signal(float)
    error = Signal(str)
    active_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._stream: sd.InputStream | None = None
        self._consumer: Callable[[np.ndarray, int], None] | None = None
        self.sample_rate = 16000
        self.log = logging.getLogger(__name__)

    @property
    def active(self) -> bool:
        return self._stream is not None and self._stream.active

    def start(
        self,
        device_id: int | None,
        consumer: Callable[[np.ndarray, int], None],
    ) -> int:
        self.stop()
        self._consumer = consumer
        try:
            info = sd.query_devices(device_id, "input")
            self.sample_rate = int(float(info["default_samplerate"]))
            blocksize = max(256, int(self.sample_rate * 0.16))
            self._stream = sd.InputStream(
                device=device_id,
                channels=1,
                samplerate=self.sample_rate,
                blocksize=blocksize,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            self._stream.start()
            self.active_changed.emit(True)
            return self.sample_rate
        except Exception as exc:
            self._stream = None
            self._consumer = None
            message = f"მიკროფონის გახსნა ვერ მოხერხდა: {exc}"
            self.log.exception(message)
            self.error.emit(message)
            raise RuntimeError(message) from exc

    def _callback(self, indata: np.ndarray, _frames: int, _time: object, status: object) -> None:
        if status:
            self.log.warning("Audio callback status: %s", status)
        audio = np.ascontiguousarray(indata[:, 0], dtype=np.float32).copy()
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if audio.size else 0.0
        visual_level = min(1.0, max(0.0, rms * 12.0))
        self.level_changed.emit(visual_level)
        if self._consumer:
            try:
                self._consumer(audio, self.sample_rate)
            except Exception:
                self.log.exception("Audio consumer failed")

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self._consumer = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                self.log.exception("Microphone shutdown failed")
        self.level_changed.emit(0.0)
        self.active_changed.emit(False)

