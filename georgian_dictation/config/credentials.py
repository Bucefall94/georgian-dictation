from __future__ import annotations

import ctypes as ct
import sys
from ctypes import wintypes


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
DEFAULT_TARGET = "GeorgianDictation/DeepgramAPIKey"


class CredentialError(RuntimeError):
    pass


class CREDENTIAL_ATTRIBUTEW(ct.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ct.POINTER(ct.c_ubyte)),
    ]


class CREDENTIALW(ct.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ct.POINTER(ct.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ct.POINTER(CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ct.POINTER(CREDENTIALW)


class WindowsCredentialStore:
    """Stores one secret in the current user's Windows Credential Manager vault."""

    def __init__(self, target: str = DEFAULT_TARGET) -> None:
        if sys.platform != "win32":
            raise CredentialError("Secure credential storage მხოლოდ Windows-ზეა ხელმისაწვდომი")
        self.target = target
        self._advapi32 = ct.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [PCREDENTIALW, wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ct.POINTER(PCREDENTIALW),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ct.c_void_p]
        self._advapi32.CredFree.restype = None

    def save(self, secret: str) -> None:
        value = secret.strip()
        if not value:
            raise CredentialError("API key ცარიელია")
        encoded = value.encode("utf-8")
        if len(encoded) > 2560:
            raise CredentialError("API key დასაშვებ ზომას აჭარბებს")
        blob = (ct.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = CREDENTIALW(
            Flags=0,
            Type=CRED_TYPE_GENERIC,
            TargetName=self.target,
            Comment="GeorgianDictation secure API key",
            CredentialBlobSize=len(encoded),
            CredentialBlob=ct.cast(blob, ct.POINTER(ct.c_ubyte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName="GeorgianDictation",
        )
        if not self._advapi32.CredWriteW(ct.byref(credential), 0):
            raise CredentialError(
                f"API key Windows Credential Manager-ში ვერ შეინახა (error {ct.get_last_error()})"
            )

    def read(self) -> str | None:
        pointer = PCREDENTIALW()
        if not self._advapi32.CredReadW(
            self.target, CRED_TYPE_GENERIC, 0, ct.byref(pointer)
        ):
            error = ct.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise CredentialError(
                f"API key Windows Credential Manager-იდან ვერ წაიკითხა (error {error})"
            )
        try:
            credential = pointer.contents
            if not credential.CredentialBlob or not credential.CredentialBlobSize:
                return ""
            raw = ct.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CredentialError("შენახული API key დაზიანებულია") from exc
        finally:
            self._advapi32.CredFree(pointer)

    def exists(self) -> bool:
        return bool(self.read())

    def remove(self) -> bool:
        if self._advapi32.CredDeleteW(self.target, CRED_TYPE_GENERIC, 0):
            return True
        error = ct.get_last_error()
        if error == ERROR_NOT_FOUND:
            return False
        raise CredentialError(
            f"API key Windows Credential Manager-იდან ვერ წაიშალა (error {error})"
        )


def deepgram_credentials() -> WindowsCredentialStore:
    return WindowsCredentialStore(DEFAULT_TARGET)
