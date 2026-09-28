"""
preferences_service - the settings a user changes about how the app behaves.

Phase 5 opens the budget-behaviour keys; the rest of Settings (theme, lock
timing, the period defaults) arrives in Phase 8b. Only the keys named in
EDITABLE can be written - a preferences row is sealed JSON, and anything
accepted here would be trusted by every later read of it.
"""

from typing import Any, Dict, Mapping

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto.user_cipher import UserCipher
from app.core.exceptions import ValidationException
from app.db.repositories.preferences_repository import PreferencesRepository
from app.services import audit_service
from app.services.auth_service.registration_service import default_preferences
from app.services.budget_service.allowance import MODES
from app.services.budget_service.suggest import STEPS

EDITABLE = (
    "carry_over", "daily_allowance_mode", "alert_warn_threshold_pct", "alert_pace_enabled",
    # Phase 8b
    "theme", "budget_period", "month_start_day", "week_start_day", "auto_lock_minutes",
    # the neo-brutalist redesign, 2026-09-18
    "palette",
    # BUD-17, 2026-09-28: the suggested budget's rounding step, and its period-start reminder
    "budget_round_step", "budget_suggestion_nudge",
)
THEMES = ("system", "light", "dark")
# UX-05: the colour palette, independent of light/dark (every palette has both).
PALETTES = ("classic", "candy", "lime", "mono")
PERIODS = ("weekly", "monthly", "custom")


def get_preferences(db: Session, cipher: UserCipher) -> Dict[str, Any]:
    record = PreferencesRepository(db, cipher).current()
    return {**default_preferences(), **(record.data if record else {})}


def update_preferences(db: Session, cipher: UserCipher, changes: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValidationException(f"Not a setting you can change here: {', '.join(sorted(unknown))}")

    cleaned: Dict[str, Any] = {}
    if "carry_over" in changes:
        cleaned["carry_over"] = _bool(changes["carry_over"], "carry_over")
    if "alert_pace_enabled" in changes:
        cleaned["alert_pace_enabled"] = _bool(changes["alert_pace_enabled"], "alert_pace_enabled")
    if "budget_suggestion_nudge" in changes:
        cleaned["budget_suggestion_nudge"] = _bool(changes["budget_suggestion_nudge"], "budget_suggestion_nudge")
    if "budget_round_step" in changes:
        step = changes["budget_round_step"]
        if isinstance(step, bool) or step not in STEPS:
            raise ValidationException(f"budget_round_step must be one of: {', '.join(map(str, STEPS))}")
        cleaned["budget_round_step"] = step
    if "daily_allowance_mode" in changes:
        if changes["daily_allowance_mode"] not in MODES:
            raise ValidationException(f"daily_allowance_mode must be one of: {', '.join(MODES)}")
        cleaned["daily_allowance_mode"] = changes["daily_allowance_mode"]
    if "alert_warn_threshold_pct" in changes:
        value = changes["alert_warn_threshold_pct"]
        if isinstance(value, bool) or not isinstance(value, int) or not 50 <= value <= 100:
            raise ValidationException("alert_warn_threshold_pct must be 50-100")
        cleaned["alert_warn_threshold_pct"] = value
    if "theme" in changes:
        if changes["theme"] not in THEMES:
            raise ValidationException(f"theme must be one of: {', '.join(THEMES)}")
        cleaned["theme"] = changes["theme"]
    if "palette" in changes:
        if changes["palette"] not in PALETTES:
            raise ValidationException(f"palette must be one of: {', '.join(PALETTES)}")
        cleaned["palette"] = changes["palette"]
    if "budget_period" in changes:
        if changes["budget_period"] not in PERIODS:
            raise ValidationException(f"budget_period must be one of: {', '.join(PERIODS)}")
        cleaned["budget_period"] = changes["budget_period"]
    for key, low, high in (("month_start_day", 1, 31), ("week_start_day", 1, 7)):
        if key in changes:
            cleaned[key] = _int(changes[key], key, low, high)
    if "auto_lock_minutes" in changes:
        # The server's own idle limit is the ceiling: a longer choice would be a promise it cannot keep.
        cleaned["auto_lock_minutes"] = _int(changes["auto_lock_minutes"], "auto_lock_minutes", 1,
                                            settings.PIN_AUTO_LOCK_MINUTES)

    repo = PreferencesRepository(db, cipher)
    record = repo.current()
    data = {**default_preferences(), **(record.data if record else {}), **cleaned}
    if record is None:
        repo.create(data)
    else:
        repo.update(record.id, data)
    audit_service.record(
        db, audit_service.UPDATE, user_id=cipher.user_id, entity="user_preferences",
        cipher=cipher, detail={"changed": sorted(cleaned)},
    )
    db.commit()
    return data


def _int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValidationException(f"{name} must be {low}-{high}")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationException(f"{name} is true or false")
    return value
