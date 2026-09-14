from datetime import datetime

import pytest

from app.executor import CaseAlreadyPaidError, execute_case
from app.models import AgentDecision, Customer, Merchant, Order, Payment, RecoveryCase
from app.policy_runner import TerminalCaseError, run_policy_for_case
from app.routers.metrics import get_metrics


def _case(db, *, case_status="detected", payment_status="failed", amount=10000):
    merchant = Merchant(name="Test Merchant")
    customer = Customer(merchant=merchant, name="Test User", email="user@example.com", phone="9999999999")
    order = Order(merchant=merchant, customer=customer, amount_paise=amount, status="created")
    payment = Payment(order=order, method="upi", status=payment_status, failure_reason="timeout", attempt_number=1)
    case = RecoveryCase(payment=payment, status=case_status)
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _strategy(db, case, action="send_payment_link"):
    decision = AgentDecision(
        recovery_case_id=case.id,
        agent_name="recovery_strategy_agent",
        model_used="rules",
        input_snapshot={},
        output={"action": action, "reasoning": "test"},
        confidence=0.99,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def test_policy_blocks_terminal_case(db_session):
    case = _case(db_session, case_status="resolved")
    _strategy(db_session, case)
    with pytest.raises(TerminalCaseError):
        run_policy_for_case(db_session, case)


def test_executor_blocks_paid_case_before_razorpay(db_session):
    case = _case(db_session, payment_status="paid")
    _strategy(db_session, case)

    class ExplodingRazorpay:
        def create_payment_link(self, **kwargs):
            raise AssertionError("Razorpay must not be called for a paid payment")

    with pytest.raises(CaseAlreadyPaidError):
        execute_case(db_session, case, razorpay=ExplodingRazorpay())


def test_reanalysis_route_blocks_terminal_case(client, db_session):
    case = _case(db_session, case_status="resolved")
    response = client.post(f"/cases/{case.id}/analyze?force=true")
    assert response.status_code == 409
    assert "blocked" in response.json()["detail"]


def test_revenue_at_risk_uses_one_failed_attempt_per_order(db_session):
    case = _case(db_session, amount=12500)
    order = case.payment.order
    db_session.add(Payment(order=order, method="card", status="failed", failure_reason="issuer_decline", attempt_number=2))
    db_session.commit()

    metrics = get_metrics(db_session)
    assert metrics.revenue_at_risk_paise == 12500
    assert sum(row.amount_at_risk_paise for row in metrics.by_failure_reason) == 12500
    assert metrics.by_failure_reason[0].reason == "issuer_decline"
    assert metrics.by_failure_reason[0].count == 1


def test_retry_later_schedules_before_outbound_call(db_session):
    case = _case(db_session)
    _strategy(db_session, case, action="retry_later")

    class ExplodingRazorpay:
        def create_payment_link(self, **kwargs):
            raise AssertionError("scheduled retry must not call Razorpay immediately")

    result = execute_case(db_session, case, razorpay=ExplodingRazorpay())
    assert result["action_status"] == "scheduled"
    assert result["case_status"] == "scheduled_retry"
    assert datetime.fromisoformat(result["not_before"]) > datetime.utcnow()
