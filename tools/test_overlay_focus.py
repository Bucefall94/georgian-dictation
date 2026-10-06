from __future__ import annotations

import ctypes as ct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from georgian_dictation.ui.overlay import ListeningOverlay


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_NOACTIVATE = 0x08000000


def main() -> int:
    user32 = ct.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = ct.c_void_p
    user32.GetWindowLongPtrW.argtypes = [ct.c_void_p, ct.c_int]
    user32.GetWindowLongPtrW.restype = ct.c_ssize_t
    foreground_before = user32.GetForegroundWindow()

    app = QApplication([])
    overlay = ListeningOverlay()
    overlay.show_state("listening")
    result = {"ok": False}

    def verify() -> None:
        foreground_after = user32.GetForegroundWindow()
        style = user32.GetWindowLongPtrW(ct.c_void_p(int(overlay.winId())), GWL_EXSTYLE)
        expected = WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        style_ok = style & expected == expected
        focus_ok = foreground_before == foreground_after
        result["ok"] = style_ok and focus_ok
        print("OVERLAY_STYLES=" + ("PASS" if style_ok else "FAIL"))
        print("OVERLAY_FOCUS=" + ("PASS" if focus_ok else "FAIL"))
        overlay.hide()
        app.quit()

    QTimer.singleShot(400, verify)
    app.exec()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
