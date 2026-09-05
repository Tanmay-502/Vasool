# Vasool — Full-Dataset Shadow-Mode Backtest

_Generated: 2026-08-29 13:22 UTC_

**Coverage:** 150 / 506 failed payments scored (29.6%)

> Shadow mode: no `AgentDecision`/`PolicyCheck` rows written, no `case.status` changes, no Razorpay calls. Read-and-score only, safe to re-run.

## Headline numbers

| Metric | Value |
|---|---|
| Revenue at risk (scored subset) | ₹698,308.34 |
| Would recover (shadow EXECUTE, actually recoverable) | ₹37,031.18 |
| False-positive cost (shadow EXECUTE, NOT recoverable) | ₹7,312.23 |
| Precision | 47.9% (TP=69, FP=75) |
| Recall | 98.6% (TP=69, FN=1) |
| Correctly escalated | 57.7% (71/123 human-review/blocked cases) |

## Verdict breakdown

- EXECUTE: 27
- HUMAN_REVIEW: 123

## Recovery Strategy Agent tier usage (across all scored cases)

- gemini: 7
- groq: 143

---

Run `python -m scripts.shadow_backtest --limit 150` to score more cases (accumulates — already-scored cases are never re-scored).

This is a full-dataset, demo-facing number (dev + holdout combined). The strict, doc-of-record precision/recall claim is `scripts.evaluate_holdout` (holdout split only, touched once).
