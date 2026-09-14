"""Verified Razorpay Payment Link webhooks.

The handler authenticates the raw body with HMAC-SHA256, deduplicates by
Razorpay's event id, and treats webhook state as the source of truth for
recovery outcomes. Out-of-order terminal events never downgrade a case that
is already verified as paid.
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

_TRACKED_EVENTS = {
    "payment_link.paid",
    "payment_link.partially_paid",
    "payment_link.cancelled",
    "payment_link.expired",
}


def verify_webhook_signature(raw_body: bytes, received_signature: str | None, secret: str) -> bool:
    if not received_signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


def _already_processed(db: Session, event_id: str) -> bool:
    recent_events = (
        db.query(AuditLog)
        .filter(AuditLog.event_type == "webhook_processed")
        .order_by(AuditLog.id.desc())
        .limit(500)
        .all()
    )
    return any(row.payload.get("event_id") == event_id for row in recent_events)


def _link_entity(payload: dict) -> dict:
    return payload.get("payment_link", {}).get("entity", {}) or {}


def _find_action(db: Session, payment_link: dict) -> Action | None:
    reference_id = payment_link.get("reference_id")
    link_id = payment_link.get("id")
    if reference_id:
        action = db.query(Action).filter(Action.idempotency_key == reference_id).first()
        if action:
            return action
    if link_id:
        return db.query(Action).filter(Action.razorpay_reference == link_id).first()
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
    if event not in _TRACKED_EVENTS:
        db.add(
            AuditLog(
                recovery_case_id=None,
                event_type="webhook_processed",
                payload={"event_id": event_id, "event": event, "ignored": True},
            )
        )
        db.commit()
        return {"ok": True, "ignored": True}

    payment_link = _link_entity(body.get("payload", {}))
    action = _find_action(db, payment_link)
    if action is None:
        db.add(
            AuditLog(
                recovery_case_id=None,
                event_type="webhook_processed",
                payload={
                    "event_id": event_id,
                    "event": event,
                    "ignored": True,
                    "reason": "unmatched_payment_link",
                },
            )
        )
        db.commit()
        return {"ok": True, "ignored": True, "reason": "unmatched_payment_link"}

    case = db.get(RecoveryCase, action.recovery_case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case for action not found")

    payment = case.payment
    paid_amount = _amount_paid(event, body.get("payload", {}), payment_link)
    payment_event = body.get("payload", {}).get("payment", {}).get("entity", {}) or {}

    # Payment is terminal. Webhook delivery order is not a business invariant;
    # cancellation/expiry/partial events must never downgrade verified payment.
    if event == "payment_link.paid":
        action.status = "paid"
        case.status = "resolved"
        payment.status = "paid"
        payment.razorpay_payment_id = payment_event.get("id") or payment.razorpay_payment_id
        outcome = case.outcome or Outcome(recovery_case_id=case.id)
        outcome.recovered_amount_paise = max(outcome.recovered_amount_paise or 0, paid_amount)
        outcome.success = True
        db.add(outcome)
    elif case.status != "resolved":
        if event == "payment_link.partially_paid":
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
