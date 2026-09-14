from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.executor import CaseNotPendingExecutionError, CircuitOpenError, execute_case
from app.models import AgentDecision, AuditLog, PolicyCheck, RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, run_policy_for_case
from app.rate_limit import RateLimitExceeded
from app.razorpay_client import RazorpayError

router = APIRouter()


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


@router.post("/cases/{case_id}/evaluate-policy")
def evaluate_case_policy(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    try:
        result = run_policy_for_case(db, case)
    except CaseNotAnalyzedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"case_id": case.id, **result}


@router.post("/cases/{case_id}/review")
def review_case(case_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    """Record a human decision without ever bypassing a hard BLOCK.

    HUMAN_REVIEW is deliberately an operator gate: approval moves the case to
    pending_execution, while rejection is terminal. A BLOCKED case can never
    be approved as-is, and an engaged global kill switch freezes approval.
    """
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if case.status != "human_review":
        raise HTTPException(status_code=409, detail=f"Case is '{case.status}', not awaiting human review")

    if body.decision == "approve" and settings.KILL_SWITCH_ENGAGED:
        raise HTTPException(status_code=409, detail="Kill switch is engaged; approval is paused")

    latest_checks = (
        db.query(PolicyCheck)
        .filter(PolicyCheck.recovery_case_id == case.id)
        .order_by(PolicyCheck.created_at.desc(), PolicyCheck.id.desc())
        .limit(7)
        .all()
    )
    if body.decision == "approve" and any(c.check_name == "opt_out" and not c.passed for c in latest_checks):
        raise HTTPException(status_code=409, detail="Consent policy blocked this action")

    case.status = "pending_execution" if body.decision == "approve" else "rejected"
    db.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="human_review_decision",
            payload={"decision": body.decision, "note": body.note or "", "kill_switch_engaged": settings.KILL_SWITCH_ENGAGED},
        )
    )
    db.commit()
    return {"case_id": case.id, "decision": body.decision, "status": case.status}


@router.post("/cases/{case_id}/execute")
def execute_case_route(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    try:
        result = execute_case(db, case)
    except CaseNotPendingExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"case_id": case.id, **result}
