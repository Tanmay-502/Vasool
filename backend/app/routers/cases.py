"""Case queue, explainability, review, and recovery-outcome surfaces."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db
from app.models import AgentDecision, AuditLog, Order, Payment, PolicyCheck, RecoveryCase
from app.schemas import AuditLedgerEntry, AuditLedgerResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_detail(event_type: str, payload: dict) -> str:
    if event_type == "execution_started":
        return f"Attempting {(payload.get('action_type') or 'recovery').replace('_', ' ')}"
    if event_type == "execution_succeeded":
        short_url = payload.get("short_url")
        return f"Payment link sent — {short_url}" if short_url else "Payment link sent"
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
    if payment is None:
        raise ValueError(f"Recovery case {case.id} has no payment relationship")
    order = payment.order
    if order is None:
        raise ValueError(f"Recovery case {case.id} has no order relationship")
    customer = order.customer
    if customer is None:
        raise ValueError(f"Recovery case {case.id} has no customer relationship")
    outcome = case.outcome
    action = max(case.actions or [], key=lambda row: (row.created_at, row.id), default=None)
    successful_event = getattr(case, "_successful_execution_event", None)
    successful_payload = successful_event.payload if successful_event and isinstance(successful_event.payload, dict) else {}
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
        "payment_link": successful_payload.get("short_url"),
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
    cases = (
        db.query(RecoveryCase)
        .options(
            joinedload(RecoveryCase.payment).joinedload(Payment.order).joinedload(Order.customer),
            selectinload(RecoveryCase.actions),
            joinedload(RecoveryCase.outcome),
        )
        .order_by(RecoveryCase.updated_at.desc(), RecoveryCase.id.desc())
        .limit(safe_limit)
        .all()
    )

    case_ids = [case.id for case in cases]
    events = (
        db.query(AuditLog)
        .filter(
            AuditLog.recovery_case_id.in_(case_ids),
            AuditLog.event_type == "execution_succeeded",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .all()
        if case_ids
        else []
    )
    latest_success_by_case = {}
    for event in events:
        latest_success_by_case.setdefault(event.recovery_case_id, event)

    summaries = []
    for case in cases:
        case._successful_execution_event = latest_success_by_case.get(case.id)
        try:
            summaries.append(_case_summary(case, db))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception("Skipping malformed recovery case id=%s: %s", case.id, exc)

    return {"cases": summaries}


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
    action = db.query(__import__("app.models", fromlist=["Action"]).Action).filter(__import__("app.models", fromlist=["Action"]).Action.recovery_case_id == case.id).order_by(__import__("app.models", fromlist=["Action"]).Action.created_at.desc(), __import__("app.models", fromlist=["Action"]).Action.id.desc()).first()
    return {
        "case": _case_summary(case, db),
        "root_cause": decisions.get("root_cause_agent").output if decisions.get("root_cause_agent") else None,
        "root_cause_meta": ({"confidence": decisions["root_cause_agent"].confidence, "model_used": decisions["root_cause_agent"].model_used, "latency_ms": decisions["root_cause_agent"].latency_ms} if decisions.get("root_cause_agent") else None),
        "strategy": decisions.get("recovery_strategy_agent").output if decisions.get("recovery_strategy_agent") else None,
        "strategy_meta": ({"confidence": decisions["recovery_strategy_agent"].confidence, "model_used": decisions["recovery_strategy_agent"].model_used, "latency_ms": decisions["recovery_strategy_agent"].latency_ms} if decisions.get("recovery_strategy_agent") else None),
        "policy_checks": [{"check_name": check.check_name, "passed": check.passed, "reason": check.reason} for check in reversed(checks)],
        "action": ({"status": action.status, "payment_link_id": action.razorpay_reference} if action else None),
        "outcome": ({"recovered_amount_paise": case.outcome.recovered_amount_paise, "success": case.outcome.success} if case.outcome else None),
    }
