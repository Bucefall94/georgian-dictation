from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class RuntimeStatus:
    available: bool
    cli_path: Path | None
    bin_dir: Path | None
    version: str = ""
    cuda_available: bool = False
    message: str = ""


def find_nemo_cli(configured_dir: str = "") -> Path | None:
    candidates: list[Path] = []
    if configured_dir:
        root = Path(os.path.expandvars(configured_dir))
        candidates.extend([root / "nemo-speech.exe", root / "bin" / "nemo-speech.exe"])
    found = shutil.which("nemo-speech")
    if found:
        candidates.append(Path(found))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates.append(local / "Programs" / "NeMoSpeech" / "bin" / "nemo-speech.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def inspect_runtime(configured_dir: str = "") -> RuntimeStatus:
    cli = find_nemo_cli(configured_dir)
    if not cli:
        return RuntimeStatus(False, None, None, message="NeMo-Speech.cpp ვერ მოიძებნა")
    try:
        proc = subprocess.run(
            [str(cli), "doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
        dll = cli.parent / "nemo_speech_asr_c.dll"
        available = proc.returncode == 0 and dll.is_file()
        return RuntimeStatus(
            available=available,
            cli_path=cli,
            bin_dir=cli.parent,
            version=str(payload.get("version", "")),
            cuda_available=bool(payload.get("accelerator_available", False)),
            message="მზადაა" if available else (proc.stderr.strip() or "ASR DLL აკლია"),
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return RuntimeStatus(False, cli, cli.parent, message=str(exc))

