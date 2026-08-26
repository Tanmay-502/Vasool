"""
Day 3 — confidence calibration spot-check.

    python -m scripts.calibrate_confidence            # first 30 dev cases
    python -m scripts.calibrate_confidence --limit 100
    python -m scripts.calibrate_confidence --all       # every dev case
    python -m scripts.calibrate_confidence --all --sleep 8

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

DAY 4 HARDENING — first attempt: `--all` used to fire up to ~800 back-to-
back Gemini calls with zero pacing. That first fix assumed the bottleneck
was RPM and added --sleep pacing plus retry-with-backoff to GeminiClient.

DAY 4.1 — wrong diagnosis. The actual 429 body showed quotaId
"GenerateRequestsPerDayPerProjectPerModel-FreeTier" — a DAILY quota (RPD)
of 20 requests for gemini-3-flash-preview on this account, not an RPM
burst. No amount of pacing between calls fixes a per-day cap; it only
resets once a day. The real fix lives in app/agents/llm_clients.py:
GeminiClient now detects an RPD-type 429 (vs an RPM-type one), never
retries it, and remembers it on `self.daily_quota_exceeded` so every later
call on the SAME INSTANCE fails instantly with no network cost. Since this
script builds one GeminiClient (`patient_gemini`) and reuses it for the
whole run, hitting the daily cap on case 8 means cases 9+ skip Gemini
instantly instead of rediscovering the same dead quota every time.

`--sleep` (default now 2.0s, was 5.0s) is no longer sized for Gemini at
all — it either succeeds or fails-fast now. It's sized for Groq's
published 30 RPM ceiling on openai/gpt-oss-20b, since once Gemini's RPD is
spent, effectively every remaining case makes 2 back-to-back Groq calls.

Neither change touches the frozen dataset or the RNG stream — this script
only reads already-generated rows, it doesn't call generate_synthetic_data.
If Gemini still falls back after this (e.g. today's RPD quota is already
spent from an earlier run), that's a real quota limit, not a bug — rerun
with a smaller --limit, wait for the daily reset, or enable billing.

KNOWN LIMITATION: Groq's own free tier caps openai/gpt-oss-20b at 200,000
tokens/day. A full --all run against ~400 dev cases (~800 LLM calls) can
plausibly hit THAT ceiling too, once Gemini's RPD is exhausted and
everything routes to Groq. If Groq calls start failing partway through a
long --all run, that's this limit, not a new bug.
"""
import argparse
import time
from collections import defaultdict

from app.agents.llm_clients import GeminiClient
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


def main(limit: int | None, sleep_seconds: float, offset: int = 0) -> None:
    db = SessionLocal()
    buckets = defaultdict(lambda: {"correct": 0, "total": 0})
    tier_counts = defaultdict(int)

    # Shared across every case — this is what makes daily_quota_exceeded
    # actually save time: once it flips True on this instance, every later
    # case's Gemini call fails instantly instead of hitting the network.
    patient_gemini = GeminiClient(max_retries=3, max_wait_seconds=45.0)
    gemini_exhausted_notice_shown = False

    try:
        query = (
            db.query(RecoveryCase)
            .join(Payment, Payment.id == RecoveryCase.payment_id)
            .join(GroundTruth, GroundTruth.payment_id == Payment.id)
            .filter(GroundTruth.eval_split == "dev")
            .order_by(RecoveryCase.id)  # deterministic, so --offset actually skips a stable set
        )
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        cases = query.all()
        print(f"Scoring dev cases [offset={offset}, limit={limit or 'all remaining'}]...")

        if not cases:
            print("No dev-split cases found. Run scripts.generate_synthetic_data first.")
            return

        for i, case in enumerate(cases, start=1):
            context = build_case_context(db, case)
            rc_result = run_root_cause_agent(context, gemini=patient_gemini)
            strategy_context = {
                **context,
                "root_cause_category": rc_result.output.root_cause_category.value,
                "is_transient": rc_result.output.is_transient,
                "root_cause_confidence": rc_result.output.confidence,
            }
            strat_result = run_recovery_strategy_agent(strategy_context, gemini=patient_gemini)
            tier_counts[strat_result.tier] += 1

            if patient_gemini.daily_quota_exceeded and not gemini_exhausted_notice_shown:
                print(
                    f"  [Gemini daily quota exhausted after case {i}/{len(cases)} — "
                    "remaining cases score via Groq/rules only, no further Gemini "
                    "calls attempted this run.]"
                )
                gemini_exhausted_notice_shown = True

            # scoring only — this is exactly the pattern the module docstring
            # above describes: read GroundTruth here, never inside app/agents/
            truth = case.payment.ground_truth
            bucket = confidence_bucket(strat_result.output.confidence)
            buckets[bucket]["total"] += 1
            if strat_result.output.action.value == truth.ideal_action:
                buckets[bucket]["correct"] += 1

            if i % 10 == 0:
                print(f"  ...{i}/{len(cases)} cases scored (tiers so far: {dict(tier_counts)})")

            if i < len(cases):  # no point sleeping after the very last case
                time.sleep(sleep_seconds)

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
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "skip this many dev cases before scoring — run a second free-tier "
            "session the next day with e.g. --offset 150 to cover a fresh "
            "slice instead of re-scoring the same cases (default 0)"
        ),
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help=(
            "seconds to wait between cases. Not sized for Gemini (that's a "
            "daily cap, not RPM — pacing can't help it); sized for Groq's "
            "30 RPM ceiling on openai/gpt-oss-20b, which is what most calls "
            "fall through to once Gemini's RPD is spent (default 2.0)"
        ),
    )
    args = parser.parse_args()
    main(limit=None if args.all else args.limit, sleep_seconds=args.sleep, offset=args.offset)