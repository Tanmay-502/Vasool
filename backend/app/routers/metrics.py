"""Fast, read-only revenue and recovery metrics for the command center."""
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
    total_failed_payments = db.query(func.count(Payment.id)).filter(Payment.status == "failed").scalar() or 0
    failure_rate_pct = round(total_failed_payments / total_orders * 100, 2) if total_orders else 0.0

    revenue_at_risk_paise = (
        db.query(func.coalesce(func.sum(Order.amount_paise), 0))
        .join(Payment, Payment.order_id == Order.id)
        .filter(Payment.status == "failed")
        .scalar()
        or 0
    )

    # Outcome is populated only from trusted Razorpay webhook events. Include
    # partial recovery amounts as real recovered revenue as well.
    revenue_recovered_paise = db.query(func.coalesce(func.sum(Outcome.recovered_amount_paise), 0)).scalar() or 0
    recovery_rate_pct = round(revenue_recovered_paise / revenue_at_risk_paise * 100, 2) if revenue_at_risk_paise else 0.0

    cases_pending_review = (
        db.query(func.count(RecoveryCase.id))
        .filter(RecoveryCase.status.in_(("detected", "human_review", "blocked")))
        .scalar()
        or 0
    )
    resolved_cases = db.query(func.count(RecoveryCase.id)).filter(RecoveryCase.status == "resolved").scalar() or 0
    partially_recovered_cases = db.query(func.count(RecoveryCase.id)).filter(RecoveryCase.status == "partially_recovered").scalar() or 0
    executed_cases = db.query(func.count(RecoveryCase.id)).filter(RecoveryCase.status == "executed").scalar() or 0

    recoverable_count = db.query(func.count(GroundTruth.id)).filter(GroundTruth.is_recoverable.is_(True)).scalar() or 0
    recoverable_pct = round(recoverable_count / total_failed_payments * 100, 2) if total_failed_payments else 0.0

    by_reason_rows = (
        db.query(Payment.failure_reason, func.count(Payment.id), func.coalesce(func.sum(Order.amount_paise), 0))
        .join(Order, Order.id == Payment.order_id)
        .filter(Payment.status == "failed")
        .group_by(Payment.failure_reason)
        .order_by(func.count(Payment.id).desc())
        .all()
    )
    by_failure_reason = [
        FailureReasonBreakdown(reason=reason or "unknown", count=count, amount_at_risk_paise=int(amount))
        for reason, count, amount in by_reason_rows
    ]

    by_split_rows = db.query(GroundTruth.eval_split, func.count(GroundTruth.id)).group_by(GroundTruth.eval_split).all()
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
        resolved_cases=resolved_cases,
        partially_recovered_cases=partially_recovered_cases,
        executed_cases=executed_cases,
        ground_truth_recoverable_count=recoverable_count,
        ground_truth_recoverable_pct=recoverable_pct,
        by_failure_reason=by_failure_reason,
        by_split=by_split,
    )
