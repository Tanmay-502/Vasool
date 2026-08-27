"""
Day 6 — final evaluation. Run ONLY against the `holdout` split.

    python -m scripts.evaluate_holdout
    python -m scripts.evaluate_holdout --limit 50

Runs the full pipeline (Root Cause Agent -> Recovery Strategy Agent ->
Policy Engine) against every RecoveryCase in the `holdout` eval split,
compares the pipeline's final decision to ground_truth_labels, and reports
the PRD's success metrics. Shadow mode only: no AgentDecision/PolicyCheck
rows written, no case.status changes, no Razorpay calls — this is a
read-and-score pass, safe to re-run as often as you like.

INTEGRITY: like scripts/calibrate_confidence.py, this script — never
app/agents/ or app/policy_engine.py — is what's allowed to read
GroundTruth. tests/test_agents_integrity.py only scans app/agents/, so
this living in scripts/ is deliberate, same reasoning as the Day 3 script.

DEV VS HOLDOUT: calibrate_confidence.py is dev-split only, by design.
This script is holdout-split only, by design. Never point either script at
the other's split — mixing them is exactly the kind of unconscious
overfitting the 80/20 split exists to prevent. Touch holdout once, at the
end, and report what it says.

METRIC DEFINITIONS (matching PRD.md's "Success metrics" section):
  - A case's PREDICTION is "recoverable" if the Recovery Strategy Agent's
    chosen action is auto-executable (retry_now / retry_later /
    send_payment_link). escalate_human and no_action count as "not
    recoverable" predictions — the model itself decided there was nothing
    worth attempting.
  - Ground truth "recoverable" = GroundTruth.is_recoverable.
  - Precision = of cases predicted recoverable, how many actually were.
  - Recall = of cases actually recoverable, how many the pipeline caught.
  - False-positive cost = amount_paise summed over cases where the policy
    engine's verdict was EXECUTE but the case was NOT actually recoverable
    — money that would have been spent (a real Payment Link sent) on a
    case that could never have been won regardless of the action taken.
  - % correctly escalated = of cases where the policy verdict was
    HUMAN_REVIEW or BLOCK, how many ground truth agrees needed a human
    (either not recoverable at all, or ideal_action is escalate_human).
  - Would-recover (shadow) = amount_paise summed over cases where the
    verdict was EXECUTE and the case actually was recoverable — the upside
    number, paired with false-positive cost as the downside number.
"""
import argparse
from dataclasses import dataclass

from app.agents.llm_clients import GeminiClient, GroqClient
from app.agents.pipeline import build_case_context
from app.agents.recovery_strategy_agent import run_recovery_strategy_agent
from app.agents.root_cause_agent import run_root_cause_agent
from app.db import SessionLocal
from app.models import GroundTruth, Payment, RecoveryCase
from app.policy_engine import VERDICT_BLOCK, VERDICT_EXECUTE, VERDICT_HUMAN_REVIEW, evaluate_policy

_AUTO_EXECUTABLE_ACTIONS = {"retry_now", "retry_later", "send_payment_link"}


@dataclass
class ScoredCase:
    case_id: int
    amount_paise: int
    predicted_recoverable: bool
    actual_recoverable: bool
    verdict: str
    root_cause_tier: str
    strategy_tier: str
    # None when the verdict was EXECUTE — "correctly escalated" only makes
    # sense to ask about a case that WAS sent to a human/blocked.
    correctly_escalated: bool | None


def _score_case(db, case: RecoveryCase, gemini: GeminiClient, groq: GroqClient) -> ScoredCase:
    """Runs the real pipeline (agents + policy engine) against one case and
    scores it against GroundTruth. Read-only — no DB writes.

    gemini/groq are passed in and reused across the whole run (see main())
    rather than built fresh per case — same reasoning as
    calibrate_confidence.py's `patient_gemini`: a fresh GeminiClient per
    case would throw away `daily_quota_exceeded` every time, so once the
    daily cap is hit the run would keep re-discovering the same dead quota
    for the rest of the holdout split instead of failing fast."""
    context = build_case_context(db, case)

    rc_result = run_root_cause_agent(context, gemini=gemini, groq=groq)
    strategy_context = {
        **context,
        "root_cause_category": rc_result.output.root_cause_category.value,
        "is_transient": rc_result.output.is_transient,
        "root_cause_confidence": rc_result.output.confidence,
    }
    strat_result = run_recovery_strategy_agent(strategy_context, gemini=gemini, groq=groq)

    decision = evaluate_policy(
        action=strat_result.output.action.value,
        confidence=strat_result.output.confidence,
        amount_paise=context["amount_paise"],
        attempt_number=context["attempt_number"],
        customer_opted_out=context["customer_opted_out"],
        root_cause_category=rc_result.output.root_cause_category.value,
        kill_switch_engaged=False,  # shadow mode scores the model's own decision, not ops state
    )

    truth = case.payment.ground_truth
    predicted_recoverable = strat_result.output.action.value in _AUTO_EXECUTABLE_ACTIONS

    correctly_escalated = None
    if decision.verdict in (VERDICT_HUMAN_REVIEW, VERDICT_BLOCK):
        correctly_escalated = (not truth.is_recoverable) or (truth.ideal_action == "escalate_human")

    return ScoredCase(
        case_id=case.id,
        amount_paise=context["amount_paise"],
        predicted_recoverable=predicted_recoverable,
        actual_recoverable=truth.is_recoverable,
        verdict=decision.verdict,
        root_cause_tier=rc_result.tier,
        strategy_tier=strat_result.tier,
        correctly_escalated=correctly_escalated,
    )


def summarize(scored: list[ScoredCase]) -> dict:
    """Pure aggregation over already-scored cases — split out from
    main()/_score_case() so this is unit-testable without a DB or the LLM
    fallback chain."""
    tp = sum(1 for s in scored if s.predicted_recoverable and s.actual_recoverable)
    fp = sum(1 for s in scored if s.predicted_recoverable and not s.actual_recoverable)
    fn = sum(1 for s in scored if not s.predicted_recoverable and s.actual_recoverable)
    tn = sum(1 for s in scored if not s.predicted_recoverable and not s.actual_recoverable)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    fp_cost_paise = sum(
        s.amount_paise for s in scored if s.verdict == VERDICT_EXECUTE and not s.actual_recoverable
    )
    would_recover_paise = sum(
        s.amount_paise for s in scored if s.verdict == VERDICT_EXECUTE and s.actual_recoverable
    )
    revenue_at_risk_paise = sum(s.amount_paise for s in scored)

    escalated = [s for s in scored if s.correctly_escalated is not None]
    correctly_escalated_count = sum(1 for s in escalated if s.correctly_escalated)
    escalation_pct = (correctly_escalated_count / len(escalated) * 100) if escalated else 0.0

    verdict_counts: dict[str, int] = {}
    for s in scored:
        verdict_counts[s.verdict] = verdict_counts.get(s.verdict, 0) + 1

    return {
        "n": len(scored),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_positive_cost_paise": fp_cost_paise,
        "would_recover_paise": would_recover_paise,
        "revenue_at_risk_paise": revenue_at_risk_paise,
        "correctly_escalated_count": correctly_escalated_count,
        "escalated_total": len(escalated),
        "escalation_pct": escalation_pct,
        "verdict_counts": verdict_counts,
    }


def _print_report(summary: dict) -> None:
    print()
    print(f"n = {summary['n']} (holdout split)")
    print(f"Precision: {summary['precision']:.1%}  (TP={summary['tp']}, FP={summary['fp']})")
    print(f"Recall:    {summary['recall']:.1%}  (TP={summary['tp']}, FN={summary['fn']})")
    print(
        f"False-positive cost: ₹{summary['false_positive_cost_paise'] / 100:,.2f} "
        f"(would-be spend on {summary['fp']} cases the pipeline executed but weren't actually recoverable)"
    )
    if summary["escalated_total"]:
        print(
            f"Correctly escalated: {summary['escalation_pct']:.1f}% "
            f"({summary['correctly_escalated_count']}/{summary['escalated_total']} human-review/blocked cases)"
        )
    else:
        print("Correctly escalated: n/a (no cases routed to human review or blocked)")
    print()
    print(f"Revenue at risk (holdout):        ₹{summary['revenue_at_risk_paise'] / 100:,.2f}")
    print(f"Would-recover (shadow EXECUTE):    ₹{summary['would_recover_paise'] / 100:,.2f}")
    print(f"Verdict breakdown: {summary['verdict_counts']}")


def main(limit: int | None) -> None:
    db = SessionLocal()
    try:
        query = (
            db.query(RecoveryCase)
            .join(Payment, Payment.id == RecoveryCase.payment_id)
            .join(GroundTruth, GroundTruth.payment_id == Payment.id)
            .filter(GroundTruth.eval_split == "holdout")
            .order_by(RecoveryCase.id)
        )
        if limit:
            query = query.limit(limit)
        cases = query.all()

        if not cases:
            print("No holdout-split cases found. Run scripts.generate_synthetic_data first.")
            return

        print(f"Scoring {len(cases)} holdout-split cases (shadow mode — no writes, no Razorpay calls)...")

        # Shared across every case — reused so daily_quota_exceeded actually
        # sticks (see _score_case docstring). Patient retry settings since
        # this runs offline, not behind a live request a demo is waiting on.
        patient_gemini = GeminiClient(max_retries=3, max_wait_seconds=45.0)
        groq = GroqClient()
        gemini_exhausted_notice_shown = False

        scored: list[ScoredCase] = []
        for i, case in enumerate(cases, start=1):
            scored.append(_score_case(db, case, patient_gemini, groq))

            if patient_gemini.daily_quota_exceeded and not gemini_exhausted_notice_shown:
                print(
                    f"  [Gemini daily quota exhausted after case {i}/{len(cases)} — "
                    "remaining cases score via Groq/rules only, no further Gemini "
                    "calls attempted this run.]"
                )
                gemini_exhausted_notice_shown = True

            if i % 20 == 0:
                print(f"  ...{i}/{len(cases)} cases scored")

        tier_counts: dict[str, int] = {}
        for s in scored:
            tier_counts[s.strategy_tier] = tier_counts.get(s.strategy_tier, 0) + 1
        print(f"Strategy-agent tier usage: {tier_counts}")

        summary = summarize(scored)
        _print_report(summary)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Final Day 6 evaluation — holdout split ONLY.")
    parser.add_argument("--limit", type=int, default=None, help="cap on holdout cases to score (default: all)")
    args = parser.parse_args()
    main(limit=args.limit)