from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from google.auth.exceptions import DefaultCredentialsError

import georgian_dictation.ai.gemini_client as gemini_module
from georgian_dictation.ai.gemini_client import (
    VERTEX_LOCATION,
    GeminiClient,
    GeminiError,
    GeminiModel,
    check_adc,
    rank_models,
)
from georgian_dictation.ai.processor import (
    AIProcessor,
    ProcessingResult,
    apply_failure_action,
)
from georgian_dictation.ai.prompts import AI_COMMAND_PROMPT, SMART_CORRECTION_PROMPT
from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.controller import ApplicationController
from georgian_dictation.ui.overlay import ListeningOverlay


TEST_VERTEX_PROJECT = "georgian-dictation-test-project"


class FakeClient:
    calls: list[tuple[str, str, str, float]] = []
    output = "გასწორებული ტექსტი."
    error: Exception | None = None

    def __init__(self, *, project: str, location: str, timeout_seconds: int) -> None:
        self.project = project
        self.location = location
        self.timeout_seconds = timeout_seconds

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def generate(
        self,
        transcript: str,
        *,
        system_instruction: str,
        model: str,
        temperature: float,
    ) -> tuple[str, str]:
        self.calls.append((transcript, system_instruction, model, temperature))
        if self.error:
            raise self.error
        return self.output, model or "gemini-test-flash"


def setup_function() -> None:
    FakeClient.calls = []
    FakeClient.output = "გასწორებული ტექსტი."
    FakeClient.error = None


def test_plain_dictation_never_calls_gemini() -> None:
    result = AIProcessor(FakeClient).process("უცვლელი ტექსტი", mode="off")
    assert result.processed_text == "უცვლელი ტექსტი"
    assert result.status == "off"
    assert not FakeClient.calls


@pytest.mark.parametrize(
    ("stt_engine", "mode"),
    [
        ("deepgram-nova-3-ka", "off"),
        ("deepgram-nova-3-ka", "smart_correction"),
        ("deepgram-nova-3-ka", "ai_command"),
        ("georgian-fastconformer-accurate", "smart_correction"),
        ("georgian-fastconformer-accurate", "ai_command"),
        ("georgian-streaming-80ms", "smart_correction"),
        ("georgian-streaming-80ms", "ai_command"),
    ],
)
def test_ai_layer_is_independent_of_selected_stt(stt_engine: str, mode: str) -> None:
    raw = "ტესტური ტრანსკრიპტი"
    result = AIProcessor(FakeClient).process(
        raw, mode=mode, model="gemini-test-flash"
    )
    assert result.status == ("off" if mode == "off" else "success")
    assert result.raw_transcript == raw
    assert stt_engine


@pytest.mark.parametrize(
    "transcript",
    [
        "Завтра не смогу прийти. Напиши это по-грузински",
        "ეს დამიწერე მეილის ფორმატში",
        "Rewrite this as a short professional email",
    ],
)
def test_ai_command_accepts_russian_georgian_and_english(transcript: str) -> None:
    FakeClient.output = "მოთხოვნილი საბოლოო ტექსტი"
    result = AIProcessor(FakeClient).process(
        transcript, mode="ai_command", model="gemini-test-flash"
    )
    assert result.status == "success"
    assert result.processed_text == "მოთხოვნილი საბოლოო ტექსტი"
    assert "no explanation" in FakeClient.calls[0][1]


def test_smart_correction_prompt_and_low_temperature() -> None:
    result = AIProcessor(FakeClient).process(
        "ეს ტექსტი გასასწორებელია",
        mode="smart_correction",
        model="gemini-test-flash",
        aggressiveness="conservative",
    )
    assert result.status == "success"
    assert FakeClient.calls[0][3] == 0.0
    prompt = FakeClient.calls[0][1]
    for protected in ("names", "numbers", "dates", "URLs", "email"):
        assert protected in prompt


def test_protected_number_change_forces_raw_fallback() -> None:
    FakeClient.output = "შეხვედრა 6 საათზეა."
    raw = "შეხვედრა 5 საათზეა"
    result = AIProcessor(FakeClient).process(
        raw, mode="smart_correction", model="gemini-test-flash"
    )
    assert result.status == "failed"
    assert apply_failure_action(result, "insert_raw") == (raw, False)


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("insert_raw", ("ნათქვამი ტექსტი", False)),
        ("show_error_keep", (None, False)),
        ("copy_raw", (None, True)),
    ],
)
def test_all_failure_policies_keep_raw(action: str, expected: tuple[str | None, bool]) -> None:
    failed = ProcessingResult(
        "ნათქვამი ტექსტი", "ნათქვამი ტექსტი", "smart_correction", "m", 1.0, "failed", "offline"
    )
    assert apply_failure_action(failed, action) == expected
    assert failed.raw_transcript == "ნათქვამი ტექსტი"


def test_unavailable_adc_or_vertex_error_returns_raw() -> None:
    for message in ("network unavailable", "Google ADC authorization failed"):
        FakeClient.error = RuntimeError(message)
        result = AIProcessor(FakeClient).process(
            "არ დაიკარგოს", mode="smart_correction", model="m"
        )
        assert result.status == "failed"
        assert result.processed_text == "არ დაიკარგოს"


def test_missing_adc_during_client_creation_returns_raw() -> None:
    class MissingADCClient:
        def __init__(self, **_kwargs) -> None:
            raise GeminiError(
                "Google Application Default Credentials ვერ მოიძებნა. გაუშვით: "
                "gcloud auth application-default login"
            )

    result = AIProcessor(MissingADCClient).process(
        "RAW არ დაიკარგოს", mode="smart_correction", model="gemini-test-flash"
    )
    assert result.status == "failed"
    assert result.raw_transcript == "RAW არ დაიკარგოს"
    assert result.processed_text == "RAW არ დაიკარგოს"
    assert "gcloud auth application-default login" in result.error


def test_secret_is_redacted_from_worker_error() -> None:
    secret = "ya29.TESTSECRET01234567890123456789"
    FakeClient.error = RuntimeError(f"request failed Bearer {secret}")
    result = AIProcessor(FakeClient).process(
        "ტექსტი", mode="smart_correction", model="m"
    )
    assert secret not in result.error
    assert "REDACTED" in result.error


def test_prompt_constants_are_separate_and_extensible() -> None:
    assert "strict multilingual" in SMART_CORRECTION_PROMPT
    assert "natural-language" in AI_COMMAND_PROMPT
    assert "no explanation" in AI_COMMAND_PROMPT


def test_dynamic_model_ranking_prefers_current_flash() -> None:
    ranked = rank_models(
        [
            GeminiModel("gemini-pro-custom", "Pro"),
            GeminiModel("gemini-2.5-flash-lite", "Flash Lite"),
            GeminiModel("gemini-3.8-flash", "Flash"),
        ]
    )
    assert [item.id for item in ranked][:2] == [
        "gemini-3.8-flash",
        "gemini-2.5-flash-lite",
    ]


def test_selected_model_unavailable_uses_dynamic_fallback() -> None:
    class Models:
        def generate_content(self, *, model, contents, config):
            if model == "gone-model":
                raise RuntimeError("404 model not found")
            return SimpleNamespace(text="კარგია")

    client = GeminiClient.__new__(GeminiClient)
    client._client = SimpleNamespace(models=Models())
    output, used = client.generate(
        "ტექსტი", system_instruction="test", model="gone-model"
    )
    assert output == "კარგია"
    assert used == "gemini-3.8-flash"


def test_adc_is_discovered_and_refreshed_without_manual_file_read(monkeypatch) -> None:
    class Credentials:
        valid = False
        quota_project_id = TEST_VERTEX_PROJECT

        def refresh(self, _request) -> None:
            self.valid = True

    credentials = Credentials()

    def fake_default(*, scopes, quota_project_id):
        assert scopes == [gemini_module.GOOGLE_CLOUD_SCOPE]
        assert quota_project_id == TEST_VERTEX_PROJECT
        return credentials, TEST_VERTEX_PROJECT

    monkeypatch.setattr(gemini_module.google.auth, "default", fake_default)
    status = check_adc(project=TEST_VERTEX_PROJECT)
    assert status.authenticated
    assert status.detected_project == TEST_VERTEX_PROJECT
    assert status.quota_project == TEST_VERTEX_PROJECT
    assert status.vertex_project == TEST_VERTEX_PROJECT


def test_missing_adc_has_human_actionable_message(monkeypatch) -> None:
    def missing(**_kwargs):
        raise DefaultCredentialsError("missing")

    monkeypatch.setattr(gemini_module.google.auth, "default", missing)
    with pytest.raises(GeminiError, match="gcloud auth application-default login"):
        check_adc(project=TEST_VERTEX_PROJECT)


def test_vertex_sdk_client_uses_adc_project_and_global_without_api_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class SDKClient:
        def close(self) -> None:
            return None

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SDKClient()

    monkeypatch.setattr(gemini_module.genai, "Client", fake_client)
    with GeminiClient(project=TEST_VERTEX_PROJECT, timeout_seconds=11):
        pass
    assert captured["vertexai"] is True
    assert captured["project"] == TEST_VERTEX_PROJECT
    assert captured["location"] == VERTEX_LOCATION
    assert "api_key" not in captured
    assert "credentials" not in captured


def test_long_dictation_segments_keep_order(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    settings = SettingsStore(tmp_path / "settings.json")
    settings.set("ai", "mode", "smart_correction")

    class SlowProcessor:
        def process(self, raw, **_kwargs):
            time.sleep(0.015)
            return ProcessingResult(raw, f"{raw}!", "smart_correction", "fake", 0.015, "success")

    controller = ApplicationController(settings, object(), ListeningOverlay())
    controller.ai_processor = SlowProcessor()
    inserted: list[str] = []
    controller.inserter.insert = lambda text, _method: inserted.append(text.strip()) or True
    for segment in ("პირველი", "მეორე", "მესამე", "მეოთხე"):
        controller._on_result(segment)
    deadline = time.monotonic() + 3
    while controller._pending_ai and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    controller.shutdown()
    assert inserted == ["პირველი!", "მეორე!", "მესამე!", "მეოთხე!"]
