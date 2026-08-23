"""
Output contracts for the Day 3 agents.

Pinned in code, not left to free-form LLM prose, so that:
  - every tier (Gemini / Groq / rules) speaks the exact same shape and can be
    swapped without touching the callers
  - Day 6 scoring against ground_truth_labels.ideal_action is an exact
    string/enum match, not a fuzzy parse of a sentence
  - a malformed or off-taxonomy response from a model is a normal, expected
    failure mode that trips the fallback chain (see llm_clients.py /
    root_cause_agent.py), not a crash
"""
from enum import Enum

from pydantic import BaseModel, Field


class RootCauseCategory(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    CARD_DECLINED = "card_declined"
    OTP_TIMEOUT = "otp_timeout"
    BANK_SERVER_ERROR = "bank_server_error"
    NETWORK_ERROR = "network_error"
    EXPIRED_CARD = "expired_card"
    LIMIT_EXCEEDED = "limit_exceeded"
    USER_CANCELLED = "user_cancelled"
    RISK_FLAGGED = "risk_flagged"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    """Canonical taxonomy — must stay identical to ground_truth_labels.ideal_action
    (see scripts/generate_synthetic_data.py) or Day 6 scoring can't compare
    agent output to the answer key at all."""

    RETRY_NOW = "retry_now"
    RETRY_LATER = "retry_later"
    SEND_PAYMENT_LINK = "send_payment_link"
    ESCALATE_HUMAN = "escalate_human"
    NO_ACTION = "no_action"


class RootCauseOutput(BaseModel):
    root_cause_category: RootCauseCategory
    is_transient: bool  # would a bare retry plausibly work right now?
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class RecoveryStrategyOutput(BaseModel):
    action: RecoveryAction
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


# Plain JSON-schema dicts (not derived from the Pydantic models above) so we
# have full, predictable control over what gets sent to each provider.
# Gemini's responseSchema and Groq's json_schema strict mode both speak this
# dialect; Groq additionally requires additionalProperties: false, added by
# groq_strict_schema() below rather than baked in here, since Gemini doesn't
# recognize that key.

ROOT_CAUSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause_category": {
            "type": "string",
            "enum": [c.value for c in RootCauseCategory],
        },
        "is_transient": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["root_cause_category", "is_transient", "confidence", "reasoning"],
}

RECOVERY_STRATEGY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [a.value for a in RecoveryAction],
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["action", "confidence", "reasoning"],
}


def groq_strict_schema(schema: dict) -> dict:
    """Groq's json_schema strict mode requires additionalProperties: false.
    Gemini's responseSchema rejects unrecognized keys, so this is applied
    only on the Groq call site, not baked into the shared schema dicts."""
    return {**schema, "additionalProperties": False}