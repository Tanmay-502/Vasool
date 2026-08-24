from app.policy_engine import (
    POLICY_CHECK_NAMES,
    VERDICT_BLOCK,
    VERDICT_EXECUTE,
    VERDICT_HUMAN_REVIEW,
    evaluate_policy,
)

# A context that should cleanly pass every single check.
HAPPY_PATH = dict(
    action="retry_now",
    confidence=0.9,
    amount_paise=20000,
    attempt_number=1,
    customer_opted_out=False,
    root_cause_category="otp_timeout",
)


def test_happy_path_executes():
    decision = evaluate_policy(**HAPPY_PATH)
    assert decision.verdict == VERDICT_EXECUTE
    assert all(c.passed for c in decision.checks)


def test_every_check_is_always_evaluated_regardless_of_verdict():
    # even a case that fails on the very first check (kill switch) should
    # still have every other check recorded, not short-circuited
    decision = evaluate_policy(**{**HAPPY_PATH, "kill_switch_engaged": True})
    assert [c.check_name for c in decision.checks] == POLICY_CHECK_NAMES
    assert len(decision.checks) == len(POLICY_CHECK_NAMES)


def test_kill_switch_forces_human_review_even_on_an_otherwise_perfect_case():
    decision = evaluate_policy(**{**HAPPY_PATH, "kill_switch_engaged": True})
    assert decision.verdict == VERDICT_HUMAN_REVIEW
    kill_check = next(c for c in decision.checks if c.check_name == "kill_switch")
    assert kill_check.passed is False


def test_risk_flagged_always_human_review_regardless_of_confidence():
    decision = evaluate_policy(
        **{**HAPPY_PATH, "root_cause_category": "risk_flagged", "confidence": 0.99}
    )
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_escalate_human_action_never_executes():
    decision = evaluate_policy(**{**HAPPY_PATH, "action": "escalate_human"})
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_no_action_never_executes():
    decision = evaluate_policy(**{**HAPPY_PATH, "action": "no_action"})
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_opted_out_customer_blocks_send_payment_link():
    decision = evaluate_policy(
        **{**HAPPY_PATH, "action": "send_payment_link", "customer_opted_out": True}
    )
    assert decision.verdict == VERDICT_BLOCK
    opt_out_check = next(c for c in decision.checks if c.check_name == "opt_out")
    assert opt_out_check.passed is False


def test_opted_out_customer_does_not_block_retry_now():
    # opt-out only matters for actions that contact the customer; retry_now
    # doesn't, so an opted-out customer shouldn't block it
    decision = evaluate_policy(
        **{**HAPPY_PATH, "action": "retry_now", "customer_opted_out": True}
    )
    assert decision.verdict == VERDICT_EXECUTE
    opt_out_check = next(c for c in decision.checks if c.check_name == "opt_out")
    assert opt_out_check.passed is True


def test_confidence_below_floor_sends_to_human_review():
    decision = evaluate_policy(**{**HAPPY_PATH, "confidence": 0.5})
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_confidence_exactly_at_floor_executes():
    decision = evaluate_policy(**{**HAPPY_PATH, "confidence": 0.75})
    assert decision.verdict == VERDICT_EXECUTE


def test_amount_above_ceiling_sends_to_human_review():
    decision = evaluate_policy(**{**HAPPY_PATH, "amount_paise": 600_000})
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_amount_exactly_at_ceiling_executes():
    decision = evaluate_policy(**{**HAPPY_PATH, "amount_paise": 500_000})
    assert decision.verdict == VERDICT_EXECUTE


def test_attempt_above_max_sends_to_human_review():
    decision = evaluate_policy(**{**HAPPY_PATH, "attempt_number": 4})
    assert decision.verdict == VERDICT_HUMAN_REVIEW


def test_attempt_exactly_at_max_executes():
    decision = evaluate_policy(**{**HAPPY_PATH, "attempt_number": 3})
    assert decision.verdict == VERDICT_EXECUTE


def test_every_check_result_has_a_non_empty_reason():
    decision = evaluate_policy(**HAPPY_PATH)
    for check in decision.checks:
        assert check.reason
        assert isinstance(check.reason, str)