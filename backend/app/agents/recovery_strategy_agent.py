"""
Recovery Strategy Agent — takes the Root Cause Agent's output plus case
context and picks one action from the canonical taxonomy (retry_now,
retry_later, send_payment_link, escalate_human, no_action).

Same fallback chain and integrity rule as root_cause_agent.py: Gemini ->
Groq -> deterministic rules, and this module must NEVER import GroundTruth
or read ground_truth_labels (enforced by tests/test_agents_integrity.py).

This agent is not itself the safety gate — Day 4's policy engine is the
authoritative, deterministic guardrail layer that runs after this and can
override its choice (e.g. block an execute, force human review). This
agent's job is to propose the best strategy it can, with an honestly
calibrated confidence.
"""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.agents import rules_fallback
from app.agents.llm_clients import AgentTierError, GeminiClient, GroqClient
from app.agents.schemas import RECOVERY_STRATEGY_JSON_SCHEMA, RecoveryStrategyOutput, groq_strict_schema

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the Recovery Strategy Agent inside Vasool, a payment-recovery "
    "pipeline. You receive a failed payment's root cause classification and "
    "must choose exactly one recovery action from the fixed taxonomy: "
    "retry_now, retry_later, send_payment_link, escalate_human, no_action. "
    "risk_flagged root causes must always be escalate_human. Never propose "
    "send_payment_link for a customer who has opted out of contact. "
    "Calibrate confidence to how certain the context genuinely makes you."
)


@dataclass
class AgentTierResult:
    output: RecoveryStrategyOutput
    tier: str  # "gemini" | "groq" | "rules_fallback"
    model_used: str
    tokens_used: int | None
    latency_ms: int


def _build_user_prompt(context: dict) -> str:
    return (
        f"root_cause_category: {context['root_cause_category']}\n"
        f"root_cause_is_transient: {context['is_transient']}\n"
        f"root_cause_confidence: {context['root_cause_confidence']:.2f}\n"
        f"payment_method: {context['method']}\n"
        f"attempt_number: {context['attempt_number']}\n"
        f"amount_paise: {context['amount_paise']}\n"
        f"customer_opted_out: {context['customer_opted_out']}\n\n"
        "Return only the decision as JSON matching the required schema."
    )


def run_recovery_strategy_agent(
    context: dict,
    gemini: GeminiClient | None = None,
    groq: GroqClient | None = None,
) -> AgentTierResult:
    gemini = gemini if gemini is not None else GeminiClient()
    groq = groq if groq is not None else GroqClient()
    user_prompt = _build_user_prompt(context)

    # Tier 1 — Gemini
    try:
        raw, tokens, latency_ms = gemini.complete_json(SYSTEM_PROMPT, user_prompt, RECOVERY_STRATEGY_JSON_SCHEMA)
        output = RecoveryStrategyOutput.model_validate(raw)
        return AgentTierResult(output, "gemini", gemini.model, tokens, latency_ms)
    except (AgentTierError, ValidationError) as exc:
        logger.warning("recovery_strategy_agent: gemini tier failed (%s), falling back to groq", exc)

    # Tier 2 — Groq
    try:
        schema = groq_strict_schema(RECOVERY_STRATEGY_JSON_SCHEMA)
        raw, tokens, latency_ms = groq.complete_json(
            SYSTEM_PROMPT, user_prompt, "recovery_strategy_output", schema
        )
        output = RecoveryStrategyOutput.model_validate(raw)
        return AgentTierResult(output, "groq", groq.model, tokens, latency_ms)
    except (AgentTierError, ValidationError) as exc:
        logger.warning("recovery_strategy_agent: groq tier failed (%s), falling back to rules", exc)

    # Tier 3 — deterministic rules, always succeeds
    output = rules_fallback.recovery_strategy_fallback(context)
    return AgentTierResult(output, "rules_fallback", "rules-v1", None, 0)