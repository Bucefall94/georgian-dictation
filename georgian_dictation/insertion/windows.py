from __future__ import annotations

import ctypes as ct
import logging

from PySide6.QtCore import QByteArray, QMimeData, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication


ULONG_PTR = ct.c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_V = 0x56


class KEYBDINPUT(ct.Structure):
    _fields_ = [
        ("wVk", ct.c_ushort),
        ("wScan", ct.c_ushort),
        ("dwFlags", ct.c_ulong),
        ("time", ct.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUTUNION(ct.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ct.c_byte * 32)]


class INPUT(ct.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ct.c_ulong), ("u", INPUTUNION)]


class TextInserter(QObject):
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.user32 = ct.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [ct.c_uint, ct.POINTER(INPUT), ct.c_int]
        self.user32.SendInput.restype = ct.c_uint

    def insert(self, text: str, method: str = "auto") -> bool:
        if not text:
            return True
        if method in ("auto", "unicode"):
            if self._unicode_sendinput(text):
                return True
            if method == "unicode":
                self.error.emit("Unicode SendInput-მა ტექსტი ვერ ჩაწერა")
                return False
        return self._clipboard_paste(text)

    def copy_to_clipboard(self, text: str) -> bool:
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    def _unicode_sendinput(self, text: str) -> bool:
        utf16 = text.encode("utf-16-le")
        units = [int.from_bytes(utf16[i : i + 2], "little") for i in range(0, len(utf16), 2)]
        events: list[INPUT] = []
        for unit in units:
            events.append(INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0))))
            events.append(
                INPUT(
                    INPUT_KEYBOARD,
                    INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)),
                )
            )
        array_type = INPUT * len(events)
        array = array_type(*events)
        sent = self.user32.SendInput(len(events), array, ct.sizeof(INPUT))
        if sent != len(events):
            self.log.error("SendInput sent %s/%s events, error=%s", sent, len(events), ct.get_last_error())
        return sent == len(events)

    def _clipboard_paste(self, text: str) -> bool:
        clipboard = QGuiApplication.clipboard()
        old = self._clone_mime(clipboard.mimeData())
        clipboard.setText(text)
        events = (
            INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0))),
            INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_V, 0, 0, 0, 0))),
            INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_V, 0, KEYEVENTF_KEYUP, 0, 0))),
            INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0))),
        )
        array_type = INPUT * len(events)
        sent = self.user32.SendInput(len(events), array_type(*events), ct.sizeof(INPUT))
        QTimer.singleShot(500, lambda: clipboard.setMimeData(old))
        if sent != len(events):
            self.error.emit("Clipboard paste ვერ შესრულდა")
            return False
        return True

    @staticmethod
    def _clone_mime(source: QMimeData) -> QMimeData:
        clone = QMimeData()
        for fmt in source.formats():
            clone.setData(fmt, QByteArray(source.data(fmt)))
        if source.hasUrls():
            clone.setUrls([QUrl(url) for url in source.urls()])
        return clone
