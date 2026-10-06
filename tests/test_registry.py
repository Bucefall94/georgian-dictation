from pathlib import Path

from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.models.registry import ModelRegistry


def test_registry_is_data_driven(tmp_path: Path) -> None:
    settings = SettingsStore(tmp_path / "settings.json")
    settings.set("advanced", "models_dir", str(tmp_path))
    registry = ModelRegistry(settings)
    assert [m.kind for m in registry.all()] == ["streaming", "accurate", "cloud"]
    assert registry.get("georgian-accurate-bf16").outtype == "bf16"
    cloud = registry.get("deepgram-nova-3-ka")
    assert cloud.priority == "High Accuracy"
    assert registry.path_for(cloud) is None


def test_model_detection_uses_local_file(tmp_path: Path) -> None:
    settings = SettingsStore(tmp_path / "settings.json")
    settings.set("advanced", "models_dir", str(tmp_path))
    registry = ModelRegistry(settings)
    path = registry.path_for("georgian-streaming-80ms")
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    assert registry.is_installed("georgian-streaming-80ms")
