"""
Day 4 — wires the pure policy engine (app/policy_engine.py) to a real
RecoveryCase: reads the agents' latest decisions, evaluates policy, and
persists the result (one PolicyCheck row per check + case.status). This is
the "DB-writing wrapper" app/policy_engine.py's own docstring says lives in
a separate module — kept apart so the decision logic itself stays pure and
trivially unit-testable in isolation.

Only reads AgentDecision (the agents' own output, already written by
app/agents/pipeline.py) — never ground_truth_labels. This module lives
outside app/agents/ on purpose, so it isn't bound by that package's
integrity-rule CI check (tests/test_agents_integrity.py) — a real
distinction, since this file's whole job is a different one: it's the
deterministic check *on top of* the agents, not one of the probabilistic
agents itself.
"""
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AgentDecision, PolicyCheck, RecoveryCase
from app.policy_engine import VERDICT_BLOCK, VERDICT_EXECUTE, VERDICT_HUMAN_REVIEW, evaluate_policy


class CaseNotAnalyzedError(Exception):
    """Raised when policy evaluation is attempted on a case with no
    recovery_strategy_agent decision yet — analyze it first."""


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
    strategy_decision = _latest_decision(db, case.id, "recovery_strategy_agent")
    if strategy_decision is None:
        raise CaseNotAnalyzedError(
            f"Case {case.id} has no recovery_strategy_agent decision yet — "
            f"run POST /cases/{case.id}/analyze first."
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
        root_cause_category=(
            root_cause_decision.output["root_cause_category"] if root_cause_decision else "unknown"
        ),
        kill_switch_engaged=settings.KILL_SWITCH_ENGAGED,
    )

    for check in decision.checks:
        db.add(
            PolicyCheck(
                recovery_case_id=case.id,
                check_name=check.check_name,
                passed=check.passed,
                reason=check.reason,
            )
        )

    case.status = _VERDICT_TO_STATUS[decision.verdict]
    db.commit()

    return {
        "verdict": decision.verdict,
        "status": case.status,
        "checks": [
            {"check_name": c.check_name, "passed": c.passed, "reason": c.reason}
            for c in decision.checks
        ],
    }