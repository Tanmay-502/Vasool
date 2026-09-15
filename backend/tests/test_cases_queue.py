from datetime import datetime

from app.models import AuditLog, Customer, Merchant, Order, Payment, RecoveryCase


def test_cases_queue_survives_malformed_success_audit_payload(client, db_session):
    merchant = Merchant(name="Test Merchant")
    customer = Customer(
        merchant=merchant,
        name="Test Customer",
        email="test@example.com",
        phone="9999999999",
    )
    order = Order(
        merchant=merchant,
        customer=customer,
        amount_paise=50000,
        currency="INR",
        status="failed",
    )
    payment = Payment(
        order=order,
        method="upi",
        status="failed",
        failure_reason="insufficient_funds",
        attempt_number=1,
    )
    case = RecoveryCase(
        payment=payment,
        status="human_review",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add_all([merchant, customer, order, payment, case])
    db_session.flush()
    db_session.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="execution_succeeded",
            payload=["unexpected", "non-dict", "payload"],
        )
    )
    db_session.commit()

    response = client.get("/cases")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["cases"]) == 1
    assert payload["cases"][0]["id"] == case.id
    assert payload["cases"][0]["payment_link"] is None
