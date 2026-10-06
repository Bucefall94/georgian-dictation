"""Speech-recognition engine abstractions."""

from .base import ASREngine, RecognitionResult
from .nemo_native import NemoNativeRecognizer

__all__ = ["ASREngine", "RecognitionResult", "NemoNativeRecognizer"]

