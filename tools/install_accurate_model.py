import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.models.installer import ModelInstaller
from georgian_dictation.models.registry import ModelRegistry


def main() -> int:
    settings = SettingsStore()
    registry = ModelRegistry(settings)
    model = registry.get("georgian-accurate-bf16")
    installer = ModelInstaller()
    failed: list[str] = []
    installer.progress.connect(lambda value, message: print(f"[{value:3d}%] {message}", flush=True))
    installer.completed.connect(lambda path: print(f"READY: {path}", flush=True))
    installer.failed.connect(lambda message: (failed.append(message), print(f"ERROR: {message}", flush=True)))
    installer._install(model, registry.path_for(model))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
