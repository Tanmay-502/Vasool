from pydantic import BaseModel


class FailureReasonBreakdown(BaseModel):
    reason: str
    count: int
    amount_at_risk_paise: int


class SplitBreakdown(BaseModel):
    eval_split: str
    count: int


class MetricsResponse(BaseModel):
    # Dataset shape
    total_orders: int
    total_failed_payments: int
    failure_rate_pct: float

    # Money — the numbers the whole project is judged on
    revenue_at_risk_paise: int
    revenue_at_risk_inr: float
    revenue_recovered_paise: int
    revenue_recovered_inr: float
    recovery_rate_pct: float

    # Pipeline state
    cases_pending_review: int

    # Ground truth (dataset health, not agent performance — that's Day 6)
    ground_truth_recoverable_count: int
    ground_truth_recoverable_pct: float

    by_failure_reason: list[FailureReasonBreakdown]
    by_split: list[SplitBreakdown]