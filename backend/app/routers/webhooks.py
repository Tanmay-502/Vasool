"""Razorpay webhook ingestion for verified recovery outcomes.

The handler verifies the HMAC-SHA256 signature over the *raw* request body,
uses X-Razorpay-Event-Id for idempotency, and never trusts client-side state to
mark money as recovered. Payment Link events update the matching Action,
RecoveryCase, Payment and Outcome rows and append an audit event.
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Action, AuditLog, Outcome, RecoveryCase

router = APIRouter()

_PAYMENT_LINK_EVENTS = {
    "payment_link.paid": "resolved",
    "payment_link.partially_paid": "partially_recovered",
    "payment_link.cancelled": "recovery_cancelled",
    "payment_link.expired": "recovery_expired",
}


def verify_webhook_signature(raw_body: bytes, received_signature: str | None, secret: str) -> bool:
    if not received_signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


def _already_processed(db: Session, event_id: str) -> bool:
    return (
        db.query(AuditLog.id)
        .filter(AuditLog.event_type == "webhook_processed")
        .order_by(AuditLog.id.desc())
        .all()
    and any(
        row.payload.get("event_id") == event_id
        for row in db.query(AuditLog)
        .filter(AuditLog.event_type == "webhook_processed")
        .order_by(AuditLog.id.desc())
        .limit(500)
        .all()
    )
    )


def _link_entity(payload: dict) -> dict:
    return payload.get("payment_link", {}).get("entity", {}) or {}


def _find_action(db: Session, payment_link: dict) -> Action | None:
    reference_id = payment_link.get("reference_id")
    link_id = payment_link.get("id")
    query = db.query(Action)
    if reference_id:
        action = query.filter(Action.idempotency_key == reference_id).first()
        if action:
            return action
    if link_id:
        return query.filter(Action.razorpay_reference == link_id).first()
    return None


def _amount_paid(event: str, payload: dict, payment_link: dict) -> int:
    if event == "payment_link.paid":
        order = payload.get("order", {}).get("entity", {}) or {}
        return int(order.get("amount_paid") or payment_link.get("amount_paid") or payment_link.get("amount") or 0)
    return int(payment_link.get("amount_paid") or 0)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature")
    event_id = request.headers.get("x-razorpay-event-id")

    if not settings.RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret is not configured")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Event-Id")
    if not verify_webhook_signature(raw_body, signature, settings.RAZORPAY_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Razorpay webhook signature")

    if _already_processed(db, event_id):
        return {"ok": True, "duplicate": True}

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON") from exc

    event = body.get("event")
    if event not in _PAYMENT_LINK_EVENTS:
        db.add(AuditLog(recovery_case_id=None, event_type="webhook_processed", payload={"event_id": event_id, "event": event, "ignored": True}))
        db.commit()
        return {"ok": True, "ignored": True}

    payment_link = _link_entity(body.get("payload", {}))
    action = _find_action(db, payment_link)
    if action is None:
        db.add(AuditLog(recovery_case_id=None, event_type="webhook_processed", payload={"event_id": event_id, "event": event, "ignored": True, "reason": "unmatched_payment_link"}))
        db.commit()
        return {"ok": True, "ignored": True, "reason": "unmatched_payment_link"}

    case = db.get(RecoveryCase, action.recovery_case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case for action not found")

    paid_amount = _amount_paid(event, body.get("payload", {}), payment_link)
    if event == "payment_link.paid":
        action.status = "paid"
        case.status = "resolved"
        case.payment.status = "paid"
        case.payment.razorpay_payment_id = (
            body.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
        ) or case.payment.razorpay_payment_id
        outcome = case.outcome or Outcome(recovery_case_id=case.id)
        outcome.recovered_amount_paise = max(outcome.recovered_amount_paise or 0, paid_amount)
        outcome.success = True
        db.add(outcome)
    elif event == "payment_link.partially_paid":
        action.status = "partially_paid"
        case.status = "partially_recovered"
        outcome = case.outcome or Outcome(recovery_case_id=case.id)
        outcome.recovered_amount_paise = max(outcome.recovered_amount_paise or 0, paid_amount)
        outcome.success = False
        db.add(outcome)
    elif event == "payment_link.cancelled":
        action.status = "cancelled"
        case.status = "recovery_cancelled"
    elif event == "payment_link.expired":
        action.status = "expired"
        case.status = "recovery_expired"

    db.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="recovery_outcome_received",
            payload={
                "event_id": event_id,
                "event": event,
                "payment_link_id": payment_link.get("id"),
                "reference_id": payment_link.get("reference_id"),
                "amount_paid_paise": paid_amount,
                "signature_verified": True,
            },
        )
    )
    db.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="webhook_processed",
            payload={"event_id": event_id, "event": event, "ignored": False},
        )
    )
    db.commit()

    return {
        "ok": True,
        "duplicate": False,
        "event": event,
        "case_id": case.id,
        "case_status": case.status,
        "recovered_amount_paise": paid_amount,
    }
