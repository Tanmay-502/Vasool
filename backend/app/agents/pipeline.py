"""
Wires the Root Cause Agent and Recovery Strategy Agent together for a single
RecoveryCase, and logs one AgentDecision row per agent call (model_used,
tokens_used, latency_ms — the cost/latency numbers PROGRESS.md calls out).

INTEGRITY RULE: this module, and everything else under app/agents/, must
never import GroundTruth or query ground_truth_labels. Scoring against that
table happens later — in scripts/calibrate_confidence.py (Day 3 spot-check,
dev split only) and the Day 6 evaluation script (holdout split, final
numbers) — never inside the agents themselves.
tests/test_agents_integrity.py fails CI if this ever creeps in.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.agents.recovery_strategy_agent import run_recovery_strategy_agent
from app.agents.root_cause_agent import run_root_cause_agent
from app.models import AgentDecision, RecoveryCase


def build_case_context(db: Session, case: RecoveryCase) -> dict:
    payment = case.payment
    order = payment.order
    customer = order.customer
    hours_since_order = (datetime.utcnow() - order.created_at).total_seconds() / 3600
    return {
        "failure_reason": payment.failure_reason,
        "method": payment.method,
        "attempt_number": payment.attempt_number,
        "amount_paise": order.amount_paise,
        "hours_since_order": hours_since_order,
        "customer_opted_out": customer.opted_out,
    }


def run_pipeline_for_case(db: Session, case: RecoveryCase) -> dict:
    context = build_case_context(db, case)

    rc_result = run_root_cause_agent(context)
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="root_cause_agent",
            model_used=f"{rc_result.tier}:{rc_result.model_used}",
            input_snapshot=context,
            output=rc_result.output.model_dump(mode="json"),
            confidence=rc_result.output.confidence,
            tokens_used=rc_result.tokens_used,
            latency_ms=rc_result.latency_ms,
        )
    )

    strategy_context = {
        **context,
        "root_cause_category": rc_result.output.root_cause_category.value,
        "is_transient": rc_result.output.is_transient,
        "root_cause_confidence": rc_result.output.confidence,
    }
    strat_result = run_recovery_strategy_agent(strategy_context)
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="recovery_strategy_agent",
            model_used=f"{strat_result.tier}:{strat_result.model_used}",
            input_snapshot=strategy_context,
            output=strat_result.output.model_dump(mode="json"),
            confidence=strat_result.output.confidence,
            tokens_used=strat_result.tokens_used,
            latency_ms=strat_result.latency_ms,
        )
    )

    case.status = "analyzed"
    db.commit()

    return {
        "root_cause": rc_result.output.model_dump(mode="json"),
        "root_cause_tier": rc_result.tier,
        "strategy": strat_result.output.model_dump(mode="json"),
        "strategy_tier": strat_result.tier,
    }
