from pathlib import Path

import numpy as np
import pytest

from georgian_dictation.asr.nemo_native import NemoNativeRecognizer
from georgian_dictation.asr.runtime import inspect_runtime


MODEL = Path.home() / "NemoSpeechModels" / "georgian-fastconformer-streaming.gguf"


@pytest.mark.skipif(not MODEL.is_file(), reason="local Georgian streaming model is absent")
def test_native_cuda_streaming_smoke() -> None:
    status = inspect_runtime()
    assert status.available
    backend = "cuda" if status.cuda_available else "cpu"
    with NemoNativeRecognizer(MODEL, backend=backend, endpointing=True) as recognizer:
        recognizer.start_stream()
        recognizer.push(np.zeros(2560, dtype=np.float32), 16000)
        finals = recognizer.finish_stream()
    assert finals
    assert finals[-1].is_final

