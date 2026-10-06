from __future__ import annotations

import ctypes as ct
from ctypes import wintypes

from PySide6.QtCore import QThread, Signal


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WH_KEYBOARD_LL = 13
HC_ACTION = 0
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C


SPECIAL_KEYS = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
}


class KBDLLHOOKSTRUCT(ct.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ct.c_size_t),
    ]


HOOKPROC = ct.WINFUNCTYPE(ct.c_ssize_t, ct.c_int, wintypes.WPARAM, wintypes.LPARAM)


def parse_sequence(sequence: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in sequence.split("+") if part.strip()]
    modifiers = 0
    key_name = ""
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in ("WIN", "META"):
            modifiers |= MOD_WIN
        else:
            key_name = part
    if not key_name:
        raise ValueError("Hotkey-ში მთავარი ღილაკი აკლია")
    if key_name.startswith("F") and key_name[1:].isdigit() and 1 <= int(key_name[1:]) <= 24:
        vk = 0x70 + int(key_name[1:]) - 1
    elif len(key_name) == 1 and key_name.isalnum():
        vk = ord(key_name)
    else:
        vk = SPECIAL_KEYS.get(key_name, 0)
    if not vk:
        raise ValueError(f"Hotkey-ის ღილაკი მხარდაჭერილი არ არის: {key_name}")
    return modifiers, vk


class HotkeyThread(QThread):
    activated = Signal()
    deactivated = Signal()
    registration_failed = Signal(str)
    registered = Signal()

    def __init__(self, sequence: str, mode: str) -> None:
        super().__init__()
        self.sequence = sequence
        self.mode = mode
        self.thread_id = 0
        self._hook = None
        self._hook_proc = None
        self._pressed = False

    def run(self) -> None:
        user32 = ct.WinDLL("user32", use_last_error=True)
        kernel32 = ct.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ct.c_void_p
        user32.SetWindowsHookExW.argtypes = [ct.c_int, HOOKPROC, ct.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ct.c_void_p
        user32.CallNextHookEx.argtypes = [ct.c_void_p, ct.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ct.c_ssize_t
        self.thread_id = kernel32.GetCurrentThreadId()
        try:
            modifiers, vk = parse_sequence(self.sequence)
        except ValueError as exc:
            self.registration_failed.emit(str(exc))
            return

        if self.mode == "toggle":
            if not user32.RegisterHotKey(None, 1, modifiers | MOD_NOREPEAT, vk):
                self.registration_failed.emit("ეს hotkey უკვე დაკავებულია სხვა პროგრამის მიერ")
                return
            self.registered.emit()
            message = wintypes.MSG()
            while user32.GetMessageW(ct.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    self.activated.emit()
            user32.UnregisterHotKey(None, 1)
            return

        if not user32.RegisterHotKey(None, 2, modifiers | MOD_NOREPEAT, vk):
            self.registration_failed.emit("ეს hotkey უკვე დაკავებულია სხვა პროგრამის მიერ")
            return
        user32.UnregisterHotKey(None, 2)

        def callback(code: int, wparam: int, lparam: int) -> int:
            if code == HC_ACTION:
                event = ct.cast(lparam, ct.POINTER(KBDLLHOOKSTRUCT)).contents
                if event.vkCode == vk:
                    if (
                        wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                        and not self._pressed
                        and self._modifiers_down(user32, modifiers)
                    ):
                        self._pressed = True
                        self.activated.emit()
                    elif wparam in (WM_KEYUP, WM_SYSKEYUP) and self._pressed:
                        self._pressed = False
                        self.deactivated.emit()
            return user32.CallNextHookEx(self._hook, code, wparam, lparam)

        self._hook_proc = HOOKPROC(callback)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, module, 0)
        if not self._hook:
            self.registration_failed.emit(f"Keyboard hook ვერ ჩაირთო (error {ct.get_last_error()})")
            return
        self.registered.emit()
        message = wintypes.MSG()
        while user32.GetMessageW(ct.byref(message), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    @staticmethod
    def _modifiers_down(user32: ct.WinDLL, required: int) -> bool:
        checks = (
            (MOD_CONTROL, VK_CONTROL),
            (MOD_SHIFT, VK_SHIFT),
            (MOD_ALT, VK_MENU),
        )
        for flag, vk in checks:
            if required & flag and not (user32.GetAsyncKeyState(vk) & 0x8000):
                return False
        if required & MOD_WIN:
            if not (
                user32.GetAsyncKeyState(VK_LWIN) & 0x8000
                or user32.GetAsyncKeyState(VK_RWIN) & 0x8000
            ):
                return False
        return True

    def stop(self) -> None:
        if self.thread_id:
            ct.WinDLL("user32").PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.wait(2000)


class GlobalHotkey:
    def __init__(self) -> None:
        self.thread: HotkeyThread | None = None

    def register(self, sequence: str, mode: str) -> HotkeyThread:
        self.unregister()
        self.thread = HotkeyThread(sequence, mode)
        return self.thread

    def unregister(self) -> None:
        if self.thread:
            self.thread.stop()
            self.thread = None
