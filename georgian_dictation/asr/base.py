from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class RecognitionResult:
    transcript: str
    is_final: bool = True
    audio_seconds: float = 0.0
    confidence: float = 0.0


ResultCallback = Callable[[RecognitionResult], None]


class ASREngine(ABC):
    supports_streaming: bool = False

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def transcribe_segment(
        self, samples: np.ndarray, sample_rate: int
    ) -> RecognitionResult: ...

    @abstractmethod
    def health_check(self) -> tuple[bool, str]: ...

    def transcribe_file(self, path: Path) -> RecognitionResult:
        raise NotImplementedError

