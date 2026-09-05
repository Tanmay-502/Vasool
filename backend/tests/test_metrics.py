from datetime import datetime

from app.models import Customer, GroundTruth, Merchant, Order, Outcome, Payment, RecoveryCase


def seed_minimal_dataset(db):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()

    customer = Customer(
        merchant_id=merchant.id, name="Test User", email="t@example.com", phone="9000000000"
    )
    db.add(customer)
    db.flush()

    # one successful order
    order_ok = Order(
        merchant_id=merchant.id, customer_id=customer.id, amount_paise=10000, status="paid"
    )
    db.add(order_ok)
    db.flush()
    db.add(Payment(order_id=order_ok.id, method="upi", status="success", attempt_number=1))

    # one failed order -> recovery case + ground truth, recovered later
    order_fail_recovered = Order(
        merchant_id=merchant.id, customer_id=customer.id, amount_paise=20000, status="failed"
    )
    db.add(order_fail_recovered)
    db.flush()
    payment1 = Payment(
        order_id=order_fail_recovered.id,
        method="card",
        status="failed",
        failure_reason="otp_timeout",
        attempt_number=1,
    )
    db.add(payment1)
    db.flush()
    case1 = RecoveryCase(payment_id=payment1.id, status="human_review")
    db.add(case1)
    db.flush()
    db.add(Outcome(recovery_case_id=case1.id, recovered_amount_paise=20000, success=True))
    db.add(
        GroundTruth(
            payment_id=payment1.id,
            is_recoverable=True,
            ideal_action="retry_now",
            eval_split="dev",
            rationale="test",
        )
    )

    # one failed order, still pending review, not recovered
    order_fail_pending = Order(
        merchant_id=merchant.id, customer_id=customer.id, amount_paise=30000, status="failed"
    )
    db.add(order_fail_pending)
    db.flush()
    payment2 = Payment(
        order_id=order_fail_pending.id,
        method="upi",
        status="failed",
        failure_reason="risk_flagged",
        attempt_number=1,
    )
    db.add(payment2)
    db.flush()
    db.add(RecoveryCase(payment_id=payment2.id, status="detected"))
    db.add(
        GroundTruth(
            payment_id=payment2.id,
            is_recoverable=False,
            ideal_action="escalate_human",
            eval_split="holdout",
            rationale="test",
        )
    )

    db.commit()


def test_metrics_shape_and_math(client, db_session):
    seed_minimal_dataset(db_session)

    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()

    assert data["total_orders"] == 3
    assert data["total_failed_payments"] == 2
    assert data["failure_rate_pct"] == round(2 / 3 * 100, 2)

    # revenue at risk = sum of amounts on FAILED orders = 20000 + 30000
    assert data["revenue_at_risk_paise"] == 50000
    assert data["revenue_at_risk_inr"] == 500.0

    # only payment1's outcome succeeded
    assert data["revenue_recovered_paise"] == 20000
    assert data["revenue_recovered_inr"] == 200.0
    assert data["recovery_rate_pct"] == round(20000 / 50000 * 100, 2)

    # both detected and human_review cases remain in the review queue
    assert data["cases_pending_review"] == 2

    # one of two ground truth rows is recoverable
    assert data["ground_truth_recoverable_count"] == 1
    assert data["ground_truth_recoverable_pct"] == 50.0

    reasons = {row["reason"]: row for row in data["by_failure_reason"]}
    assert reasons["otp_timeout"]["count"] == 1
    assert reasons["otp_timeout"]["amount_at_risk_paise"] == 20000
    assert reasons["risk_flagged"]["count"] == 1
    assert reasons["risk_flagged"]["amount_at_risk_paise"] == 30000

    splits = {row["eval_split"]: row["count"] for row in data["by_split"]}
    assert splits == {"dev": 1, "holdout": 1}


def test_metrics_empty_db_does_not_divide_by_zero(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_orders"] == 0
    assert data["failure_rate_pct"] == 0.0
    assert data["recovery_rate_pct"] == 0.0
    assert data["ground_truth_recoverable_pct"] == 0.0
    assert data["by_failure_reason"] == []
    assert data["by_split"] == []