# Privacy and Data Flow

Georgian Dictation does not implement application telemetry.

## Local NVIDIA mode

Microphone audio is processed by the local NeMo-Speech.cpp runtime. Audio and transcript data are not sent to Deepgram unless the user explicitly selects the Deepgram engine. Gemini is not called when AI Processing is Off.

## Deepgram mode

When Deepgram Nova-3 is selected, audio required for transcription is sent to the Deepgram API. The application requests Georgian recognition and uses the provider option configured in source for model-improvement opt-out where supported.

The Deepgram API key is stored through Windows Credential Manager for the current Windows user. It is not written to the normal settings JSON.

## Gemini on Vertex AI

Vertex AI receives only completed transcript text from the STT stage. The application does not send microphone audio to Vertex AI.

Google authentication is provided by Application Default Credentials (ADC). The app does not require a credential JSON path and does not bundle service-account credentials.

## Logs

The application can write operational logs locally. Contributors and users should review and redact logs before posting them publicly because runtime errors can contain machine-specific paths, project identifiers, or dictated text depending on the failure context.

## Clipboard fallback

When Unicode `SendInput` cannot insert text, the Windows clipboard can be used temporarily for paste fallback. The implementation attempts to restore the prior clipboard contents after insertion.
