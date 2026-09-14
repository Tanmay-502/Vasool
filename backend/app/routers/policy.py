from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import settings
from app.db import get_db
from app.executor import AutomationPausedError, CaseAlreadyPaidError, CaseNotPendingExecutionError, CircuitOpenError, execute_case
from app.models import AgentDecision, AuditLog, PolicyCheck, RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, TerminalCaseError, run_policy_for_case
from app.rate_limit import RateLimitExceeded
from app.razorpay_client import RazorpayError
from app.state import get_kill_switch
from app.status import TERMINAL_STATUSES

router = APIRouter()
_AUTO_EXECUTABLE_ACTIONS = {"retry_now", "retry_later", "send_payment_link"}


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


@router.post("/cases/{case_id}/evaluate-policy", dependencies=[Depends(require_api_key)])
def evaluate_case_policy(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    try:
        result = run_policy_for_case(db, case)
    except (CaseNotAnalyzedError, TerminalCaseError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"case_id": case.id, **result}


@router.post("/cases/{case_id}/review", dependencies=[Depends(require_api_key)])
def review_case(case_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if case.status in TERMINAL_STATUSES or case.payment.status == "paid":
        raise HTTPException(status_code=409, detail=f"Case {case_id} is terminal or already paid and cannot be reviewed")
    if case.status != "human_review":
        raise HTTPException(status_code=409, detail=f"Case is '{case.status}', not awaiting human review")
    kill_switch_engaged = get_kill_switch(db)
    if body.decision == "approve" and kill_switch_engaged:
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
        .limit(7).all()
    )

    if body.decision == "approve":
        if strategy is None:
            raise HTTPException(status_code=409, detail="No recovery strategy exists to approve")
        action = strategy.output.get("action")
        if action not in _AUTO_EXECUTABLE_ACTIONS:
            raise HTTPException(status_code=409, detail=f"'{action}' is not an executable recovery action")
        hard_failures = {check.check_name for check in latest_checks if not check.passed and check.check_name in {"opt_out", "action_type"}}
        if hard_failures:
            raise HTTPException(status_code=409, detail="One or more hard policy gates still block this action")

    case.status = "pending_execution" if body.decision == "approve" else "rejected"
    db.add(AuditLog(recovery_case_id=case.id, event_type="human_review_decision", payload={"decision": body.decision, "note": body.note or "", "approved_action": strategy.output.get("action") if strategy else None, "kill_switch_engaged": kill_switch_engaged}))
    db.commit()
    return {"case_id": case.id, "decision": body.decision, "status": case.status}


@router.post("/cases/{case_id}/execute", dependencies=[Depends(require_api_key)])
def execute_case_route(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    try:
        result = execute_case(db, case)
    except (CaseNotPendingExecutionError, CaseAlreadyPaidError) as exc:
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
