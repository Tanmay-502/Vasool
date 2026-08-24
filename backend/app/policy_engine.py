"""
Day 4 — Policy / Guardrail Engine.

Deterministic, zero-LLM safety gate that sits between the agents (Day 3) and
execution (Razorpay, later in Day 4). Takes the Recovery Strategy Agent's
proposed action + confidence, plus case context, and decides one of:

    EXECUTE       — safe to auto-execute via Razorpay Test Mode
    HUMAN_REVIEW  — send to the review queue instead of auto-executing
    BLOCK         — the proposed action is not allowed to happen at all,
                    even by a human clicking "approve as-is" (e.g. contacting
                    an opted-out customer) — still routes to a human, but the
                    reason is a hard compliance rule, not a judgment call

This is the layer the PRD and PROGRESS.md call "compliant escalation" and
Day 5's UI calls the "explainability panel" (green/red chips per check).
Every check below is evaluated and recorded EVERY time, regardless of
whether an earlier check already decided the verdict — so the audit trail
for a case always shows the full picture ("here's what passed, here's what
would also have blocked it"), not just the first thing that tripped.

Deliberately kept pure (no DB session, no I/O, no imports from app.agents or
app.models) so it's trivial to unit test exhaustively and easy to reason
about independently of the probabilistic agents feeding into it. The DB-
writing wrapper (PolicyCheck rows, case.status, Action creation) is a
separate module — this file is only the decision logic itself.
"""
from dataclasses import dataclass, field

from app.config import settings

# Actions that actually move money or contact a customer, i.e. the only ones
# that could ever reach EXECUTE. escalate_human and no_action are terminal
# outcomes from the agent's own taxonomy and never auto-execute regardless of
# confidence or amount — there's nothing to execute.
_AUTO_EXECUTABLE_ACTIONS = {"retry_now", "retry_later", "send_payment_link"}

# Of those, the subset that reaches out to the customer directly and is
# therefore subject to the opt-out guardrail.
_CONTACT_ACTIONS = {"send_payment_link"}

VERDICT_EXECUTE = "EXECUTE"
VERDICT_HUMAN_REVIEW = "HUMAN_REVIEW"
VERDICT_BLOCK = "BLOCK"

# Stable, ordered list of every check this engine runs — useful for tests and
# for the Day 5 UI to know what columns/chips to render without guessing.
POLICY_CHECK_NAMES = [
    "kill_switch",
    "risk_flagged_escalation",
    "action_type",
    "opt_out",
    "confidence_floor",
    "amount_ceiling",
    "retry_ceiling",
]


@dataclass
class PolicyCheckResult:
    check_name: str
    passed: bool
    reason: str


@dataclass
class PolicyDecision:
    verdict: str  # EXECUTE | HUMAN_REVIEW | BLOCK
    checks: list[PolicyCheckResult] = field(default_factory=list)


def evaluate_policy(
    *,
    action: str,
    confidence: float,
    amount_paise: int,
    attempt_number: int,
    customer_opted_out: bool,
    root_cause_category: str,
    kill_switch_engaged: bool = False,
) -> PolicyDecision:
    checks: list[PolicyCheckResult] = []

    # ---- Global kill switch ----
    checks.append(
        PolicyCheckResult(
            "kill_switch",
            passed=not kill_switch_engaged,
            reason=(
                "kill switch is engaged — all auto-execution halted"
                if kill_switch_engaged
                else "kill switch not engaged"
            ),
        )
    )

    # ---- risk_flagged always escalates, no exceptions ----
    is_risk_flagged = root_cause_category == "risk_flagged"
    checks.append(
        PolicyCheckResult(
            "risk_flagged_escalation",
            passed=not is_risk_flagged,
            reason=(
                "root cause is risk_flagged — always human review, regardless of confidence"
                if is_risk_flagged
                else "root cause is not risk-flagged"
            ),
        )
    )

    # ---- action must be one that actually does something executable ----
    action_is_executable_type = action in _AUTO_EXECUTABLE_ACTIONS
    checks.append(
        PolicyCheckResult(
            "action_type",
            passed=action_is_executable_type,
            reason=(
                f"action '{action}' is auto-executable"
                if action_is_executable_type
                else f"action '{action}' is not auto-executable (escalate_human/no_action)"
            ),
        )
    )

    # ---- opted-out customers never get contacted ----
    is_contact_action = action in _CONTACT_ACTIONS
    opt_out_violation = is_contact_action and customer_opted_out
    checks.append(
        PolicyCheckResult(
            "opt_out",
            passed=not opt_out_violation,
            reason=(
                "customer has opted out of contact — cannot send payment link"
                if opt_out_violation
                else "no opt-out conflict for this action"
            ),
        )
    )

    # ---- confidence floor ----
    confidence_ok = confidence >= settings.MIN_CONFIDENCE_TO_AUTO_EXECUTE
    checks.append(
        PolicyCheckResult(
            "confidence_floor",
            passed=confidence_ok,
            reason=(
                f"confidence {confidence:.2f} meets floor {settings.MIN_CONFIDENCE_TO_AUTO_EXECUTE}"
                if confidence_ok
                else f"confidence {confidence:.2f} below floor {settings.MIN_CONFIDENCE_TO_AUTO_EXECUTE}"
            ),
        )
    )

    # ---- amount ceiling ----
    amount_ok = amount_paise <= settings.MAX_AUTO_RETRY_AMOUNT_PAISE
    checks.append(
        PolicyCheckResult(
            "amount_ceiling",
            passed=amount_ok,
            reason=(
                f"amount {amount_paise}p within ceiling {settings.MAX_AUTO_RETRY_AMOUNT_PAISE}p"
                if amount_ok
                else f"amount {amount_paise}p exceeds ceiling {settings.MAX_AUTO_RETRY_AMOUNT_PAISE}p"
            ),
        )
    )

    # ---- retry ceiling ----
    attempts_ok = attempt_number <= settings.MAX_RETRY_ATTEMPTS
    checks.append(
        PolicyCheckResult(
            "retry_ceiling",
            passed=attempts_ok,
            reason=(
                f"attempt {attempt_number} within max {settings.MAX_RETRY_ATTEMPTS}"
                if attempts_ok
                else f"attempt {attempt_number} exceeds max {settings.MAX_RETRY_ATTEMPTS}"
            ),
        )
    )

    # ---- Verdict priority: hard stops first, then judgment-call gates ----
    if kill_switch_engaged:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)
    if is_risk_flagged:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)
    if not action_is_executable_type:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)
    if opt_out_violation:
        return PolicyDecision(VERDICT_BLOCK, checks)
    if not confidence_ok:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)
    if not amount_ok:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)
    if not attempts_ok:
        return PolicyDecision(VERDICT_HUMAN_REVIEW, checks)

    return PolicyDecision(VERDICT_EXECUTE, checks)