import pytest

from app.config import settings
from app.models import AgentDecision, Customer, Merchant, Order, Payment, PolicyCheck, RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, run_policy_for_case


def _seed_case_with_decisions(
    db,
    *,
    action="retry_now",
    confidence=0.9,
    root_cause_category="otp_timeout",
    amount_paise=20000,
    attempt_number=1,
    opted_out=False,
    include_root_cause_decision=True,
):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()
    customer = Customer(
        merchant_id=merchant.id,
        name="Test User",
        email="t@example.com",
        phone="9000000000",
        opted_out=opted_out,
    )
    db.add(customer)
    db.flush()
    order = Order(
        merchant_id=merchant.id, customer_id=customer.id, amount_paise=amount_paise, status="failed"
    )
    db.add(order)
    db.flush()
    payment = Payment(
        order_id=order.id,
        method="upi",
        status="failed",
        failure_reason=root_cause_category,
        attempt_number=attempt_number,
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="analyzed")
    db.add(case)
    db.flush()

    if include_root_cause_decision:
        db.add(
            AgentDecision(
                recovery_case_id=case.id,
                agent_name="root_cause_agent",
                model_used="rules_fallback:rules-v1",
                input_snapshot={},
                output={
                    "root_cause_category": root_cause_category,
                    "is_transient": True,
                    "confidence": 0.8,
                    "reasoning": "test",
                },
                confidence=0.8,
            )
        )
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="recovery_strategy_agent",
            model_used="rules_fallback:rules-v1",
            input_snapshot={},
            output={"action": action, "confidence": confidence, "reasoning": "test"},
            confidence=confidence,
        )
    )
    db.commit()
    return case


def _seed_case_without_decisions(db):
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
    payment = Payment(order_id=order.id, method="upi", status="failed", failure_reason="otp_timeout", attempt_number=1)
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db.add(case)
    db.commit()
    return case


def test_raises_if_case_never_analyzed(db_session):
    case = _seed_case_without_decisions(db_session)
    with pytest.raises(CaseNotAnalyzedError):
        run_policy_for_case(db_session, case)


def test_high_confidence_transient_case_executes(db_session):
    case = _seed_case_with_decisions(db_session, action="retry_now", confidence=0.9)

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] == "EXECUTE"
    assert result["status"] == "pending_execution"
    assert db_session.get(RecoveryCase, case.id).status == "pending_execution"


def test_risk_flagged_goes_to_human_review_even_with_high_confidence(db_session):
    case = _seed_case_with_decisions(
        db_session, action="escalate_human", confidence=0.99, root_cause_category="risk_flagged"
    )

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] == "HUMAN_REVIEW"
    assert result["status"] == "human_review"


def test_opted_out_customer_send_payment_link_is_blocked(db_session):
    case = _seed_case_with_decisions(
        db_session,
        action="send_payment_link",
        confidence=0.9,
        root_cause_category="card_declined",
        opted_out=True,
    )

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] == "BLOCK"
    assert result["status"] == "blocked"


def test_low_confidence_sends_to_human_review(db_session):
    case = _seed_case_with_decisions(db_session, action="retry_now", confidence=0.5)

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] == "HUMAN_REVIEW"


def test_policy_check_rows_are_persisted_with_all_seven_checks(db_session):
    case = _seed_case_with_decisions(db_session)

    run_policy_for_case(db_session, case)

    checks = db_session.query(PolicyCheck).filter(PolicyCheck.recovery_case_id == case.id).all()
    assert len(checks) == 7
    assert {c.check_name for c in checks} == {
        "kill_switch",
        "risk_flagged_escalation",
        "action_type",
        "opt_out",
        "confidence_floor",
        "amount_ceiling",
        "retry_ceiling",
    }


def test_missing_root_cause_decision_defaults_to_unknown_not_a_crash(db_session):
    case = _seed_case_with_decisions(db_session, include_root_cause_decision=False)

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] in {"EXECUTE", "HUMAN_REVIEW", "BLOCK"}


def test_kill_switch_forces_human_review(db_session, monkeypatch):
    monkeypatch.setattr(settings, "KILL_SWITCH_ENGAGED", True)
    case = _seed_case_with_decisions(db_session, action="retry_now", confidence=0.95)

    result = run_policy_for_case(db_session, case)

    assert result["verdict"] == "HUMAN_REVIEW"