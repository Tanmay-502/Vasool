from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.executor import AutomationPausedError, CaseNotPendingExecutionError, CircuitOpenError, execute_case
from app.models import AgentDecision, AuditLog, PolicyCheck, RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, run_policy_for_case
from app.rate_limit import RateLimitExceeded
from app.razorpay_client import RazorpayError

router = APIRouter()
_AUTO_EXECUTABLE_ACTIONS = {"retry_now", "retry_later", "send_payment_link"}


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
    """Record a human decision without bypassing hard safety gates."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if case.status != "human_review":
        raise HTTPException(status_code=409, detail=f"Case is '{case.status}', not awaiting human review")

    if body.decision == "approve" and settings.KILL_SWITCH_ENGAGED:
        raise HTTPException(status_code=409, detail="Kill switch is engaged; approval is paused")

    strategy = (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case.id, AgentDecision.agent_name == "recovery_strategy_agent")
        .order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc())
        .first()
    )
    latest_checks = (
        db.query(PolicyCheck)
        .filter(PolicyCheck.recovery_case_id == case.id)
        .order_by(PolicyCheck.created_at.desc(), PolicyCheck.id.desc())
        .limit(7)
        .all()
    )

    if body.decision == "approve":
        if strategy is None:
            raise HTTPException(status_code=409, detail="No recovery strategy exists to approve")
        action = strategy.output.get("action")
        if action not in _AUTO_EXECUTABLE_ACTIONS:
            raise HTTPException(status_code=409, detail=f"'{action}' is not an executable recovery action")
        hard_failures = {
            check.check_name
            for check in latest_checks
            if not check.passed and check.check_name in {"opt_out", "action_type"}
        }
        if hard_failures:
            raise HTTPException(status_code=409, detail="One or more hard policy gates still block this action")

    case.status = "pending_execution" if body.decision == "approve" else "rejected"
    db.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="human_review_decision",
            payload={
                "decision": body.decision,
                "note": body.note or "",
                "approved_action": strategy.output.get("action") if strategy else None,
                "kill_switch_engaged": settings.KILL_SWITCH_ENGAGED,
            },
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
    except AutomationPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"case_id": case.id, **result}
