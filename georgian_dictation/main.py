from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from georgian_dictation.config.settings import SettingsStore, log_dir
from georgian_dictation.controller import ApplicationController
from georgian_dictation.models.registry import ModelRegistry
from georgian_dictation.ui.main_window import MainWindow
from georgian_dictation.ui.overlay import ListeningOverlay
from georgian_dictation.ui.fonts import load_app_fonts


def configure_logging() -> None:
    handler = RotatingFileHandler(
        log_dir() / "georgian-dictation.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> int:
    configure_logging()
    QCoreApplication.setOrganizationName("GeorgianDictation")
    QCoreApplication.setApplicationName("GeorgianDictation")
    app = QApplication(sys.argv)
    app.setFont(QFont(load_app_fonts(), 10))
    app.setQuitOnLastWindowClosed(False)
    settings = SettingsStore()
    registry = ModelRegistry(settings)
    overlay = ListeningOverlay()
    controller = ApplicationController(settings, registry, overlay)
    window = MainWindow(settings, registry, controller)
    app.aboutToQuit.connect(controller.shutdown)
    controller.initialize()
    minimized_arg = "--minimized" in sys.argv
    if not (minimized_arg or settings.get("general", "start_minimized", False)):
        window.show()
    elif not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
