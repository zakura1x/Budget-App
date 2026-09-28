"""
Phase 15 - UX-14 haptics (misc/ROADMAP.md). The vibration itself is the
browser's (frontend/src/tests/haptics.test.ts); the server keeps the switch,
on by default, like every other preference.
"""

import pytest

from app.core.exceptions import ValidationException
from app.services import preferences_service


def test_haptics_are_on_until_turned_off(session, owner):
    assert preferences_service.get_preferences(session, owner)["haptics"] is True
    preferences_service.update_preferences(session, owner, {"haptics": False})
    assert preferences_service.get_preferences(session, owner)["haptics"] is False


def test_haptics_is_a_yes_or_no(session, owner):
    with pytest.raises(ValidationException):
        preferences_service.update_preferences(session, owner, {"haptics": "loud"})
