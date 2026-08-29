"""
Day 6 — full-dataset shadow-mode backtest.

    python -m scripts.shadow_backtest --limit 150
    python -m scripts.shadow_backtest --run-all

Runs the same real pipeline + policy engine scoring as
scripts/evaluate_holdout.py — this module imports ScoredCase / _score_case /
summarize from it directly rather than re-implementing the same logic
twice — but against EVERY failed payment that has a ground-truth label:
dev split AND holdout split, not holdout-only.

DAY 6.1 HARDENING — Windows encoding bug: every file write here originally
used Path.write_text()/read_text() with no explicit `encoding=` argument,
which defaults to locale.getpreferredencoding() — UTF-8 on Linux/Mac, but
cp1252 on Windows. The report contains a rupee sign (₹, U+20B9), which
cp1252 has no slot for. Every read_text()/write_text() call below now
passes encoding="utf-8" explicitly, and the final console print() is
wrapped so a legacy-codepage Windows terminal can't crash the run either.

DAY 6.2 HARDENING — long-running DB connection drops (caught on the same
real Windows run that hit the Day 6.1 bug, after that fix let it run far
enough to hit the next one): a single SQLAlchemy session was held open
for the entire batch and reused across every case. Somewhere around case
100+ into a 150-case run — after enough Gemini 429 waits and Groq
read-timeout/SSL-handshake retries to spend real wall-clock time between
database queries — the underlying Postgres connection got closed out from
under the session (psycopg.OperationalError: "server closed the
connection unexpectedly"), and the run crashed. Two separate problems
made that worse than it needed to be:
  1. app/db.py's pool_pre_ping=True only re-validates a connection when
     it's checked OUT of the pool. This script checks one connection out
     once, at SessionLocal() at the top of main(), and holds it for the
     whole run — so pre_ping never got a chance to catch the dead
     connection before a query tried to use it.
  2. _save_cases(existing) was only called once, AFTER the whole to_score
     loop finished. A crash on case ~104 of 150 meant the cases already
     scored earlier in that same run were never written to
     shadow_backtest_cases.json at all — the exact opposite of what the
     "accumulates across runs" design below promises.
Fix: (a) the loop now catches OperationalError/DBAPIError per case, rolls
the session back, and retries that one case once — a rollback releases
the dead connection back to the pool as invalid, so the retry's next
query gets a fresh, pre-pinged connection instead of the stale one. If the
retry also fails, that single case is skipped (logged, not raised) — it
stays unscored and gets picked up automatically on the next invocation —
rather than aborting every remaining case in the batch. (b)
_save_cases(existing) now runs after every case, not just at the end of
the loop, so a crash of any kind (DB drop, Ctrl+C, an unrelated bug) loses
at most the one case in flight, never the whole run's progress.

WHY THIS EXISTS, AND HOW IT DIFFERS FROM evaluate_holdout.py:
  evaluate_holdout.py is the strict, doc-of-record number: holdout split
  ONLY, touched once, at the end (PRD.md's "Success metrics" section,
  PROGRESS.md's Day 6 checklist). That discipline stays completely
  untouched by this file — this script never filters or even reads
  eval_split at all, so it can never accidentally become the "official"
  precision/recall claim.

  This script is the PRD's OTHER Day 6 ask: "Shadow-mode backtest: replay
  the full synthetic dataset with execution disabled, log what would have
  happened." Its job is a bigger, demo-facing number — "here's what
  measured money recovered looks like across the whole batch, not just
  102 holdout cases" — for the pitch and the README, not the
  precision/recall claim itself. Nothing here trains or tunes anything;
  the agents never see GroundTruth (same integrity rule as everywhere
  else — this script lives in scripts/, not app/agents/, for exactly that
  reason, same as evaluate_holdout.py and calibrate_confidence.py).

QUOTA REALITY, AND WHY THIS ACCUMULATES ACROSS RUNS:
  506 failed payments x 2 agent calls (root cause + strategy) = up to
  ~1,012 LLM calls in a single full pass. Gemini's free-tier RPD and
  Groq's free-tier TPD (see app/agents/llm_clients.py's daily_quota_exceeded
  handling) will not survive that in one sitting — both tiers fall through
  to rules_fallback partway in, which is fine (rules_fallback always
  produces a valid decision) but means one single run can't produce an
  accurate tier-mix number.

  So this script is checkpointed: every already-scored case_id is
  persisted to reports/shadow_backtest_cases.json, keyed by case_id. Each
  run loads that file, skips every case_id already in it, scores only the
  next --limit NEW cases, merges the results back in, and regenerates
  reports/shadow_backtest_report.md from the FULL accumulated set every
  time — so the report always reflects everything scored so far, and a
  quota cutoff (or, per Day 6.2 above, a DB/network cutoff) mid-run never
  throws away work already done. Run it a handful of times across a day
  or two (`--limit 150` a few times, or `--run-all` once quota resets)
  until coverage is high enough to be a credible number, then commit both
  files under reports/.

Shadow mode: no AgentDecision/PolicyCheck rows written, no case.status
changes, no Razorpay calls. Safe to re-run as many times as you like.
"""
import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import DBAPIError, OperationalError

from app.agents.llm_clients import GeminiClient, GroqClient
from app.db import SessionLocal
from app.models import GroundTruth, Payment, RecoveryCase
from scripts.evaluate_holdout import ScoredCase, _score_case, summarize

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
CASES_FILE = REPORTS_DIR / "shadow_backtest_cases.json"
REPORT_FILE = REPORTS_DIR / "shadow_backtest_report.md"

DEFAULT_LIMIT = 150


def _load_existing_cases() -> dict:
    """Keyed by str(case_id) -> ScoredCase-as-dict.

    Deliberately reads the CASES_FILE module-level name directly inside the
    function body rather than binding it as a default parameter value — see
    the module's test suite for the regression this guards against.
    encoding="utf-8" is explicit — see the DAY 6.1 HARDENING note above.
    """
    if not CASES_FILE.exists():
        return {}
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def _save_cases(cases: dict) -> None:
    """Same reasoning as _load_existing_cases() above — CASES_FILE is read
    fresh here, not bound as a default argument. Called after EVERY case
    scored (see DAY 6.2 HARDENING above) — not just once at the end of a
    batch — so a mid-run crash of any kind never discards already-scored
    work. Writing a small JSON file after each case is cheap (milliseconds)
    next to LLM call latency (seconds), so this costs nothing meaningful."""
    CASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CASES_FILE.write_text(json.dumps(cases, indent=2, sort_keys=True), encoding="utf-8")


def _scored_case_to_dict(scored: ScoredCase) -> dict:
    return asdict(scored)


def _dict_to_scored_case(data: dict) -> ScoredCase:
    return ScoredCase(**data)


def _score_case_with_db_retry(db, case, gemini, groq) -> ScoredCase | None:
    """Wraps evaluate_holdout._score_case with one bounded retry against a
    transient DB connection drop (see DAY 6.2 HARDENING in the module
    docstring). Returns None if the case couldn't be scored even after a
    retry — the caller skips it and moves on; it stays unscored on disk and
    gets picked up automatically on the next invocation of this script."""
    try:
        return _score_case(db, case, gemini, groq)
    except (OperationalError, DBAPIError) as exc:
        print(
            f"  [case {case.id}: DB connection dropped ({exc.__class__.__name__}) "
            "— rolling back and retrying once...]"
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 — rollback itself failing is not fatal here
            pass
        try:
            return _score_case(db, case, gemini, groq)
        except (OperationalError, DBAPIError) as exc2:
            print(
                f"  [case {case.id}: retry also failed ({exc2.__class__.__name__}) "
                "— skipping for now, it will be picked up on the next run.]"
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None


def _render_report(
    scored: list[ScoredCase], total_dataset_size: int, generated_at: datetime
) -> str:
    """Pure function — no DB, no LLM — so this is unit-testable on canned
    ScoredCase lists, same spirit as evaluate_holdout.summarize()."""
    summary = summarize(scored)
    n = summary["n"]
    coverage_pct = round(n / total_dataset_size * 100, 1) if total_dataset_size else 0.0

    tier_counts: dict[str, int] = {}
    for s in scored:
        tier_counts[s.strategy_tier] = tier_counts.get(s.strategy_tier, 0) + 1

    lines = [
        "# Vasool — Full-Dataset Shadow-Mode Backtest",
        "",
        f"_Generated: {generated_at.strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"**Coverage:** {n} / {total_dataset_size} failed payments scored ({coverage_pct}%)",
        "",
        "> Shadow mode: no `AgentDecision`/`PolicyCheck` rows written, no "
        "`case.status` changes, no Razorpay calls. Read-and-score only, "
        "safe to re-run.",
        "",
        "## Headline numbers",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Revenue at risk (scored subset) | \u20b9{summary['revenue_at_risk_paise'] / 100:,.2f} |",
        f"| Would recover (shadow EXECUTE, actually recoverable) | \u20b9{summary['would_recover_paise'] / 100:,.2f} |",
        f"| False-positive cost (shadow EXECUTE, NOT recoverable) | \u20b9{summary['false_positive_cost_paise'] / 100:,.2f} |",
        f"| Precision | {summary['precision']:.1%} (TP={summary['tp']}, FP={summary['fp']}) |",
        f"| Recall | {summary['recall']:.1%} (TP={summary['tp']}, FN={summary['fn']}) |",
    ]

    if summary["escalated_total"]:
        lines.append(
            f"| Correctly escalated | {summary['escalation_pct']:.1f}% "
            f"({summary['correctly_escalated_count']}/{summary['escalated_total']} "
            "human-review/blocked cases) |"
        )
    else:
        lines.append(
            "| Correctly escalated | n/a (no cases routed to human review or blocked) |"
        )

    lines += ["", "## Verdict breakdown", ""]
    for verdict, count in sorted(summary["verdict_counts"].items()):
        lines.append(f"- {verdict}: {count}")

    lines += ["", "## Recovery Strategy Agent tier usage (across all scored cases)", ""]
    for tier, count in sorted(tier_counts.items()):
        lines.append(f"- {tier}: {count}")

    lines += [
        "",
        "---",
        "",
        "Run `python -m scripts.shadow_backtest --limit 150` to score more "
        "cases (accumulates — already-scored cases are never re-scored).",
        "",
        "This is a full-dataset, demo-facing number (dev + holdout "
        "combined). The strict, doc-of-record precision/recall claim is "
        "`scripts.evaluate_holdout` (holdout split only, touched once).",
        "",
    ]
    return "\n".join(lines)


def _print_report_safely(report_text: str) -> None:
    """Print the report to the console without letting a legacy-codepage
    terminal (cp1252/cp437 — the Windows default outside Windows Terminal
    with UTF-8 configured) crash the whole run over a display nicety. The
    file on disk always has the real ₹ characters (written with explicit
    UTF-8 — see _save_cases/main below); this only affects what shows up
    in the terminal itself."""
    try:
        print(report_text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        safe_text = report_text.encode(encoding, errors="replace").decode(encoding)
        print(safe_text)
        # Pure ASCII on purpose — this message exists to run *after* a
        # UnicodeEncodeError, so it must never itself contain a character
        # (like the rupee sign) that could trigger the same error again.
        print(
            "\n[Note: your terminal's encoding could not display some "
            "characters (likely the rupee sign) -- shown above as "
            "placeholders. The report file on disk has the correct "
            "characters; open it directly to see them.]"
        )


def main(limit: int | None, run_all: bool) -> None:
    effective_limit = None if run_all else (limit if limit is not None else DEFAULT_LIMIT)

    db = SessionLocal()
    try:
        all_case_rows = (
            db.query(RecoveryCase)
            .join(Payment, Payment.id == RecoveryCase.payment_id)
            .join(GroundTruth, GroundTruth.payment_id == Payment.id)
            .order_by(RecoveryCase.id)
            .all()
        )
        total_dataset_size = len(all_case_rows)

        if not all_case_rows:
            print("No cases with ground truth found. Run scripts.generate_synthetic_data first.")
            return

        existing = _load_existing_cases()
        already_scored_ids = {int(k) for k in existing}

        remaining = [c for c in all_case_rows if c.id not in already_scored_ids]

        if not remaining:
            print(
                f"All {total_dataset_size} cases already scored — nothing new to run. "
                f"Regenerating report from {len(existing)} accumulated cases."
            )
        else:
            to_score = remaining if effective_limit is None else remaining[:effective_limit]
            print(
                f"Scoring {len(to_score)} new case(s) "
                f"({len(already_scored_ids)} already scored, {len(remaining)} remaining "
                f"before this run, {total_dataset_size} total)..."
            )

            patient_gemini = GeminiClient(max_retries=3, max_wait_seconds=45.0)
            groq = GroqClient()
            gemini_exhausted_notice_shown = False
            skipped_case_ids: list[int] = []

            for i, case in enumerate(to_score, start=1):
                scored = _score_case_with_db_retry(db, case, patient_gemini, groq)
                if scored is None:
                    skipped_case_ids.append(case.id)
                    continue

                existing[str(scored.case_id)] = _scored_case_to_dict(scored)
                # Save after every case, not just at the end of the batch —
                # see DAY 6.2 HARDENING above.
                _save_cases(existing)

                if patient_gemini.daily_quota_exceeded and not gemini_exhausted_notice_shown:
                    print(
                        f"  [Gemini daily quota exhausted after case {i}/{len(to_score)} — "
                        "remaining cases this run score via Groq/rules only.]"
                    )
                    gemini_exhausted_notice_shown = True

                if i % 20 == 0:
                    print(f"  ...{i}/{len(to_score)} new cases scored")

            print(f"Saved {len(existing)} accumulated cases to {CASES_FILE}")
            if skipped_case_ids:
                print(
                    f"Skipped {len(skipped_case_ids)} case(s) after a DB error survived a "
                    f"retry: {skipped_case_ids}. They stay unscored and will be retried "
                    "automatically the next time this script runs."
                )

        all_scored = [_dict_to_scored_case(v) for v in existing.values()]
        report_text = _render_report(all_scored, total_dataset_size, datetime.now(timezone.utc))
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(report_text, encoding="utf-8")
        print(f"Report written to {REPORT_FILE}")
        print()
        _print_report_safely(report_text)
    finally:
        db.close()


if __name__ == "__main__":
    # Windows consoles typically default stdout to a legacy code page
    # (cp1252/cp437) that can't encode the rupee sign this report prints.
    # Force UTF-8 for stdout when running as a script. Guarded because
    # reconfigure() isn't guaranteed on every stream (e.g. some redirected/
    # piped invocations) and a display preference must never crash the
    # actual scoring run — _print_report_safely() above is the real
    # safety net regardless of whether this succeeds.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Full-dataset shadow-mode backtest — accumulates across quota-limited runs."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"max NEW cases to score this run (default {DEFAULT_LIMIT}, ignored with --run-all)",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="score every remaining unscored case in one run, ignoring --limit",
    )
    args = parser.parse_args()
    main(limit=args.limit, run_all=args.run_all)