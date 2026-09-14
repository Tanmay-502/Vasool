"""Database-backed global runtime state.

The settings table intentionally stays generic so future operational flags can be
persisted without introducing another deployment dependency.
"""

from sqlalchemy.orm import Session

from app.config import settings
from app.models import RuntimeSetting

_KILL_SWITCH_KEY = "kill_switch_engaged"


def get_kill_switch(db: Session) -> bool:
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == _KILL_SWITCH_KEY).first()
    if row is None:
        row = RuntimeSetting(key=_KILL_SWITCH_KEY, value={"enabled": bool(settings.KILL_SWITCH_ENGAGED)})
        db.add(row)
        db.commit()
        return bool(settings.KILL_SWITCH_ENGAGED)
    return bool(row.value.get("enabled", False))


def set_kill_switch(db: Session, engaged: bool) -> bool:
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == _KILL_SWITCH_KEY).first()
    if row is None:
        row = RuntimeSetting(key=_KILL_SWITCH_KEY, value={"enabled": engaged})
        db.add(row)
    else:
        row.value = {"enabled": engaged}
    db.commit()
    settings.KILL_SWITCH_ENGAGED = engaged
    return engaged
