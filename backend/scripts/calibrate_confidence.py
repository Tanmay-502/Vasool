"""
Day 3 — confidence calibration spot-check.

    python -m scripts.calibrate_confidence            # first 30 dev cases
    python -m scripts.calibrate_confidence --limit 100
    python -m scripts.calibrate_confidence --all       # every dev case

Runs the full Root Cause -> Recovery Strategy pipeline against cases in the
`dev` split ONLY (never `holdout` — that's reserved for Day 6's final,
touch-once numbers) and buckets the Recovery Strategy Agent's confidence
against whether it matched ground_truth.ideal_action. A well-calibrated
agent should show the match rate roughly tracking the confidence bucket:
the 0.90+ bucket should clearly out-score the <0.60 bucket. If it doesn't,
the model is being confidently wrong, which is worse than being unsure.

This script — NOT the agents themselves — is what's allowed to read
GroundTruth. See app/agents/pipeline.py's INTEGRITY RULE docstring and
tests/test_agents_integrity.py, which fails CI if app/agents/ ever imports
GroundTruth directly.

Nothing here is written back to the database (no AgentDecision rows, no
case.status changes) — this is a read-only scoring pass, safe to re-run as
often as you like while iterating on prompts.
"""
import argparse
from collections import defaultdict

from app.agents.pipeline import build_case_context
from app.agents.recovery_strategy_agent import run_recovery_strategy_agent
from app.agents.root_cause_agent import run_root_cause_agent
from app.db import SessionLocal
from app.models import GroundTruth, Payment, RecoveryCase

BUCKET_ORDER = ["0.90-1.00", "0.75-0.89", "0.60-0.74", "<0.60"]


def confidence_bucket(confidence: float) -> str:
    if confidence >= 0.9:
        return "0.90-1.00"
    if confidence >= 0.75:
        return "0.75-0.89"
    if confidence >= 0.6:
        return "0.60-0.74"
    return "<0.60"


def main(limit: int | None) -> None:
    db = SessionLocal()
    buckets = defaultdict(lambda: {"correct": 0, "total": 0})
    tier_counts = defaultdict(int)

    try:
        query = (
            db.query(RecoveryCase)
            .join(Payment, Payment.id == RecoveryCase.payment_id)
            .join(GroundTruth, GroundTruth.payment_id == Payment.id)
            .filter(GroundTruth.eval_split == "dev")
        )
        if limit:
            query = query.limit(limit)
        cases = query.all()

        if not cases:
            print("No dev-split cases found. Run scripts.generate_synthetic_data first.")
            return

        for case in cases:
            context = build_case_context(db, case)
            rc_result = run_root_cause_agent(context)
            strategy_context = {
                **context,
                "root_cause_category": rc_result.output.root_cause_category.value,
                "is_transient": rc_result.output.is_transient,
                "root_cause_confidence": rc_result.output.confidence,
            }
            strat_result = run_recovery_strategy_agent(strategy_context)
            tier_counts[strat_result.tier] += 1

            # scoring only — this is exactly the pattern the module docstring
            # above describes: read GroundTruth here, never inside app/agents/
            truth = case.payment.ground_truth
            bucket = confidence_bucket(strat_result.output.confidence)
            buckets[bucket]["total"] += 1
            if strat_result.output.action.value == truth.ideal_action:
                buckets[bucket]["correct"] += 1

        print(f"Scored {len(cases)} dev-split cases.")
        print("Tier usage:", dict(tier_counts))
        print()
        print(f"{'confidence bucket':<20}{'n':>6}{'match rate':>14}")
        for bucket in BUCKET_ORDER:
            stats = buckets.get(bucket)
            if not stats or stats["total"] == 0:
                continue
            rate = stats["correct"] / stats["total"]
            print(f"{bucket:<20}{stats['total']:>6}{rate:>13.1%}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spot-check agent confidence calibration against the dev split.")
    parser.add_argument("--limit", type=int, default=30, help="cap on dev cases to score (default 30)")
    parser.add_argument("--all", action="store_true", help="score every dev case, ignoring --limit")
    args = parser.parse_args()
    main(limit=None if args.all else args.limit)