from __future__ import annotations

import json
import uuid
from pathlib import Path

from georgian_dictation.config.credentials import DEFAULT_TARGET, WindowsCredentialStore
from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.models.registry import ModelRegistry


def test_windows_credential_manager_round_trip() -> None:
    target = f"GeorgianDictation.Tests/{uuid.uuid4()}"
    store = WindowsCredentialStore(target)
    try:
        assert store.read() is None
        store.save("temporary-test-secret")
        assert store.exists()
        assert store.read() == "temporary-test-secret"
        assert store.remove()
        assert store.read() is None
    finally:
        store.remove()


def test_api_key_is_never_written_to_settings_json(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = SettingsStore(settings_path)
    settings.set("models", "selected", "deepgram-nova-3-ka")
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(payload).casefold()
    assert "secret" not in json.dumps(payload).casefold()


def test_secure_credential_target_remains_deepgram_only() -> None:
    assert DEFAULT_TARGET == "GeorgianDictation/DeepgramAPIKey"


def test_cloud_selection_persists_but_credential_stays_in_vault(tmp_path: Path) -> None:
    target = f"GeorgianDictation.Tests/{uuid.uuid4()}"
    credential = WindowsCredentialStore(target)
    settings_path = tmp_path / "settings.json"
    try:
        credential.save("temporary-test-secret")
        registry = ModelRegistry(SettingsStore(settings_path), credential)
        assert registry.is_installed("deepgram-nova-3-ka")
        registry.select("deepgram-nova-3-ka")

        reloaded = ModelRegistry(SettingsStore(settings_path), credential)
        assert reloaded.selected().id == "deepgram-nova-3-ka"
        assert "temporary-test-secret" not in settings_path.read_text(encoding="utf-8")
    finally:
        credential.remove()
