import pytest

from georgian_dictation.hotkeys.windows import (
    MOD_CONTROL,
    MOD_SHIFT,
    parse_sequence,
)


def test_parses_function_key() -> None:
    assert parse_sequence("F8") == (0, 0x77)


def test_parses_modifier_combo() -> None:
    modifiers, vk = parse_sequence("Ctrl+Shift+Space")
    assert modifiers == MOD_CONTROL | MOD_SHIFT
    assert vk == 0x20


def test_rejects_modifier_only() -> None:
    with pytest.raises(ValueError):
        parse_sequence("Ctrl+Shift")

