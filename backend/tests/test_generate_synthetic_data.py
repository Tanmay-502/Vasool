import random

from scripts.generate_synthetic_data import (
    FAILURE_PROFILES,
    compute_ground_truth,
    generate,
)
from app.models import Customer, GroundTruth, Merchant, Order, Payment, RecoveryCase


def test_compute_ground_truth_is_deterministic_for_a_given_seed():
    rng1 = random.Random(123)
    rng2 = random.Random(123)
    result1 = compute_ground_truth(rng1, "otp_timeout", attempt_number=1, amount_paise=50000)
    result2 = compute_ground_truth(rng2, "otp_timeout", attempt_number=1, amount_paise=50000)
    assert result1 == result2


def test_risk_flagged_always_escalates_to_human():
    rng = random.Random(0)
    for _ in range(200):
        is_recoverable, ideal_action, _ = compute_ground_truth(
            rng, "risk_flagged", attempt_number=1, amount_paise=100000
        )
        assert ideal_action == "escalate_human"


def test_more_attempts_reduces_recovery_probability():
    # same seed sequence, only attempt_number differs -> fewer recoveries at higher attempts
    def recoverable_rate(attempt_number, n=500):
        rng = random.Random(7)
        hits = sum(
            compute_ground_truth(rng, "insufficient_funds", attempt_number, 50000)[0]
            for _ in range(n)
        )
        return hits / n

    assert recoverable_rate(1) > recoverable_rate(3)


def test_unrecoverable_non_risk_cases_get_no_action():
    rng = random.Random(0)
    for _ in range(500):
        is_recoverable, ideal_action, _ = compute_ground_truth(
            rng, "card_declined", attempt_number=1, amount_paise=50000
        )
        if not is_recoverable:
            assert ideal_action == "no_action"


def test_all_failure_reasons_have_valid_action_taxonomy():
    valid_actions = {"retry_now", "retry_later", "send_payment_link", "escalate_human"}
    for profile in FAILURE_PROFILES.values():
        assert profile["action"] in valid_actions


def test_generate_produces_expected_volume_and_split(db_session, monkeypatch):
    import scripts.generate_synthetic_data as gen_module

    monkeypatch.setattr(gen_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(gen_module.Base.metadata, "create_all", lambda bind=None: None)
    # prevent the real close() from tearing down the shared test session
    monkeypatch.setattr(db_session, "close", lambda: None)

    generate(count=200, seed=42, reset=False)

    assert db_session.query(Merchant).count() == len(gen_module.MERCHANTS)
    assert db_session.query(Order).count() == 200

    failed_count = db_session.query(Payment).filter(Payment.status == "failed").count()
    case_count = db_session.query(RecoveryCase).count()
    gt_count = db_session.query(GroundTruth).count()
    assert failed_count == case_count == gt_count
    assert 0 < failed_count < 200  # some failures, not all/none

    dev_count = db_session.query(GroundTruth).filter(GroundTruth.eval_split == "dev").count()
    holdout_count = db_session.query(GroundTruth).filter(
        GroundTruth.eval_split == "holdout"
    ).count()
    assert dev_count + holdout_count == gt_count
    # roughly 80/20, allow rounding slack on small samples
    assert abs(dev_count / gt_count - 0.8) < 0.05