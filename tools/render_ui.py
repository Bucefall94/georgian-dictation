import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from georgian_dictation.config.settings import SettingsStore
from georgian_dictation.controller import ApplicationController
from georgian_dictation.models.registry import ModelRegistry
from georgian_dictation.ui.main_window import MainWindow
from georgian_dictation.ui.overlay import ListeningOverlay
from georgian_dictation.ui.fonts import load_app_fonts


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    load_app_fonts()
    settings = SettingsStore(root / "artifacts" / "render-settings.json")
    registry = ModelRegistry(settings)
    overlay = ListeningOverlay()
    controller = ApplicationController(settings, registry, overlay)
    window = MainWindow(settings, registry, controller)
    window.show()

    def capture() -> None:
        for index in range(window.pages.count()):
            window.navigation.setCurrentRow(index)
            app.processEvents()
            window.grab().save(str(output_dir / f"page-{index}.png"), "PNG")
        overlay.show_state("ai_processing", "AI Processing")
        app.processEvents()
        overlay.grab().save(str(output_dir / "overlay-ai-processing.png"), "PNG")
        overlay.hide()
        controller.shutdown()
        window.tray.hide()
        app.quit()

    QTimer.singleShot(800, capture)
    app.exec()
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
