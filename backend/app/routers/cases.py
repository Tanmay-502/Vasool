"""
Read-only case-listing endpoints for the dashboard. Currently just the
recent-activity feed backing the frontend's audit ledger — kept separate
from routers/agents.py (pipeline actions) and routers/policy.py (policy +
execution actions) since this is a pure read, not a state transition.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog
from app.schemas import AuditLedgerEntry, AuditLedgerResponse

router = APIRouter()


def _build_detail(event_type: str, payload: dict) -> str:
    if event_type == "execution_started":
        action_type = (payload.get("action_type") or "action").replace("_", " ")
        return f"Attempting {action_type}"
    if event_type == "execution_succeeded":
        short_url = payload.get("short_url")
        return f"Payment link sent — {short_url}" if short_url else "Payment link sent"
    if event_type == "execution_failed":
        reason = payload.get("reason", "unknown error")
        return f"Failed: {reason}"
    return event_type.replace("_", " ").capitalize()


@router.get("/cases/recent", response_model=AuditLedgerResponse)
def get_recent_cases(limit: int = 20, db: Session = Depends(get_db)):
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.recovery_case_id.isnot(None))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    entries = [
        AuditLedgerEntry(
            id=row.id,
            case_id=row.recovery_case_id,
            event_type=row.event_type,
            detail=_build_detail(row.event_type, row.payload),
            created_at=row.created_at,
        )
        for row in rows
    ]
    return AuditLedgerResponse(entries=entries)