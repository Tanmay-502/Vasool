from app.models import AgentDecision, AuditLog, Customer, Merchant, Order, Payment, PolicyCheck, RecoveryCase


def _seed_case(db):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()
    customer = Customer(
        merchant_id=merchant.id, name="Test User", email="t@example.com", phone="9000000000"
    )
    db.add(customer)
    db.flush()
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=20000, status="failed")
    db.add(order)
    db.flush()
    payment = Payment(
        order_id=order.id, method="upi", status="failed", failure_reason="otp_timeout", attempt_number=1
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="executed")
    db.add(case)
    db.commit()
    return case


def test_recent_cases_empty_when_no_audit_log(client):
    response = client.get("/cases/recent")
    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_recent_cases_returns_most_recent_first(client, db_session):
    case = _seed_case(db_session)
    db_session.add(
        AuditLog(recovery_case_id=case.id, event_type="execution_started", payload={"action_type": "retry_now"})
    )
    db_session.commit()
    db_session.add(
        AuditLog(
            recovery_case_id=case.id,
            event_type="execution_succeeded",
            payload={"short_url": "https://rzp.io/i/abc"},
        )
    )
    db_session.commit()

    response = client.get("/cases/recent")
    data = response.json()["entries"]

    assert len(data) == 2
    assert data[0]["event_type"] == "execution_succeeded"
    assert data[0]["detail"] == "Payment link sent — https://rzp.io/i/abc"
    assert data[1]["event_type"] == "execution_started"
    assert data[1]["detail"] == "Attempting retry now"
    assert data[0]["case_id"] == case.id


def test_recent_cases_respects_limit(client, db_session):
    case = _seed_case(db_session)
    for _ in range(5):
        db_session.add(
            AuditLog(recovery_case_id=case.id, event_type="execution_started", payload={"action_type": "retry_now"})
        )
        db_session.commit()

    response = client.get("/cases/recent?limit=2")
    assert len(response.json()["entries"]) == 2


def test_case_list_and_detail_include_decision_context(client, db_session):
    case = _seed_case(db_session)
    db_session.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="root_cause_agent",
            model_used="rules_fallback:rules-v1",
            input_snapshot={},
            output={"root_cause_category": "otp_timeout", "reasoning": "Transient timeout"},
            confidence=0.88,
        )
    )
    db_session.add(
        PolicyCheck(
            recovery_case_id=case.id,
            check_name="confidence_floor",
            passed=True,
            reason="confidence meets floor",
        )
    )
    db_session.commit()

    listing = client.get("/cases")
    assert listing.status_code == 200
    assert listing.json()["cases"][0]["id"] == case.id

    detail = client.get(f"/cases/{case.id}")
    assert detail.status_code == 200
    assert detail.json()["root_cause"]["root_cause_category"] == "otp_timeout"
    assert detail.json()["policy_checks"][0]["check_name"] == "confidence_floor"