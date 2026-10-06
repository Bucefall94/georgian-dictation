from __future__ import annotations

import json
import urllib.parse

import numpy as np
import pytest

from georgian_dictation.asr.deepgram import (
    DeepgramError,
    DeepgramNova3Recognizer,
    _linear16,
    _query,
)


def test_deepgram_query_is_pinned_to_nova3_georgian() -> None:
    params = urllib.parse.parse_qs(
        _query(streaming=True, punctuation=True, silence_ms=1200)
    )
    assert params["model"] == ["nova-3"]
    assert params["language"] == ["ka"]
    assert params["encoding"] == ["linear16"]
    assert params["sample_rate"] == ["16000"]
    assert params["mip_opt_out"] == ["true"]
    assert params["interim_results"] == ["true"]


def test_audio_is_resampled_to_16khz_linear16() -> None:
    source = np.zeros(4800, dtype=np.float32)
    assert len(_linear16(source, 48000)) == 1600 * 2


def test_prerecorded_response_is_parsed_without_persisting_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {"transcript": "ქართული ტექსტი", "confidence": 0.97}
                                ]
                            }
                        ]
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    recognizer = DeepgramNova3Recognizer("test-key")
    result = recognizer.transcribe_segment(np.zeros(1600, dtype=np.float32), 16000)
    assert result.transcript == "ქართული ტექსტი"
    assert result.confidence == pytest.approx(0.97)
    assert "model=nova-3" in str(captured["url"])
    assert "language=ka" in str(captured["url"])
    assert captured["authorization"] == "Token test-key"


def test_empty_api_key_is_rejected() -> None:
    with pytest.raises(DeepgramError, match="API key"):
        DeepgramNova3Recognizer("   ")
