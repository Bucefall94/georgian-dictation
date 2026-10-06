from pathlib import Path

from georgian_dictation.config.settings import SettingsStore


def test_settings_round_trip_preserves_georgian(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.set("audio", "device_name", "ქართული მიკროფონი")
    loaded = SettingsStore(path)
    assert loaded.get("audio", "device_name") == "ქართული მიკროფონი"
    assert loaded.get("hotkey", "sequence") == "F8"


def test_unknown_saved_keys_do_not_remove_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"audio":{"silence_ms":1800}}', encoding="utf-8")
    store = SettingsStore(path)
    assert store.get("audio", "silence_ms") == 1800
    assert store.get("audio", "sample_rate") == 16000
    assert store.get("ai", "mode") == "off"
    assert store.get("ai", "provider") == "vertex_ai_adc"
    assert store.get("ai", "failure_action") == "insert_raw"


def test_ai_settings_never_contain_a_credential(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.set("ai", "mode", "smart_correction")
    store.set("ai", "gemini_model", "gemini-dynamic-flash")
    reloaded = SettingsStore(path)
    assert reloaded.get("ai", "provider") == "vertex_ai_adc"
    assert reloaded.get("ai", "mode") == "smart_correction"
    assert reloaded.get("ai", "gemini_model") == "gemini-dynamic-flash"
    payload = path.read_text(encoding="utf-8").casefold()
    assert "api_key" not in payload
    assert "credential" not in payload
