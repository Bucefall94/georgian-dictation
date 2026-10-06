from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.config.credentials import CredentialError, WindowsCredentialStore, deepgram_credentials


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    short_name: str
    source: str
    filename: str
    kind: str
    outtype: str
    approx_size_mb: int
    priority: str
    reference_wer: dict[str, float]
    description: str


class ModelRegistry:
    def __init__(
        self,
        settings: SettingsStore,
        credentials: WindowsCredentialStore | None = None,
    ) -> None:
        self.settings = settings
        self.credentials = credentials or deepgram_credentials()
        resource = files("georgian_dictation.models").joinpath("models.json")
        raw = json.loads(resource.read_text(encoding="utf-8"))
        self._models = [ModelSpec(**entry) for entry in raw["models"]]

    def all(self) -> list[ModelSpec]:
        return list(self._models)

    def get(self, model_id: str) -> ModelSpec:
        return next(model for model in self._models if model.id == model_id)

    def path_for(self, model: ModelSpec | str) -> Path | None:
        spec = self.get(model) if isinstance(model, str) else model
        if spec.kind == "cloud":
            return None
        return self.settings.models_dir / spec.filename

    def is_installed(self, model: ModelSpec | str) -> bool:
        spec = self.get(model) if isinstance(model, str) else model
        if spec.kind == "cloud":
            try:
                return self.credentials.exists()
            except CredentialError:
                return False
        path = self.path_for(spec)
        assert path is not None
        return path.is_file() and path.stat().st_size > 1024 * 1024

    def location_for(self, model: ModelSpec | str) -> str:
        spec = self.get(model) if isinstance(model, str) else model
        path = self.path_for(spec)
        return "Windows Credential Manager" if path is None else str(path)

    @staticmethod
    def backend_for(model: ModelSpec) -> str:
        return "Deepgram Cloud" if model.kind == "cloud" else "NeMo local"

    def selected(self) -> ModelSpec:
        selected_id = self.settings.get("models", "selected")
        try:
            return self.get(selected_id)
        except StopIteration:
            return self._models[0]

    def select(self, model_id: str) -> None:
        self.get(model_id)
        self.settings.set("models", "selected", model_id)
