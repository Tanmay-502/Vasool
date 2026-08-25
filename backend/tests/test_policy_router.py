from unittest.mock import patch

from app.models import AgentDecision, Customer, Merchant, Order, Payment, RecoveryCase
from app.razorpay_client import RazorpayClient


def _seed_analyzed_case(db, *, action="retry_now", confidence=0.9, root_cause_category="otp_timeout"):
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
        order_id=order.id, method="upi", status="failed", failure_reason=root_cause_category, attempt_number=1
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="analyzed")
    db.add(case)
    db.flush()
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="root_cause_agent",
            model_used="rules_fallback:rules-v1",
            input_snapshot={},
            output={"root_cause_category": root_cause_category, "is_transient": True, "confidence": 0.8, "reasoning": "t"},
            confidence=0.8,
        )
    )
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="recovery_strategy_agent",
            model_used="rules_fallback:rules-v1",
            input_snapshot={},
            output={"action": action, "confidence": confidence, "reasoning": "t"},
            confidence=confidence,
        )
    )
    db.commit()
    return case


def test_evaluate_policy_endpoint_returns_verdict(client, db_session):
    case = _seed_analyzed_case(db_session)
    response = client.post(f"/cases/{case.id}/evaluate-policy")
    assert response.status_code == 200
    data = response.json()
    assert data["verdict"] == "EXECUTE"
    assert len(data["checks"]) == 7


def test_evaluate_policy_404s_for_unknown_case(client):
    response = client.post("/cases/999999/evaluate-policy")
    assert response.status_code == 404


def test_evaluate_policy_409s_when_case_never_analyzed(client, db_session):
    merchant = Merchant(name="M")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, name="C", email="c@example.com", phone="9000000000")
    db_session.add(customer)
    db_session.flush()
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=1000, status="failed")
    db_session.add(order)
    db_session.flush()
    payment = Payment(order_id=order.id, method="upi", status="failed", attempt_number=1)
    db_session.add(payment)
    db_session.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db_session.add(case)
    db_session.commit()

    response = client.post(f"/cases/{case.id}/evaluate-policy")
    assert response.status_code == 409


def test_execute_404s_for_unknown_case(client):
    response = client.post("/cases/999999/execute")
    assert response.status_code == 404


def test_execute_409s_when_not_pending_execution(client, db_session):
    case = _seed_analyzed_case(db_session)
    response = client.post(f"/cases/{case.id}/execute")
    assert response.status_code == 409


def test_full_flow_analyze_to_execute_via_router(client, db_session):
    case = _seed_analyzed_case(db_session, action="retry_now", confidence=0.9)

    policy_response = client.post(f"/cases/{case.id}/evaluate-policy")
    assert policy_response.json()["verdict"] == "EXECUTE"

    with patch.object(
        RazorpayClient,
        "create_payment_link",
        return_value={"id": "plink_ROUTER_TEST", "short_url": "https://rzp.io/i/router"},
    ):
        execute_response = client.post(f"/cases/{case.id}/execute")

    assert execute_response.status_code == 200
    data = execute_response.json()
    assert data["case_status"] == "executed"
    assert data["razorpay_reference"] == "plink_ROUTER_TEST"


def test_kill_switch_status_defaults_off(client):
    response = client.get("/admin/kill-switch")
    assert response.json() == {"kill_switch_engaged": False}


def test_kill_switch_engage_forces_human_review(client, db_session):
    case = _seed_analyzed_case(db_session, action="retry_now", confidence=0.95)

    engage = client.post("/admin/kill-switch/engage")
    assert engage.json() == {"kill_switch_engaged": True}

    policy_response = client.post(f"/cases/{case.id}/evaluate-policy")
    assert policy_response.json()["verdict"] == "HUMAN_REVIEW"

    disengage = client.post("/admin/kill-switch/disengage")
    assert disengage.json() == {"kill_switch_engaged": False}