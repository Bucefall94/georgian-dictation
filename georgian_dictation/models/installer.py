from __future__ import annotations

import json
import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from platformdirs import user_data_dir
from PySide6.QtCore import QObject, Signal

from georgian_dictation.asr.runtime import CREATE_NO_WINDOW, find_nemo_cli
from georgian_dictation.config.settings import APP_AUTHOR, APP_NAME
from georgian_dictation.models.registry import ModelSpec


class ModelInstaller(QObject):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)
    running_changed = Signal(bool)

    SOURCE_URL = "https://github.com/NVIDIA/NeMo-Speech.cpp.git"
    SOURCE_TAG = "v0.1.0"

    def __init__(self) -> None:
        super().__init__()
        self.log = logging.getLogger(__name__)
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def install(self, model: ModelSpec, destination: Path) -> None:
        if self.running:
            return
        self._thread = threading.Thread(
            target=self._install,
            args=(model, destination),
            name="ModelInstaller",
            daemon=True,
        )
        self._thread.start()

    def _install(self, model: ModelSpec, destination: Path) -> None:
        self.running_changed.emit(True)
        data_root = Path(user_data_dir(APP_NAME, APP_AUTHOR, roaming=False))
        checkout = data_root / "converter" / "NeMo-Speech.cpp-v0.1.0"
        venv = data_root / "converter" / "venv-v0.1.0"
        partial = destination.with_suffix(destination.suffix + ".partial")
        metadata = destination.with_suffix(".metadata.json")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                self.completed.emit(str(destination))
                return
            if partial.exists():
                partial.unlink()
            if not (checkout / "convert_model.py").is_file():
                self.progress.emit(5, "ოფიციალური converter-ის source იტვირთება…")
                checkout.parent.mkdir(parents=True, exist_ok=True)
                self._run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--branch",
                        self.SOURCE_TAG,
                        self.SOURCE_URL,
                        str(checkout),
                    ],
                    progress_base=5,
                )
            python = self._python_for_venv()
            venv_python = venv / "Scripts" / "python.exe"
            if not venv_python.is_file():
                self.progress.emit(15, "Converter-ის იზოლირებული გარემო იქმნება…")
                self._run([str(python), "-m", "venv", str(venv)], progress_base=15)
            marker = venv / ".dependencies-ready"
            if not marker.is_file():
                self.progress.emit(22, "Converter-ის დამოკიდებულებები ყენდება…")
                self._run(
                    [
                        str(venv_python),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "-r",
                        str(checkout / "requirements.txt"),
                    ],
                    cwd=checkout,
                    progress_base=22,
                )
                marker.write_text(self.SOURCE_TAG, encoding="utf-8")
            self.progress.emit(45, "Accurate checkpoint იტვირთება და BF16 GGUF იქმნება…")
            self._run(
                [
                    str(venv_python),
                    str(checkout / "convert_model.py"),
                    model.source,
                    "--outfile",
                    str(partial),
                    "--outtype",
                    model.outtype,
                    "--metadata-json",
                    str(metadata),
                ],
                cwd=checkout,
                progress_base=45,
            )
            self.progress.emit(92, "GGUF თავსებადობა მოწმდება…")
            cli = find_nemo_cli()
            if not cli:
                raise RuntimeError("NeMo-Speech.cpp runtime ვერ მოიძებნა")
            proc = subprocess.run(
                [str(cli), "model", "info", str(partial), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
            info = json.loads(proc.stdout)
            if not info.get("runtime_compatible"):
                raise RuntimeError("შექმნილი GGUF მიმდინარე runtime-თან თავსებადი არ არის")
            partial.replace(destination)
            self.progress.emit(100, "მოდელი მზადაა")
            self.completed.emit(str(destination))
        except Exception as exc:
            self.log.exception("Model installation failed")
            self.failed.emit(str(exc))
        finally:
            self.running_changed.emit(False)

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        progress_base: int,
    ) -> None:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        assert proc.stdout is not None
        tail: list[str] = []
        for line in proc.stdout:
            clean = line.strip()
            if clean:
                self.log.info("installer: %s", clean)
                tail.append(clean)
                tail = tail[-30:]
                match = re.search(r"(\d{1,3})%", clean)
                if match and progress_base >= 45:
                    value = 45 + int(match.group(1)) * 45 // 100
                    self.progress.emit(min(value, 90), "მოდელი მუშავდება…")
        code = proc.wait()
        if code:
            raise RuntimeError("\n".join(tail[-8:]) or f"პროცესი დასრულდა კოდით {code}")

    @staticmethod
    def _python_for_venv() -> Path:
        if not getattr(sys, "frozen", False):
            return Path(sys.executable)
        py = shutil.which("py")
        if py:
            proc = subprocess.run(
                [py, "-3.12", "-c", "import sys;print(sys.executable)"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            candidate = Path(proc.stdout.strip())
            if proc.returncode == 0 and candidate.is_file():
                return candidate
        python = shutil.which("python")
        if python:
            return Path(python)
        raise RuntimeError("Accurate მოდელის conversion-ისთვის Python 3.12 ვერ მოიძებნა")


def recycle_file(path: Path) -> bool:
    """Move one exact file to the Windows recycle bin."""
    if not path.is_file():
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_bool),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_SILENT = 0x4
    source = str(path.resolve()) + "\0\0"
    operation = SHFILEOPSTRUCTW(
        None, FO_DELETE, source, None, FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT,
        False, None, None
    )
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation)) == 0
