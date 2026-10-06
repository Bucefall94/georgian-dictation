from __future__ import annotations

from PySide6.QtGui import QFontDatabase


PREFERRED_FAMILIES = (
    "Noto Sans Georgian",
    "Segoe UI",
    "Sylfaen",
)


def load_app_fonts() -> str:
    """Choose a Georgian-capable installed font; no font binary is bundled."""
    available = set(QFontDatabase.families())
    for family in PREFERRED_FAMILIES:
        if family in available:
            return family
    return "Segoe UI"
