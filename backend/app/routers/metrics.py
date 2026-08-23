"""
Revenue-intelligence metrics — descriptive stats over whatever's currently in
the database. Deliberately zero LLM calls (see PROGRESS.md Day 2): this is
the numbers dashboard, not a decision-maker. Precision/recall against agent
output comes later (Day 6) once agents exist to score.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import GroundTruth, Order, Outcome, Payment, RecoveryCase
from app.schemas import FailureReasonBreakdown, MetricsResponse, SplitBreakdown

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)):
    total_orders = db.query(func.count(Order.id)).scalar() or 0

    total_failed_payments = (
        db.query(func.count(Payment.id)).filter(Payment.status == "failed").scalar() or 0
    )
    failure_rate_pct = (
        round(total_failed_payments / total_orders * 100, 2) if total_orders else 0.0
    )

    revenue_at_risk_paise = (
        db.query(func.coalesce(func.sum(Order.amount_paise), 0))
        .join(Payment, Payment.order_id == Order.id)
        .filter(Payment.status == "failed")
        .scalar()
        or 0
    )

    revenue_recovered_paise = (
        db.query(func.coalesce(func.sum(Outcome.recovered_amount_paise), 0))
        .filter(Outcome.success.is_(True))
        .scalar()
        or 0
    )
    recovery_rate_pct = (
        round(revenue_recovered_paise / revenue_at_risk_paise * 100, 2)
        if revenue_at_risk_paise
        else 0.0
    )

    cases_pending_review = (
        db.query(func.count(RecoveryCase.id)).filter(RecoveryCase.status == "detected").scalar()
        or 0
    )

    recoverable_count = (
        db.query(func.count(GroundTruth.id)).filter(GroundTruth.is_recoverable.is_(True)).scalar()
        or 0
    )
    recoverable_pct = (
        round(recoverable_count / total_failed_payments * 100, 2)
        if total_failed_payments
        else 0.0
    )

    by_reason_rows = (
        db.query(
            Payment.failure_reason,
            func.count(Payment.id),
            func.coalesce(func.sum(Order.amount_paise), 0),
        )
        .join(Order, Order.id == Payment.order_id)
        .filter(Payment.status == "failed")
        .group_by(Payment.failure_reason)
        .order_by(func.count(Payment.id).desc())
        .all()
    )
    by_failure_reason = [
        FailureReasonBreakdown(
            reason=reason or "unknown", count=count, amount_at_risk_paise=int(amount)
        )
        for reason, count, amount in by_reason_rows
    ]

    by_split_rows = (
        db.query(GroundTruth.eval_split, func.count(GroundTruth.id))
        .group_by(GroundTruth.eval_split)
        .all()
    )
    by_split = [SplitBreakdown(eval_split=split, count=count) for split, count in by_split_rows]

    return MetricsResponse(
        total_orders=total_orders,
        total_failed_payments=total_failed_payments,
        failure_rate_pct=failure_rate_pct,
        revenue_at_risk_paise=int(revenue_at_risk_paise),
        revenue_at_risk_inr=round(revenue_at_risk_paise / 100, 2),
        revenue_recovered_paise=int(revenue_recovered_paise),
        revenue_recovered_inr=round(revenue_recovered_paise / 100, 2),
        recovery_rate_pct=recovery_rate_pct,
        cases_pending_review=cases_pending_review,
        ground_truth_recoverable_count=recoverable_count,
        ground_truth_recoverable_pct=recoverable_pct,
        by_failure_reason=by_failure_reason,
        by_split=by_split,
    )