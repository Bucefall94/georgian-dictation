# Contributing to Georgian Dictation

Thanks for helping improve Georgian desktop voice input.

## Development environment

The project currently targets **Windows 11 x64 + Python 3.12**.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

## Pull requests

Keep pull requests focused and explain the user-visible behavior being changed. Add or update tests when practical. For UI changes, include a screenshot or short recording with credentials and personal data removed.

Before opening a PR:

1. Run the unit tests.
2. Run the relevant Windows integration utility when touching hotkeys, insertion, overlay focus, audio, or model/runtime discovery.
3. Do not commit `.venv`, `dist`, `build`, logs, WAV recordings, GGUF/model files, ADC files, API keys, or exported credential files.
4. Keep STT provider code, AI processing, and text insertion separate unless the change truly spans those layers.
5. Preserve the raw transcript on AI/cloud failures.

## Security-sensitive changes

Changes involving credential storage, auth, clipboard behavior, subprocess execution, downloads, or native DLL loading deserve extra review. Do not move secrets into JSON settings or logs.

## Language and UX

User-facing Georgian copy should be natural and readable. English developer documentation is preferred for contributor-facing technical material so the project remains accessible internationally.
