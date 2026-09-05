"""
Read-only case-listing endpoints for the dashboard. Currently just the
recent-activity feed backing the frontend's audit ledger — kept separate
from routers/agents.py (pipeline actions) and routers/policy.py (policy +
execution actions) since this is a pure read, not a state transition.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AgentDecision, AuditLog, PolicyCheck, RecoveryCase
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


def _latest_decisions(db: Session, case_id: int) -> dict[str, AgentDecision]:
    decisions = (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case_id)
        .order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc())
        .all()
    )
    latest: dict[str, AgentDecision] = {}
    for decision in decisions:
        latest.setdefault(decision.agent_name, decision)
    return latest


def _case_summary(case: RecoveryCase) -> dict:
    payment = case.payment
    order = payment.order
    customer = order.customer
    return {
        "id": case.id,
        "status": case.status,
        "amount_paise": order.amount_paise,
        "amount_inr": order.amount_paise / 100,
        "currency": order.currency,
        "failure_reason": payment.failure_reason or "unknown",
        "payment_method": payment.method,
        "attempt_number": payment.attempt_number,
        "customer_name": customer.name,
        "customer_opted_out": customer.opted_out,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


@router.get("/cases")
def list_cases(limit: int = 25, db: Session = Depends(get_db)):
    cases = (
        db.query(RecoveryCase)
        .order_by(RecoveryCase.updated_at.desc(), RecoveryCase.id.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    return {"cases": [_case_summary(case) for case in cases]}


@router.get("/cases/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    decisions = _latest_decisions(db, case.id)
    checks = (
        db.query(PolicyCheck)
        .filter(PolicyCheck.recovery_case_id == case.id)
        .order_by(PolicyCheck.created_at.desc(), PolicyCheck.id.desc())
        .limit(7)
        .all()
    )
    return {
        "case": _case_summary(case),
        "root_cause": decisions.get("root_cause_agent").output if decisions.get("root_cause_agent") else None,
        "root_cause_meta": (
            {
                "confidence": decisions["root_cause_agent"].confidence,
                "model_used": decisions["root_cause_agent"].model_used,
                "latency_ms": decisions["root_cause_agent"].latency_ms,
            }
            if decisions.get("root_cause_agent")
            else None
        ),
        "strategy": decisions.get("recovery_strategy_agent").output if decisions.get("recovery_strategy_agent") else None,
        "strategy_meta": (
            {
                "confidence": decisions["recovery_strategy_agent"].confidence,
                "model_used": decisions["recovery_strategy_agent"].model_used,
                "latency_ms": decisions["recovery_strategy_agent"].latency_ms,
            }
            if decisions.get("recovery_strategy_agent")
            else None
        ),
        "policy_checks": [
            {"check_name": check.check_name, "passed": check.passed, "reason": check.reason}
            for check in reversed(checks)
        ],
    }