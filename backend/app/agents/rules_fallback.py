"""
Tier 3 of the fallback chain: deterministic, zero-LLM, always succeeds.

Deliberately written independently of
scripts/generate_synthetic_data.py's compute_ground_truth(). That function
defines the answer key this project is scored against — if the fallback
heuristic secretly mirrored its probabilities, any case that lands on this
tier would silently "know" the answer, and Day 6 precision/recall would
measure nothing. This heuristic uses its own, simpler reasoning and is
allowed to be less accurate than the LLM tiers; that's the honest trade-off
of a fallback path.

Day 4's policy engine remains the authoritative safety gate (opted_out,
amount ceilings, retry ceilings, confidence floor). The light opted_out
check here is a courtesy, not a substitute for it.
"""
from app.agents.schemas import RecoveryAction, RecoveryStrategyOutput, RootCauseCategory, RootCauseOutput

_TRANSIENT_REASONS = {"otp_timeout", "bank_server_error", "network_error"}
_KNOWN_REASONS = {c.value for c in RootCauseCategory if c != RootCauseCategory.UNKNOWN}


def root_cause_fallback(context: dict) -> RootCauseOutput:
    reason = str(context.get("failure_reason") or "").strip().lower()
    if reason in _KNOWN_REASONS:
        category = RootCauseCategory(reason)
        confidence = 0.68  # gateway signal is strong, but no LLM cross-check happened
    else:
        category = RootCauseCategory.UNKNOWN
        confidence = 0.25

    return RootCauseOutput(
        root_cause_category=category,
        is_transient=reason in _TRANSIENT_REASONS,
        confidence=confidence,
        reasoning="rules_fallback: passthrough of gateway-reported failure_reason, no LLM available.",
    )


def recovery_strategy_fallback(context: dict) -> RecoveryStrategyOutput:
    category = context["root_cause_category"]
    is_transient = context["is_transient"]
    attempt_number = context["attempt_number"]
    opted_out = context.get("customer_opted_out", False)

    if category == RootCauseCategory.RISK_FLAGGED.value:
        return RecoveryStrategyOutput(
            action=RecoveryAction.ESCALATE_HUMAN,
            confidence=0.9,
            reasoning="rules_fallback: risk-flagged cases always go to a human, regardless of anything else.",
        )

    if is_transient:
        return RecoveryStrategyOutput(
            action=RecoveryAction.RETRY_NOW,
            confidence=0.68 if attempt_number == 1 else 0.48,
            reasoning=(
                "rules_fallback: transient failure signal supports a retry; "
                f"attempt {attempt_number} lowers confidence and the policy retry ceiling remains authoritative."
            ),
        )

    if category in {RootCauseCategory.INSUFFICIENT_FUNDS.value, RootCauseCategory.LIMIT_EXCEEDED.value}:
        return RecoveryStrategyOutput(
            action=RecoveryAction.RETRY_LATER,
            confidence=0.55 if attempt_number == 1 else 0.45,
            reasoning=(
                "rules_fallback: funds/limit issue, give it time before retrying; "
                f"attempt {attempt_number} lowers confidence."
            ),
        )

    if category in {
        RootCauseCategory.CARD_DECLINED.value,
        RootCauseCategory.EXPIRED_CARD.value,
        RootCauseCategory.USER_CANCELLED.value,
    }:
        if opted_out:
            return RecoveryStrategyOutput(
                action=RecoveryAction.ESCALATE_HUMAN,
                confidence=0.5,
                reasoning="rules_fallback: would normally send a payment link, but customer opted out of contact.",
            )
        if attempt_number == 1:
            return RecoveryStrategyOutput(
                action=RecoveryAction.SEND_PAYMENT_LINK,
                confidence=0.56,
                reasoning="rules_fallback: first attempt card/user-side issue, a fresh payment link is the safest nudge.",
            )
        return RecoveryStrategyOutput(
            action=RecoveryAction.NO_ACTION,
            confidence=0.42,
            reasoning="rules_fallback: repeated card/user-side failure makes another automated contact unlikely to help.",
        )

    return RecoveryStrategyOutput(
        action=RecoveryAction.ESCALATE_HUMAN,
        confidence=0.3,
        reasoning="rules_fallback: unrecognized pattern, defer to a human rather than guess.",
    )