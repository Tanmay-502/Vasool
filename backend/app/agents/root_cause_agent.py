"""
Root Cause Agent — classifies why a payment failed and whether it looks
transient (a bare retry would plausibly work) or persistent.

Fallback chain: Gemini -> Groq -> deterministic rules. Every tier is tried
in order; the first one to return a schema-valid RootCauseOutput wins. This
module must NEVER import GroundTruth or read ground_truth_labels — see
models.py's GroundTruth docstring and tests/test_agents_integrity.py, which
fails CI if that ever happens.
"""
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.agents import rules_fallback
from app.agents.llm_clients import AgentTierError, GeminiClient, GroqClient
from app.agents.schemas import ROOT_CAUSE_JSON_SCHEMA, RootCauseOutput, groq_strict_schema

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the Root Cause Agent inside Vasool, a payment-recovery pipeline. "
    "Given the signal from a single failed payment, classify why it failed "
    "and whether it looks transient (a bare retry right now would plausibly "
    "succeed) or persistent (retrying as-is won't help without a different "
    "action). Calibrate confidence to how certain the signal genuinely makes "
    "you — do not default to a high number out of habit."
)


@dataclass
class AgentTierResult:
    output: RootCauseOutput
    tier: str  # "gemini" | "groq" | "rules_fallback"
    model_used: str
    tokens_used: int | None
    latency_ms: int


def _build_user_prompt(context: dict) -> str:
    return (
        f"failure_reason (payment gateway signal): {context['failure_reason']}\n"
        f"payment_method: {context['method']}\n"
        f"attempt_number: {context['attempt_number']}\n"
        f"amount_paise: {context['amount_paise']}\n"
        f"hours_since_order_created: {context['hours_since_order']:.1f}\n\n"
        "Return only the classification as JSON matching the required schema."
    )


def run_root_cause_agent(
    context: dict,
    gemini: GeminiClient | None = None,
    groq: GroqClient | None = None,
) -> AgentTierResult:
    gemini = gemini if gemini is not None else GeminiClient()
    groq = groq if groq is not None else GroqClient()
    user_prompt = _build_user_prompt(context)

    # Tier 1 — Gemini
    try:
        raw, tokens, latency_ms = gemini.complete_json(SYSTEM_PROMPT, user_prompt, ROOT_CAUSE_JSON_SCHEMA)
        output = RootCauseOutput.model_validate(raw)
        return AgentTierResult(output, "gemini", gemini.model, tokens, latency_ms)
    except (AgentTierError, ValidationError) as exc:
        logger.warning("root_cause_agent: gemini tier failed (%s), falling back to groq", exc)

    # Tier 2 — Groq
    try:
        schema = groq_strict_schema(ROOT_CAUSE_JSON_SCHEMA)
        raw, tokens, latency_ms = groq.complete_json(SYSTEM_PROMPT, user_prompt, "root_cause_output", schema)
        output = RootCauseOutput.model_validate(raw)
        return AgentTierResult(output, "groq", groq.model, tokens, latency_ms)
    except (AgentTierError, ValidationError) as exc:
        logger.warning("root_cause_agent: groq tier failed (%s), falling back to rules", exc)

    # Tier 3 — deterministic rules, always succeeds
    output = rules_fallback.root_cause_fallback(context)
    return AgentTierResult(output, "rules_fallback", "rules-v1", None, 0)