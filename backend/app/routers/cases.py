"""Case queue, explainability, review, and recovery-outcome surfaces."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Action, AgentDecision, AuditLog, RecoveryCase
from app.schemas import AuditLedgerEntry, AuditLedgerResponse

router = APIRouter()


def _build_detail(event_type: str, payload: dict) -> str:
    if event_type == "execution_started":
        return f"Attempting {(payload.get('action_type') or 'recovery').replace('_', ' ')}"
    if event_type == "execution_succeeded":
        short_url = payload.get("short_url")
        return f"Payment link created{f' — {short_url}' if short_url else ''}"
    if event_type == "execution_failed":
        return f"Execution failed: {payload.get('reason', 'unknown error')}"
    if event_type == "human_review_decision":
        return f"Human {payload.get('decision', 'updated')} case"
    if event_type == "recovery_outcome_received":
        event = (payload.get("event") or "recovery").replace("payment_link.", "").replace("_", " ")
        amount = int(payload.get("amount_paid_paise") or 0) / 100
        return f"{event.capitalize()} · ₹{amount:,.2f} verified by webhook"
    return event_type.replace("_", " ").capitalize()


@router.get("/cases/recent", response_model=AuditLedgerResponse)
def get_recent_cases(limit: int = 20, db: Session = Depends(get_db)):
    safe_limit = min(max(limit, 1), 100)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.recovery_case_id.isnot(None))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(safe_limit)
        .all()
    )
    return {"entries": [
        AuditLedgerEntry(id=row.id, case_id=row.recovery_case_id, event_type=row.event_type,
                         detail=_build_detail(row.event_type, row.payload), created_at=row.created_at)
        for row in rows
    ]}


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


def _case_summary(case: RecoveryCase, db: Session) -> dict:
    payment = case.payment
    order = payment.order
    customer = order.customer
    outcome = case.outcome
    action = (
        db.query(Action)
        .filter(Action.recovery_case_id == case.id)
        .order_by(Action.created_at.desc(), Action.id.desc())
        .first()
    )
    successful_event = (
        db.query(AuditLog)
        .filter(AuditLog.recovery_case_id == case.id, AuditLog.event_type == "execution_succeeded")
        .order_by(AuditLog.id.desc())
        .first()
    )
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
        "payment_link": successful_event.payload.get("short_url") if successful_event else None,
        "outcome_amount_paise": outcome.recovered_amount_paise if outcome else 0,
        "outcome_amount_inr": (outcome.recovered_amount_paise / 100) if outcome else 0,
        "outcome_success": outcome.success if outcome else False,
        "action_status": action.status if action else None,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


@router.get("/cases")
def list_cases(limit: int = 25, db: Session = Depends(get_db)):
    safe_limit = min(max(limit, 1), 100)
    cases = db.query(RecoveryCase).order_by(RecoveryCase.updated_at.desc(), RecoveryCase.id.desc()).limit(safe_limit).all()
    return {"cases": [_case_summary(case, db) for case in cases]}


@router.get("/cases/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    decisions = _latest_decisions(db, case.id)
    checks = (
        db.query(__import__("app.models", fromlist=["PolicyCheck"]).PolicyCheck)
        .filter(__import__("app.models", fromlist=["PolicyCheck"]).PolicyCheck.recovery_case_id == case.id)
        .order_by(__import__("app.models", fromlist=["PolicyCheck"]).PolicyCheck.created_at.desc(), __import__("app.models", fromlist=["PolicyCheck"]).PolicyCheck.id.desc())
        .limit(7)
        .all()
    )
    action = db.query(Action).filter(Action.recovery_case_id == case.id).order_by(Action.created_at.desc(), Action.id.desc()).first()
    return {
        "case": _case_summary(case, db),
        "root_cause": decisions.get("root_cause_agent").output if decisions.get("root_cause_agent") else None,
        "root_cause_meta": ({
            "confidence": decisions["root_cause_agent"].confidence,
            "model_used": decisions["root_cause_agent"].model_used,
            "latency_ms": decisions["root_cause_agent"].latency_ms,
        } if decisions.get("root_cause_agent") else None),
        "strategy": decisions.get("recovery_strategy_agent").output if decisions.get("recovery_strategy_agent") else None,
        "strategy_meta": ({
            "confidence": decisions["recovery_strategy_agent"].confidence,
            "model_used": decisions["recovery_strategy_agent"].model_used,
            "latency_ms": decisions["recovery_strategy_agent"].latency_ms,
        } if decisions.get("recovery_strategy_agent") else None),
        "policy_checks": [
            {"check_name": check.check_name, "passed": check.passed, "reason": check.reason}
            for check in reversed(checks)
        ],
        "action": ({"status": action.status, "payment_link_id": action.razorpay_reference} if action else None),
        "outcome": ({"recovered_amount_paise": case.outcome.recovered_amount_paise, "success": case.outcome.success} if case.outcome else None),
    }
