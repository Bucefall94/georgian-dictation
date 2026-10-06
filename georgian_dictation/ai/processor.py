from __future__ import annotations

import time
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from georgian_dictation.ai.gemini_client import (
    VERTEX_LOCATION,
    GeminiClient,
)
from georgian_dictation.ai.prompts import system_prompt


@dataclass(frozen=True)
class ProcessingResult:
    raw_transcript: str
    processed_text: str
    mode: str
    model: str
    latency_seconds: float
    status: str
    error: str = ""


ClientFactory = Callable[..., GeminiClient]


class AIProcessor:
    def __init__(self, client_factory: ClientFactory = GeminiClient) -> None:
        self._client_factory = client_factory

    def process(
        self,
        raw_transcript: str,
        *,
        mode: str,
        model: str = "",
        timeout_seconds: int = 20,
        aggressiveness: str = "conservative",
        project: str | None = None,
        location: str = VERTEX_LOCATION,
    ) -> ProcessingResult:
        raw = raw_transcript.strip()
        if not raw:
            return ProcessingResult(raw, raw, mode, model, 0.0, "empty")
        if mode == "off":
            return ProcessingResult(raw, raw, mode, "", 0.0, "off")
        started = time.perf_counter()
        temperature = {
            "conservative": 0.0,
            "balanced": 0.1,
            "strong": 0.2,
        }.get(aggressiveness, 0.0)
        if mode == "ai_command":
            temperature = 0.2
        try:
            with self._client_factory(
                project=project,
                location=location,
                timeout_seconds=timeout_seconds,
            ) as client:
                output, used_model = client.generate(
                    raw,
                    system_instruction=system_prompt(mode, aggressiveness),
                    model=model,
                    temperature=temperature,
                )
            if mode == "smart_correction" and _protected_tokens(raw) != _protected_tokens(output):
                raise RuntimeError(
                    "Gemini-მ დაცული მნიშვნელობა (რიცხვი, თარიღი, URL ან email) შეცვალა"
                )
            return ProcessingResult(
                raw, output, mode, used_model, time.perf_counter() - started, "success"
            )
        except Exception as exc:
            error = str(exc)
            error = re.sub(r"(?i)(?:key|api_key)=[^&\s]+", "key=[REDACTED]", error)
            error = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", error)
            error = re.sub(
                r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", error
            )
            return ProcessingResult(
                raw, raw, mode, model, time.perf_counter() - started, "failed", error
            )


def _protected_tokens(text: str) -> Counter[str]:
    patterns = (
        r"https?://[^\s<>\]\[()]+",
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"[-+]?\d[\d.,:/-]*",
    )
    values: list[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return Counter(value.rstrip(".,;!?").casefold() for value in values)


def apply_failure_action(result: ProcessingResult, action: str) -> tuple[str | None, bool]:
    """Returns (text to insert, copy_raw_to_clipboard). RAW is never discarded internally."""
    if result.status != "failed":
        return result.processed_text, False
    if action == "copy_raw":
        return None, True
    if action == "show_error_keep":
        return None, False
    return result.raw_transcript, False
