import hashlib
import hmac
import json

from app.config import settings
from app.models import Action, AgentDecision, AuditLog, Customer, Merchant, Order, Outcome, Payment, RecoveryCase
from app.routers.webhooks import verify_webhook_signature


def _signed_payload(payload: dict, secret: str, event_id: str):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, signature, {"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": event_id}


def _seed_executed_case(db):
    merchant = Merchant(name="Webhook Merchant")
    customer = Customer(merchant=merchant, name="Webhook User", email="webhook@example.com", phone="9000000000")
    order = Order(merchant=merchant, customer=customer, amount_paise=25000, currency="INR", status="failed")
    payment = Payment(order=order, method="upi", status="failed", failure_reason="otp_timeout", attempt_number=1)
    case = RecoveryCase(payment=payment, status="executed")
    db.add_all([merchant, customer, order, payment, case])
    db.flush()
    action = Action(recovery_case_id=case.id, action_type="send_payment_link", status="sent", razorpay_reference="plink_123")
    db.add(action)
    db.commit()
    return case, action


def _payment_link_payload(action: Action, event: str = "payment_link.paid", amount_paid=25000):
    payload = {
        "event": event,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": action.razorpay_reference,
                    "reference_id": action.idempotency_key,
                    "amount": 25000,
                    "amount_paid": amount_paid,
                    "currency": "INR",
                }
            },
            "order": {"entity": {"amount_paid": amount_paid}},
            "payment": {"entity": {"id": "pay_123"}},
        },
    }
    return payload


def test_webhook_signature_uses_raw_body():
    body = b'{"event":"payment_link.paid"}'
    secret = "secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, signature, secret) is True
    assert verify_webhook_signature(body + b" ", signature, secret) is False


def test_paid_webhook_marks_case_recovered(client, db_session, monkeypatch):
    secret = "webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    case, action = _seed_executed_case(db_session)
    payload = _payment_link_payload(action)
    raw, signature, headers = _signed_payload(payload, secret, "evt_paid_1")

    response = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert response.status_code == 200
    assert response.json()["case_status"] == "resolved"
    db_session.refresh(case)
    db_session.refresh(action)
    assert case.status == "resolved"
    assert case.payment.status == "paid"
    assert case.payment.razorpay_payment_id == "pay_123"
    assert action.status == "paid"
    outcome = db_session.query(Outcome).filter(Outcome.recovery_case_id == case.id).one()
    assert outcome.success is True
    assert outcome.recovered_amount_paise == 25000


def test_duplicate_event_id_is_idempotent(client, db_session, monkeypatch):
    secret = "webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    case, action = _seed_executed_case(db_session)
    raw, signature, headers = _signed_payload(_payment_link_payload(action), secret, "evt_duplicate")

    first = client.post("/webhooks/razorpay", content=raw, headers=headers)
    second = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert db_session.query(AuditLog).filter(AuditLog.recovery_case_id == case.id, AuditLog.event_type == "recovery_outcome_received").count() == 1


def test_invalid_signature_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "secret")
    response = client.post(
        "/webhooks/razorpay",
        content=b'{"event":"payment_link.paid"}',
        headers={"X-Razorpay-Signature": "bad", "X-Razorpay-Event-Id": "evt_bad"},
    )
    assert response.status_code == 401


def test_missing_event_id_rejected(client, monkeypatch):
    secret = "secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    raw = b'{"event":"payment_link.paid"}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    response = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": signature})
    assert response.status_code == 400


def test_paid_event_cannot_be_downgraded_by_late_expiry(client, db_session, monkeypatch):
    secret = "webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    case, action = _seed_executed_case(db_session)

    raw_paid, sig_paid, headers_paid = _signed_payload(_payment_link_payload(action), secret, "evt_paid_monotonic")
    assert client.post("/webhooks/razorpay", content=raw_paid, headers=headers_paid).status_code == 200

    expired = _payment_link_payload(action, event="payment_link.expired", amount_paid=25000)
    raw_expired, sig_expired, headers_expired = _signed_payload(expired, secret, "evt_expired_late")
    assert client.post("/webhooks/razorpay", content=raw_expired, headers=headers_expired).status_code == 200

    db_session.refresh(case)
    assert case.status == "resolved"
    assert case.outcome.success is True


def test_partial_paid_records_partial_recovery(client, db_session, monkeypatch):
    secret = "webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    case, action = _seed_executed_case(db_session)
    payload = _payment_link_payload(action, event="payment_link.partially_paid", amount_paid=10000)
    raw, signature, headers = _signed_payload(payload, secret, "evt_partial")

    response = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert response.status_code == 200
    db_session.refresh(case)
    assert case.status == "partially_recovered"
    assert case.outcome.recovered_amount_paise == 10000
    assert case.outcome.success is False


def test_unmatched_payment_link_is_ignored(client, monkeypatch):
    secret = "secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    payload = {
        "event": "payment_link.paid",
        "payload": {"payment_link": {"entity": {"id": "plink_missing", "reference_id": "missing"}}},
    }
    raw, signature, headers = _signed_payload(payload, secret, "evt_unmatched")
    response = client.post("/webhooks/razorpay", content=raw, headers=headers)
    assert response.status_code == 200
    assert response.json()["reason"] == "unmatched_payment_link"
