from datetime import datetime

from pydantic import BaseModel


class FailureReasonBreakdown(BaseModel):
    reason: str
    count: int
    amount_at_risk_paise: int


class SplitBreakdown(BaseModel):
    eval_split: str
    count: int


class MetricsResponse(BaseModel):
    total_orders: int
    total_failed_payments: int
    failure_rate_pct: float
    revenue_at_risk_paise: int
    revenue_at_risk_inr: float
    revenue_recovered_paise: int
    revenue_recovered_inr: float
    recovery_rate_pct: float
    cases_pending_review: int
    resolved_cases: int
    partially_recovered_cases: int
    executed_cases: int
    ground_truth_recoverable_count: int
    ground_truth_recoverable_pct: float
    by_failure_reason: list[FailureReasonBreakdown]
    by_split: list[SplitBreakdown]


class AuditLedgerEntry(BaseModel):
    id: int
    case_id: int
    event_type: str
    detail: str
    created_at: datetime


class AuditLedgerResponse(BaseModel):
    entries: list[AuditLedgerEntry]
