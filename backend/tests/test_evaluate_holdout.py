from app.agents import llm_clients
from app.agents.llm_clients import GeminiClient, GroqClient
from app.models import Customer, GroundTruth, Merchant, Order, Payment, RecoveryCase
from app.policy_engine import VERDICT_BLOCK, VERDICT_EXECUTE, VERDICT_HUMAN_REVIEW
from scripts.evaluate_holdout import ScoredCase, _score_case, summarize


def _seed_case(
    db,
    *,
    failure_reason,
    attempt_number=1,
    amount_paise=20000,
    opted_out=False,
    is_recoverable,
    ideal_action,
    eval_split="holdout",
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
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=amount_paise, status="failed")
    db.add(order)
    db.flush()
    payment = Payment(
        order_id=order.id,
        method="upi",
        status="failed",
        failure_reason=failure_reason,
        attempt_number=attempt_number,
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db.add(case)
    db.flush()
    db.add(
        GroundTruth(
            payment_id=payment.id,
            is_recoverable=is_recoverable,
            ideal_action=ideal_action,
            eval_split=eval_split,
            rationale="test",
        )
    )
    db.commit()
    return case


# ---- summarize() — pure aggregation math, no DB / no LLM chain ----------


def test_summarize_computes_precision_recall():
    scored = [
        ScoredCase(1, 10000, True, True, VERDICT_EXECUTE, "rules_fallback", "rules_fallback", None),   # TP
        ScoredCase(2, 10000, True, False, VERDICT_EXECUTE, "rules_fallback", "rules_fallback", None),  # FP
        ScoredCase(3, 10000, False, True, VERDICT_HUMAN_REVIEW, "rules_fallback", "rules_fallback", True),  # FN
        ScoredCase(4, 10000, False, False, VERDICT_HUMAN_REVIEW, "rules_fallback", "rules_fallback", True), # TN
    ]
    summary = summarize(scored)
    assert summary["tp"] == 1
    assert summary["fp"] == 1
    assert summary["fn"] == 1
    assert summary["tn"] == 1
    assert summary["precision"] == 0.5  # 1 / (1+1)
    assert summary["recall"] == 0.5  # 1 / (1+1)


def test_summarize_false_positive_cost_only_counts_executed_non_recoverable():
    scored = [
        ScoredCase(1, 50000, True, False, VERDICT_EXECUTE, "t", "t", None),      # counts: executed, not recoverable
        ScoredCase(2, 30000, True, False, VERDICT_HUMAN_REVIEW, "t", "t", True), # doesn't count: never executed
        ScoredCase(3, 20000, True, True, VERDICT_EXECUTE, "t", "t", None),       # doesn't count: was recoverable
    ]
    summary = summarize(scored)
    assert summary["false_positive_cost_paise"] == 50000


def test_summarize_would_recover_only_counts_executed_and_actually_recoverable():
    scored = [
        ScoredCase(1, 40000, True, True, VERDICT_EXECUTE, "t", "t", None),
        ScoredCase(2, 15000, True, False, VERDICT_EXECUTE, "t", "t", None),
        ScoredCase(3, 99999, True, True, VERDICT_HUMAN_REVIEW, "t", "t", True),
    ]
    summary = summarize(scored)
    assert summary["would_recover_paise"] == 40000


def test_summarize_escalation_pct_only_over_escalated_cases():
    scored = [
        ScoredCase(1, 1000, True, True, VERDICT_EXECUTE, "t", "t", None),  # excluded — never escalated
        ScoredCase(2, 1000, False, False, VERDICT_HUMAN_REVIEW, "t", "t", True),  # correct
        ScoredCase(3, 1000, False, True, VERDICT_HUMAN_REVIEW, "t", "t", False),  # incorrect
        ScoredCase(4, 1000, True, False, VERDICT_BLOCK, "t", "t", True),  # correct
    ]
    summary = summarize(scored)
    assert summary["escalated_total"] == 3
    assert summary["correctly_escalated_count"] == 2
    assert round(summary["escalation_pct"], 1) == round(2 / 3 * 100, 1)


def test_summarize_handles_empty_list_without_dividing_by_zero():
    summary = summarize([])
    assert summary["precision"] == 0.0
    assert summary["recall"] == 0.0
    assert summary["escalation_pct"] == 0.0
    assert summary["n"] == 0


# ---- _score_case() — real pipeline + policy engine, rules_fallback tier -


def test_score_case_risk_flagged_is_correctly_predicted_and_escalated(db_session, monkeypatch):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    case = _seed_case(
        db_session,
        failure_reason="risk_flagged",
        is_recoverable=False,
        ideal_action="escalate_human",
    )

    scored = _score_case(db_session, case, GeminiClient(api_key=''), GroqClient(api_key=''))

    assert scored.verdict == VERDICT_HUMAN_REVIEW
    assert scored.predicted_recoverable is False  # rules fallback always escalates risk_flagged
    assert scored.actual_recoverable is False
    assert scored.correctly_escalated is True


def test_score_case_transient_first_attempt_below_confidence_floor_goes_to_review(db_session, monkeypatch):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    case = _seed_case(
        db_session,
        failure_reason="otp_timeout",
        attempt_number=1,
        is_recoverable=True,
        ideal_action="retry_now",
    )

    scored = _score_case(db_session, case, GeminiClient(api_key=''), GroqClient(api_key=''))

    # rules_fallback: otp_timeout is_transient -> retry_now, confidence 0.65
    # policy: confidence 0.65 < MIN_CONFIDENCE_TO_AUTO_EXECUTE (0.75) -> HUMAN_REVIEW, not EXECUTE
    assert scored.predicted_recoverable is True
    assert scored.actual_recoverable is True
    assert scored.verdict == VERDICT_HUMAN_REVIEW
    assert scored.correctly_escalated is False  # ground truth says recoverable, so this escalation was a miss


def test_score_case_opted_out_customer_blocks_payment_link(db_session, monkeypatch):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    case = _seed_case(
        db_session,
        failure_reason="card_declined",
        opted_out=True,
        is_recoverable=True,
        ideal_action="send_payment_link",
    )

    scored = _score_case(db_session, case, GeminiClient(api_key=''), GroqClient(api_key=''))

    # opted_out -> rules_fallback picks escalate_human instead of send_payment_link,
    # so nothing to BLOCK; this proves the guardrail changes the *predicted* action too
    assert scored.predicted_recoverable is False
    assert scored.verdict == VERDICT_HUMAN_REVIEW


def test_evaluate_holdout_query_excludes_dev_split(db_session, monkeypatch):
    """Guards the actual query in scripts.evaluate_holdout.main() — the one
    thing this script must never get wrong, mirroring calibrate_confidence's
    dev-only filter but inverted."""
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")

    _seed_case(
        db_session, failure_reason="otp_timeout", is_recoverable=True,
        ideal_action="retry_now", eval_split="dev",
    )
    holdout_case = _seed_case(
        db_session, failure_reason="otp_timeout", is_recoverable=True,
        ideal_action="retry_now", eval_split="holdout",
    )

    rows = (
        db_session.query(RecoveryCase)
        .join(Payment, Payment.id == RecoveryCase.payment_id)
        .join(GroundTruth, GroundTruth.payment_id == Payment.id)
        .filter(GroundTruth.eval_split == "holdout")
        .all()
    )
    assert [r.id for r in rows] == [holdout_case.id]