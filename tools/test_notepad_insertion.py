from __future__ import annotations

import ctypes as ct
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from georgian_dictation.insertion.windows import INPUT, INPUTUNION, KEYBDINPUT, TextInserter


EXPECTED = "ქართული Unicode ტექსტი — Notepad"
SW_RESTORE = 9
VK_CONTROL = 0x11
VK_A = 0x41
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


def _find_window(user32: ct.WinDLL, pid: int, timeout: float = 8.0) -> int:
    windows: list[int] = []
    callback_type = ct.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ct.byref(window_pid))
        if window_pid.value == pid and user32.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    callback_ref = callback_type(callback)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows.clear()
        user32.EnumWindows(callback_ref, 0)
        if windows:
            return windows[0]
        time.sleep(0.1)
    raise RuntimeError("Notepad window did not appear")


def _copy_all(user32: ct.WinDLL) -> None:
    events = (
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_A, 0, 0, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_A, 0, KEYEVENTF_KEYUP, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_C, 0, 0, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_C, 0, KEYEVENTF_KEYUP, 0, 0))),
        INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0))),
    )
    array_type = INPUT * len(events)
    sent = user32.SendInput(len(events), array_type(*events), ct.sizeof(INPUT))
    if sent != len(events):
        raise RuntimeError(f"Copy input incomplete: {sent}/{len(events)}")


def main() -> int:
    app = QApplication([])
    clipboard = app.clipboard()
    original_clipboard: QMimeData = TextInserter._clone_mime(clipboard.mimeData())
    process = subprocess.Popen(["notepad.exe"])
    try:
        user32 = ct.WinDLL("user32", use_last_error=True)
        user32.SendInput.argtypes = [ct.c_uint, ct.POINTER(INPUT), ct.c_int]
        user32.SendInput.restype = ct.c_uint
        hwnd = _find_window(user32, process.pid)
        user32.ShowWindow(hwnd, SW_RESTORE)
        if not user32.SetForegroundWindow(hwnd):
            raise RuntimeError("Could not focus Notepad")
        time.sleep(0.35)

        inserted = TextInserter().insert(EXPECTED, "unicode")
        if not inserted:
            raise RuntimeError("Unicode SendInput failed")
        time.sleep(0.35)
        _copy_all(user32)
        time.sleep(0.25)
        app.processEvents()
        received = clipboard.text()
        print("NOTEPAD_INSERTION=" + ("PASS" if received == EXPECTED else "FAIL"))
        return 0 if received == EXPECTED else 1
    finally:
        clipboard.setMimeData(original_clipboard)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
