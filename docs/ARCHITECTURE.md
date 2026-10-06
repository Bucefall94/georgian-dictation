# Architecture

Georgian Dictation is intentionally split into small layers so that local speech recognition, cloud speech recognition, optional AI processing, and Windows text insertion can evolve independently.

## Runtime flow

1. `audio/` captures microphone PCM data.
2. `asr/` converts audio into a raw Georgian transcript through either a local NeMo runtime or Deepgram.
3. `ai/` optionally transforms only the completed transcript through Gemini on Vertex AI.
4. `controller.py` preserves ordering and applies the configured failure policy.
5. `insertion/` writes final Unicode text into the currently focused Windows application.
6. `ui/` exposes settings, diagnostics, status, and the non-activating overlay.

## Key boundaries

### ASR

`ASREngine` is the conceptual provider boundary. The application currently implements a native NeMo path and a Deepgram path. UI code should not need to know transport details for either provider.

### AI post-processing

AI processing is transcript-only and optional. `AIProcessor` has conservative failure semantics: if processing fails, the raw transcript remains available and the configured fallback decides whether to insert it, keep it internally, or copy it.

### Credentials

Deepgram uses Windows Credential Manager. Vertex AI uses Google ADC discovery. The source tree contains neither API keys nor a fixed maintainer project ID.

### Windows integration

Hotkeys, Unicode input, clipboard fallback, startup behavior, and focus handling are isolated from speech/model code. This makes them testable without coupling the ASR layer to the GUI.

## Local data

User settings and logs are stored under platform-appropriate Windows user directories through `platformdirs`. Large speech models are external to the repository and live in the configured model directory.

## Testing strategy

The suite combines provider-independent unit tests, mocked cloud tests, Windows credential/insertion tests, and a native NeMo smoke test that skips when the local model is unavailable.
