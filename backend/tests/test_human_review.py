from app.config import settings
from app.models import AgentDecision, AuditLog, Customer, Merchant, Order, Payment, PolicyCheck, RecoveryCase


def _seed_review_case(db, *, action="retry_now", opt_out=False):
    merchant = Merchant(name="Review Merchant")
    customer = Customer(merchant=merchant, name="Review User", email="review@example.com", phone="9000000000", opted_out=opt_out)
    order = Order(merchant=merchant, customer=customer, amount_paise=15000, currency="INR", status="failed")
    payment = Payment(order=order, method="upi", status="failed", failure_reason="card_declined", attempt_number=2)
    case = RecoveryCase(payment=payment, status="human_review")
    db.add_all([merchant, customer, order, payment, case])
    db.flush()
    db.add(AgentDecision(
        recovery_case_id=case.id,
        agent_name="recovery_strategy_agent",
        model_used="rules_fallback:rules-v1",
        input_snapshot={},
        output={"action": action, "confidence": 0.60, "reasoning": "uncertain"},
        confidence=0.60,
    ))
    db.add_all([
        PolicyCheck(recovery_case_id=case.id, check_name="action_type", passed=action in {"retry_now", "retry_later", "send_payment_link"}, reason="test"),
        PolicyCheck(recovery_case_id=case.id, check_name="opt_out", passed=not opt_out or action != "send_payment_link", reason="test"),
        PolicyCheck(recovery_case_id=case.id, check_name="confidence_floor", passed=False, reason="below threshold"),
    ])
    db.commit()
    return case


def test_review_approval_allows_only_executable_strategy(client, db_session):
    case = _seed_review_case(db_session, action="retry_later")
    response = client.post(f"/cases/{case.id}/review", json={"decision": "approve", "note": "operator approved"})
    assert response.status_code == 200
    assert response.json()["status"] == "pending_execution"
    db_session.refresh(case)
    assert case.status == "pending_execution"
    assert db_session.query(AuditLog).filter(AuditLog.recovery_case_id == case.id, AuditLog.event_type == "human_review_decision").count() == 1


def test_review_approval_rejects_non_executable_strategy(client, db_session):
    case = _seed_review_case(db_session, action="no_action")
    response = client.post(f"/cases/{case.id}/review", json={"decision": "approve"})
    assert response.status_code == 409
    db_session.refresh(case)
    assert case.status == "human_review"


def test_review_approval_rejects_hard_opt_out_gate(client, db_session):
    case = _seed_review_case(db_session, action="send_payment_link", opt_out=True)
    response = client.post(f"/cases/{case.id}/review", json={"decision": "approve"})
    assert response.status_code == 409
    db_session.refresh(case)
    assert case.status == "human_review"


def test_review_rejection_is_terminal(client, db_session):
    case = _seed_review_case(db_session)
    response = client.post(f"/cases/{case.id}/review", json={"decision": "reject", "note": "not worth attempting"})
    assert response.status_code == 200
    db_session.refresh(case)
    assert case.status == "rejected"


def test_review_approval_paused_by_kill_switch(client, db_session, monkeypatch):
    case = _seed_review_case(db_session)
    monkeypatch.setattr(settings, "KILL_SWITCH_ENGAGED", True)
    response = client.post(f"/cases/{case.id}/review", json={"decision": "approve"})
    assert response.status_code == 409
    db_session.refresh(case)
    assert case.status == "human_review"
