from app.agents import llm_clients
from app.agents.pipeline import build_case_context, run_pipeline_for_case
from app.models import AgentDecision, Customer, Merchant, Order, Payment, RecoveryCase


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
        failure_reason="otp_timeout",
        attempt_number=1,
    )
    db.add(payment)
    db.flush()

    case = RecoveryCase(payment_id=payment.id, status="detected")
    db.add(case)
    db.commit()
    return case


def test_build_case_context_shape(db_session):
    case = _seed_one_failed_case(db_session)
    context = build_case_context(db_session, case)

    assert context["failure_reason"] == "otp_timeout"
    assert context["method"] == "upi"
    assert context["attempt_number"] == 1
    assert context["amount_paise"] == 20000
    assert context["customer_opted_out"] is False
    assert context["hours_since_order"] >= 0


def test_pipeline_writes_one_agent_decision_per_agent_and_marks_case_analyzed(db_session, monkeypatch):
    # Force both LLM tiers off regardless of whatever's in the developer's
    # local .env, so this test is deterministic and makes zero network calls.
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    case = _seed_one_failed_case(db_session)

    result = run_pipeline_for_case(db_session, case)

    assert result["root_cause_tier"] == "rules_fallback"
    assert result["strategy_tier"] == "rules_fallback"
    assert result["root_cause"]["root_cause_category"] == "otp_timeout"
    assert result["strategy"]["action"] == "retry_now"  # transient -> retry_now on the rules tier

    decisions = (
        db_session.query(AgentDecision).filter(AgentDecision.recovery_case_id == case.id).all()
    )
    assert len(decisions) == 2
    assert {d.agent_name for d in decisions} == {"root_cause_agent", "recovery_strategy_agent"}
    for decision in decisions:
        assert decision.model_used.startswith("rules_fallback:")
        assert decision.tokens_used is None
        assert decision.latency_ms == 0
        assert 0.0 <= decision.confidence <= 1.0

    assert db_session.get(RecoveryCase, case.id).status == "analyzed"