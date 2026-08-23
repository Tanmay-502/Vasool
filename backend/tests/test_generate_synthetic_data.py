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


def test_golden_snapshot_seed_42_count_1500(db_session, monkeypatch):
    """
    Locks in the exact aggregate stats of the frozen dataset (seed=42,
    count=1500) that Day 3+ agents get built and evaluated against.

    If this test ever fails, it means something changed how the RNG stream
    gets consumed (a reordered rng call, a new randomized field, a changed
    weight/probability) and seed=42 now silently produces a *different*
    dataset than the one every prior eval number was collected against.

    Do NOT "fix" this test by just updating the numbers unless you've
    deliberately decided to re-freeze the dataset — see the module
    docstring's "IMPORTANT" and "DAY 2.5 HARDENING" notes on why that
    invalidates prior metrics.
    """
    import scripts.generate_synthetic_data as gen_module
    from sqlalchemy import func

    monkeypatch.setattr(gen_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(gen_module.Base.metadata, "create_all", lambda bind=None: None)
    monkeypatch.setattr(db_session, "close", lambda: None)

    generate(count=1500, seed=42, reset=False)

    assert db_session.query(Merchant).count() == 5
    assert db_session.query(Customer).count() == 500
    assert db_session.query(Order).count() == 1500

    opted_out_count = (
        db_session.query(Customer).filter(Customer.opted_out.is_(True)).count()
    )
    assert opted_out_count == 32

    failed_count = db_session.query(Payment).filter(Payment.status == "failed").count()
    assert failed_count == 506
    assert db_session.query(RecoveryCase).count() == failed_count

    gt_count = db_session.query(GroundTruth).count()
    assert gt_count == failed_count

    recoverable_count = (
        db_session.query(GroundTruth).filter(GroundTruth.is_recoverable.is_(True)).count()
    )
    assert recoverable_count == 258

    dev_count = db_session.query(GroundTruth).filter(GroundTruth.eval_split == "dev").count()
    holdout_count = db_session.query(GroundTruth).filter(
        GroundTruth.eval_split == "holdout"
    ).count()
    assert (dev_count, holdout_count) == (404, 102)

    attempt_dist = dict(
        db_session.query(Payment.attempt_number, func.count(Payment.id))
        .filter(Payment.status == "failed")
        .group_by(Payment.attempt_number)
        .all()
    )
    assert attempt_dist == {1: 296, 2: 136, 3: 74}