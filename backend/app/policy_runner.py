"""Database-writing wrapper around the pure policy engine."""
from sqlalchemy.orm import Session

from app.models import AgentDecision, PolicyCheck, RecoveryCase
from app.policy_engine import VERDICT_BLOCK, VERDICT_EXECUTE, VERDICT_HUMAN_REVIEW, evaluate_policy
from app.state import get_kill_switch
from app.status import TERMINAL_STATUSES


class CaseNotAnalyzedError(Exception):
    """Raised when policy evaluation has no recovery strategy decision."""


class TerminalCaseError(Exception):
    """Raised when a terminal or already-paid case is evaluated again."""


_VERDICT_TO_STATUS = {
    VERDICT_EXECUTE: "pending_execution",
    VERDICT_HUMAN_REVIEW: "human_review",
    VERDICT_BLOCK: "blocked",
}


def _latest_decision(db: Session, case_id: int, agent_name: str) -> AgentDecision | None:
    return (
        db.query(AgentDecision)
        .filter(AgentDecision.recovery_case_id == case_id, AgentDecision.agent_name == agent_name)
        .order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc())
        .first()
    )


def run_policy_for_case(db: Session, case: RecoveryCase) -> dict:
    if case.payment.status == "paid" or case.status in TERMINAL_STATUSES:
        raise TerminalCaseError(
            f"Case {case.id} is terminal or already paid; policy evaluation is blocked."
        )

    strategy_decision = _latest_decision(db, case.id, "recovery_strategy_agent")
    if strategy_decision is None:
        raise CaseNotAnalyzedError(
            f"Case {case.id} has no recovery_strategy_agent decision yet — run analysis first."
        )
    root_cause_decision = _latest_decision(db, case.id, "root_cause_agent")
    payment = case.payment
    order = payment.order
    customer = order.customer

    decision = evaluate_policy(
        action=strategy_decision.output["action"],
        confidence=strategy_decision.confidence,
        amount_paise=order.amount_paise,
        attempt_number=payment.attempt_number,
        customer_opted_out=customer.opted_out,
        root_cause_category=(root_cause_decision.output["root_cause_category"] if root_cause_decision else "unknown"),
        kill_switch_engaged=get_kill_switch(db),
    )

    for check in decision.checks:
        db.add(PolicyCheck(recovery_case_id=case.id, check_name=check.check_name, passed=check.passed, reason=check.reason))

    case.status = _VERDICT_TO_STATUS[decision.verdict]
    db.commit()
    return {
        "verdict": decision.verdict,
        "status": case.status,
        "checks": [{"check_name": c.check_name, "passed": c.passed, "reason": c.reason} for c in decision.checks],
    }
