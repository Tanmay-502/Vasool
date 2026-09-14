"""Database-backed global runtime state."""

from sqlalchemy.orm import Session

from app.config import settings
from app.models import RuntimeSetting

_KILL_SWITCH_KEY = "kill_switch_engaged"


def get_kill_switch(db: Session) -> bool:
    # An explicit environment setting remains an emergency floor: the database
    # can pause/resume automation at runtime, but cannot override a deployment
    # that was intentionally started with the kill switch engaged.
    if settings.KILL_SWITCH_ENGAGED:
        return True
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == _KILL_SWITCH_KEY).first()
    if row is None:
        row = RuntimeSetting(key=_KILL_SWITCH_KEY, value={"enabled": False})
        db.add(row)
        db.commit()
        return False
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
