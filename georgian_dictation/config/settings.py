from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_log_dir


APP_NAME = "GeorgianDictation"
APP_AUTHOR = "GeorgianDictation"


DEFAULTS: dict[str, Any] = {
    "general": {
        "launch_at_startup": False,
        "start_minimized": False,
        "minimize_to_tray": True,
        "sounds": False,
    },
    "audio": {
        "device_id": None,
        "device_name": "Windows default",
        "sample_rate": 16000,
        "silence_ms": 1200,
        "vad_threshold": 0.012,
    },
    "hotkey": {
        "sequence": "F8",
        "mode": "toggle",
    },
    "dictation": {
        "trailing_space": True,
        "automatic_punctuation": True,
        "insertion_method": "auto",
        "long_dictation": True,
        "keep_microphone_active": True,
    },
    "models": {
        "selected": "georgian-streaming-80ms",
    },
    "ai": {
        "provider": "vertex_ai_adc",
        "mode": "off",
        "gemini_model": "",
        "timeout_seconds": 20,
        "aggressiveness": "conservative",
        "failure_action": "insert_raw",
    },
    "advanced": {
        "backend": "cuda",
        "logging": True,
        "streaming_profile": "fastest",
        "nemo_runtime_dir": "",
        "models_dir": "",
    },
}


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_AUTHOR, roaming=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = Path(user_log_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_models_dir() -> Path:
    return Path(os.path.expandvars(r"%USERPROFILE%\NemoSpeechModels"))


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.data = _merge(DEFAULTS, saved)
        except (OSError, json.JSONDecodeError):
            self.data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(self.path)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any, *, save: bool = True) -> None:
        self.data.setdefault(section, {})[key] = value
        if save:
            self.save()

    @property
    def models_dir(self) -> Path:
        configured = self.get("advanced", "models_dir", "")
        return Path(os.path.expandvars(configured)) if configured else default_models_dir()
