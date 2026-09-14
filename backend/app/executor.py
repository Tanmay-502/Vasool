"""Idempotent, policy-gated execution against Razorpay Test Mode."""
import hashlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.agents import circuit_breaker
from app.config import settings
from app.models import Action, AgentDecision, AuditLog, RecoveryCase
from app.rate_limit import RateLimitExceeded, check_and_record
from app.razorpay_client import RazorpayClient, RazorpayError
from app.state import get_kill_switch
from app.status import TERMINAL_STATUSES

RAZORPAY_RATE_LIMIT_PER_MINUTE = 15
RAZORPAY_RATE_LIMIT_KEY = "razorpay_execute"
_AUTO_EXECUTABLE_ACTIONS = {"retry_now", "retry_later", "send_payment_link"}
_NOTIFY_ACTIONS = {"send_payment_link"}


class CaseNotPendingExecutionError(Exception):
    """Raised when the case is not in an executable recovery state."""


class CircuitOpenError(Exception):
    """Raised when the Razorpay circuit breaker is open."""


class AutomationPausedError(Exception):
    """Raised when the global kill switch blocks outbound automation."""


class CaseAlreadyPaidError(Exception):
    """Raised as a defense-in-depth backstop before any Razorpay call."""


def _latest_strategy_decision(db: Session, case_id: int) -> AgentDecision | None:
    return (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case_id, AgentDecision.agent_name == "recovery_strategy_agent")
        .order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc())
        .first()
    )


def _stable_execution_key(case_id: int, decision_id: int) -> str:
    raw = f"vasool:testmode:case:{case_id}:strategy:{decision_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _fail(db: Session, case: RecoveryCase, action: Action, reason: str) -> None:
    action.status = "failed"
    case.status = "execution_failed"
    db.add(AuditLog(recovery_case_id=case.id, event_type="execution_failed", payload={"reason": reason, "idempotency_key": action.idempotency_key}))
    db.commit()


def _payment_link_from_audit(db: Session, case_id: int, idempotency_key: str) -> str | None:
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.recovery_case_id == case_id, AuditLog.event_type == "execution_succeeded")
        .order_by(AuditLog.id.desc())
        .all()
    )
    for entry in rows:
        if entry.payload.get("idempotency_key") == idempotency_key:
            return entry.payload.get("short_url")
    return None


def execute_case(db: Session, case: RecoveryCase, razorpay: RazorpayClient | None = None) -> dict:
    # Payment state is an absolute backstop: once paid, there is no safe replay.
    if case.payment.status == "paid":
        raise CaseAlreadyPaidError(f"Case {case.id} payment is already paid; no recovery call is allowed")

    strategy_decision = _latest_strategy_decision(db, case.id)
    if strategy_decision is None:
        raise CaseNotPendingExecutionError("Recovery strategy decision is missing")
    action_type = strategy_decision.output.get("action")
    if action_type not in _AUTO_EXECUTABLE_ACTIONS:
        raise CaseNotPendingExecutionError(f"Action '{action_type}' is not auto-executable")

    stable_key = _stable_execution_key(case.id, strategy_decision.id)
    action = db.query(Action).filter(Action.idempotency_key == stable_key).first()

    # Safe replay path comes before the terminal status guard. We may return an
    # already-sent action, but we never create a new provider call.
    if action is not None and action.status in {"sent", "paid", "partially_paid"}:
        return {
            "action_type": action.action_type,
            "action_status": action.status,
            "razorpay_reference": action.razorpay_reference,
            "payment_link": _payment_link_from_audit(db, case.id, action.idempotency_key),
            "case_status": case.status,
            "idempotent_replay": True,
        }

    if action is not None and action.status == "scheduled" and action.not_before and datetime.utcnow() < action.not_before:
        return {
            "action_type": action.action_type,
            "action_status": action.status,
            "razorpay_reference": None,
            "payment_link": None,
            "case_status": case.status,
            "not_before": action.not_before.isoformat(),
            "idempotent_replay": True,
        }

    if case.status in TERMINAL_STATUSES:
        raise CaseNotPendingExecutionError(f"Case {case.id} is terminal and cannot execute")
    if case.status not in {"pending_execution", "execution_failed", "scheduled_retry"}:
        raise CaseNotPendingExecutionError(
            f"Case {case.id} has status '{case.status}' and cannot execute. A policy-approved recovery must be pending execution."
        )
    if get_kill_switch(db):
        raise AutomationPausedError("Global kill switch is engaged; outbound recovery automation is paused")

    payment = case.payment
    if payment.status == "paid":
        raise CaseAlreadyPaidError(f"Case {case.id} payment is already paid; no recovery call is allowed")

    if action is None:
        action = Action(recovery_case_id=case.id, action_type=action_type, status="pending", idempotency_key=stable_key)
        db.add(action)
        db.flush()

    if action_type == "retry_later" and action.status == "pending":
        action.not_before = datetime.utcnow() + timedelta(minutes=max(settings.RETRY_LATER_DELAY_MINUTES, 1))
        action.status = "scheduled"
        case.status = "scheduled_retry"
        db.add(AuditLog(
            recovery_case_id=case.id,
            event_type="execution_scheduled",
            payload={"action_type": action_type, "idempotency_key": action.idempotency_key, "not_before": action.not_before.isoformat()},
        ))
        db.commit()
        return {
            "action_type": action_type,
            "action_status": action.status,
            "razorpay_reference": None,
            "payment_link": None,
            "case_status": case.status,
            "not_before": action.not_before.isoformat(),
            "idempotent_replay": False,
        }

    razorpay = razorpay if razorpay is not None else RazorpayClient()
    customer = payment.order.customer

    action.status = "pending"
    db.add(AuditLog(recovery_case_id=case.id, event_type="execution_started", payload={"action_type": action_type, "idempotency_key": action.idempotency_key}))
    db.commit()

    if get_kill_switch(db):
        _fail(db, case, action, "kill switch engaged before outbound call")
        raise AutomationPausedError("Global kill switch is engaged; outbound recovery automation is paused")
    if payment.status == "paid":
        _fail(db, case, action, "payment became paid before outbound call")
        raise CaseAlreadyPaidError(f"Case {case.id} payment is already paid; no recovery call is allowed")
    if circuit_breaker.is_open("razorpay"):
        _fail(db, case, action, "razorpay circuit open, call skipped")
        raise CircuitOpenError(f"Razorpay circuit open, case {case.id} not attempted")

    try:
        check_and_record(RAZORPAY_RATE_LIMIT_PER_MINUTE, key=RAZORPAY_RATE_LIMIT_KEY)
    except RateLimitExceeded:
        _fail(db, case, action, "rate limit exceeded")
        raise

    try:
        result = razorpay.create_payment_link(
            amount_paise=payment.order.amount_paise,
            reference_id=action.idempotency_key,
            customer_name=customer.name,
            customer_email=customer.email,
            customer_phone=customer.phone,
            notify=action_type in _NOTIFY_ACTIONS,
        )
    except RazorpayError as exc:
        circuit_breaker.record_failure("razorpay")
        _fail(db, case, action, str(exc))
        raise

    circuit_breaker.record_success("razorpay")
    action.status = "sent"
    action.razorpay_reference = result["id"]
    case.status = "executed"
    db.add(AuditLog(
        recovery_case_id=case.id,
        event_type="execution_succeeded",
        payload={"razorpay_payment_link_id": result["id"], "short_url": result.get("short_url"), "idempotency_key": action.idempotency_key},
    ))
    db.commit()

    return {
        "action_type": action_type,
        "action_status": action.status,
        "razorpay_reference": action.razorpay_reference,
        "payment_link": result.get("short_url"),
        "case_status": case.status,
        "idempotent_replay": False,
    }
