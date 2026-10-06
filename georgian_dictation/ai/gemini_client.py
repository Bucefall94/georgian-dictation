from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable

import google.auth
from google import genai
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.auth.transport.requests import Request
from google.genai import types


VERTEX_PROJECT_ENV = "GEORGIAN_DICTATION_VERTEX_PROJECT"
VERTEX_LOCATION_ENV = "GEORGIAN_DICTATION_VERTEX_LOCATION"
# Kept as a compatibility export. Public builds never contain a private project ID.
VERTEX_PROJECT_ID = os.getenv(VERTEX_PROJECT_ENV, "").strip()
VERTEX_LOCATION = os.getenv(VERTEX_LOCATION_ENV, "global").strip() or "global"
GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GeminiError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeminiModel:
    id: str
    display_name: str


@dataclass(frozen=True)
class ADCStatus:
    authenticated: bool
    detected_project: str
    quota_project: str
    vertex_project: str


# Vertex global does not expose the public Gemini Developer API model-list endpoint.
# Keep every supported model ID in this one location and validate the selected/default
# model with a real, tiny generation request.
SUPPORTED_VERTEX_MODELS = (
    GeminiModel("gemini-3.8-flash", "Gemini 3.8 Flash"),
    GeminiModel("gemini-3.7-flash", "Gemini 3.7 Flash"),
    GeminiModel("gemini-3.6-flash", "Gemini 3.6 Flash"),
    GeminiModel("gemini-3.5-flash", "Gemini 3.5 Flash"),
    GeminiModel("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
    GeminiModel("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite"),
    GeminiModel("gemini-2.5-flash", "Gemini 2.5 Flash"),
    GeminiModel("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite"),
)


def normalize_model_name(name: str) -> str:
    return name.removeprefix("models/").strip()


def rank_models(models: Iterable[GeminiModel]) -> list[GeminiModel]:
    priority = {model.id: index for index, model in enumerate(SUPPORTED_VERTEX_MODELS)}
    return sorted(models, key=lambda model: (priority.get(model.id, 999), model.id))


def _redact(message: str) -> str:
    value = re.sub(r"(?i)(?:key|api_key)=[^&\s]+", "key=[REDACTED]", message)
    value = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", value)
    value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", value)
    return value


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, DefaultCredentialsError):
        return (
            "Google Application Default Credentials ვერ მოიძებნა. გაუშვით: "
            "gcloud auth application-default login"
        )
    message = _redact(str(exc).strip() or exc.__class__.__name__)
    lowered = message.casefold()
    if isinstance(exc, RefreshError) or "invalid_grant" in lowered or "reauth" in lowered:
        return (
            "Google ADC ვადაგასულია ან ხელახალ ავტორიზაციას ითხოვს. გაუშვით: "
            "gcloud auth application-default login"
        )
    if "401" in lowered or "unauth" in lowered:
        return "Google ADC ავტორიზაცია ვერ დადასტურდა"
    if "403" in lowered or "permission_denied" in lowered or "permission denied" in lowered:
        return (
            "Vertex AI-ზე წვდომა აკრძალულია. შეამოწმეთ project-ის IAM უფლებები და "
            "aiplatform.googleapis.com API"
        )
    if "429" in lowered or "quota" in lowered or "resource_exhausted" in lowered:
        return "Vertex AI quota ან rate limit ამოიწურა; სცადეთ მოგვიანებით"
    if "timeout" in lowered or "timed out" in lowered or "deadline" in lowered:
        return "Vertex AI-ის პასუხის მოლოდინის დრო ამოიწურა"
    if "404" in lowered or "not found" in lowered:
        return "არჩეული Gemini მოდელი Vertex AI-ზე ხელმისაწვდომი არ არის"
    if any(token in lowered for token in ("connection", "network", "dns", "unreachable")):
        return "Vertex AI-სთან ქსელური კავშირი ვერ დამყარდა"
    return f"Vertex AI მოთხოვნა ვერ შესრულდა: {message[:400]}"


def _is_model_unavailable(exc: Exception) -> bool:
    lowered = str(exc).casefold()
    return any(
        token in lowered
        for token in ("404", "not found", "not_found", "unsupported model")
    )


def _clean_response(text: str) -> str:
    value = text.strip()
    fenced = re.fullmatch(
        r"```(?:text|markdown)?\s*(.*?)\s*```", value, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        value = fenced.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def _configured_project(project: str | None = None) -> str:
    return (project or "").strip() or os.getenv(VERTEX_PROJECT_ENV, "").strip()


def _missing_project_error() -> GeminiError:
    return GeminiError(
        "Vertex AI project ვერ განისაზღვრა. დააყენეთ "
        f"{VERTEX_PROJECT_ENV}=YOUR_PROJECT_ID ან გამოიყენეთ ADC, რომელსაც project/quota project აქვს."
    )


def resolve_vertex_project(project: str | None = None) -> str:
    """Resolve a Vertex project without embedding a maintainer-specific project ID."""
    configured = _configured_project(project)
    if configured:
        return configured
    try:
        credentials, detected_project = google.auth.default(scopes=[GOOGLE_CLOUD_SCOPE])
    except Exception as exc:
        raise GeminiError(friendly_error(exc)) from exc
    resolved = (
        (detected_project or "").strip()
        or (getattr(credentials, "quota_project_id", "") or "").strip()
    )
    if not resolved:
        raise _missing_project_error()
    return resolved


def check_adc(
    *, project: str | None = None, refresh: bool = True
) -> ADCStatus:
    """Detect ADC through google-auth; never reads credential JSON directly."""
    configured = _configured_project(project)
    try:
        credentials, detected_project = google.auth.default(
            scopes=[GOOGLE_CLOUD_SCOPE],
            quota_project_id=configured or None,
        )
        quota_project = (getattr(credentials, "quota_project_id", "") or "").strip()
        vertex_project = configured or (detected_project or "").strip() or quota_project
        if not vertex_project:
            raise _missing_project_error()
        if refresh:
            credentials.refresh(Request())
            if not credentials.valid:
                raise RefreshError("ADC refresh completed without valid credentials")
        return ADCStatus(
            authenticated=True,
            detected_project=(detected_project or "").strip(),
            quota_project=quota_project,
            vertex_project=vertex_project,
        )
    except Exception as exc:
        if isinstance(exc, GeminiError):
            raise
        raise GeminiError(friendly_error(exc)) from exc


class GeminiClient:
    """Transcript-only Gemini client backed by Vertex AI and auto-discovered ADC."""

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str = VERTEX_LOCATION,
        timeout_seconds: int = 20,
    ) -> None:
        timeout_ms = max(5, min(120, int(timeout_seconds))) * 1000
        resolved_project = resolve_vertex_project(project)
        try:
            # No API key and no credential-file path: google-auth discovers ADC itself.
            self._client = genai.Client(
                vertexai=True,
                project=resolved_project,
                location=location,
                http_options=types.HttpOptions(
                    api_version="v1",
                    timeout=timeout_ms,
                ),
            )
        except Exception as exc:
            raise GeminiError(friendly_error(exc)) from exc

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def __enter__(self) -> "GeminiClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def list_text_models(self) -> list[GeminiModel]:
        return list(SUPPORTED_VERTEX_MODELS)

    def generate(
        self,
        transcript: str,
        *,
        system_instruction: str,
        model: str,
        temperature: float = 0.0,
    ) -> tuple[str, str]:
        chosen = normalize_model_name(model) or SUPPORTED_VERTEX_MODELS[0].id
        try:
            return (
                self._generate_once(
                    transcript, system_instruction, chosen, temperature
                ),
                chosen,
            )
        except Exception as first:
            if not _is_model_unavailable(first):
                if isinstance(first, GeminiError):
                    raise
                raise GeminiError(friendly_error(first)) from first
            last_error: Exception = first
            for fallback in SUPPORTED_VERTEX_MODELS:
                if fallback.id == chosen:
                    continue
                try:
                    return (
                        self._generate_once(
                            transcript,
                            system_instruction,
                            fallback.id,
                            temperature,
                        ),
                        fallback.id,
                    )
                except Exception as exc:
                    last_error = exc
                    if not _is_model_unavailable(exc):
                        break
            if isinstance(last_error, GeminiError):
                raise last_error
            raise GeminiError(friendly_error(last_error)) from last_error

    def _generate_once(
        self, transcript: str, instruction: str, model: str, temperature: float
    ) -> str:
        response = self._client.models.generate_content(
            model=model,
            contents=transcript,
            config=types.GenerateContentConfig(
                system_instruction=instruction,
                temperature=temperature,
                response_mime_type="text/plain",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        output = _clean_response(response.text or "")
        if not output:
            raise GeminiError("Vertex AI-მ ცარიელი პასუხი დააბრუნა")
        return output

    def test_connection(
        self, selected_model: str = ""
    ) -> tuple[list[GeminiModel], str]:
        output, used = self.generate(
            "Return exactly OK",
            system_instruction="Return only OK with no punctuation.",
            model=selected_model,
            temperature=0.0,
        )
        if output.strip().strip(".!`*\"'").casefold() != "ok":
            raise GeminiError(
                "Vertex AI კავშირი შედგა, მაგრამ სატესტო პასუხი მოულოდნელი იყო"
            )
        return self.list_text_models(), used
