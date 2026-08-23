from app.agents import llm_clients
from app.models import Customer, Merchant, Order, Payment, RecoveryCase
from app.rate_limit import check_and_record
from app.routers import agents as agents_router


def _seed_one_failed_case(db):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()
    customer = Customer(
        merchant_id=merchant.id, name="Test User", email="t@example.com", phone="9000000000"
    )
    db.add(customer)
    db.flush()
    order = Order(
        merchant_id=merchant.id, customer_id=customer.id, amount_paise=20000, status="failed"
    )
    db.add(order)
    db.flush()
    payment = Payment(
        order_id=order.id,
        method="upi",
        status="failed",
        failure_reason="risk_flagged",
        attempt_number=1,
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db.add(case)
    db.commit()
    return case


def test_analyze_case_returns_pipeline_result(client, db_session, monkeypatch):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    case = _seed_one_failed_case(db_session)

    response = client.post(f"/cases/{case.id}/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == case.id
    assert data["root_cause"]["root_cause_category"] == "risk_flagged"
    # risk_flagged must always escalate, even on the rules-fallback tier
    assert data["strategy"]["action"] == "escalate_human"


def test_analyze_case_404s_for_unknown_case(client):
    response = client.post("/cases/999999/analyze")
    assert response.status_code == 404

def test_analyze_case_409s_when_already_analyzed_without_force(client, db_session):
    case = _seed_one_failed_case(db_session)
    assert client.post(f"/cases/{case.id}/analyze").status_code == 200
    assert client.post(f"/cases/{case.id}/analyze").status_code == 409


def test_analyze_case_allows_re_analysis_with_force(client, db_session):
    case = _seed_one_failed_case(db_session)
    client.post(f"/cases/{case.id}/analyze")
    assert client.post(f"/cases/{case.id}/analyze?force=true").status_code == 200


def test_analyze_case_returns_429_when_rate_limited(client, db_session):
    case = _seed_one_failed_case(db_session)
    for _ in range(agents_router.ANALYZE_RATE_LIMIT_PER_MINUTE):
        check_and_record(agents_router.ANALYZE_RATE_LIMIT_PER_MINUTE)
    assert client.post(f"/cases/{case.id}/analyze").status_code == 429