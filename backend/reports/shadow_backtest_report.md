# Vasool — Full-Dataset Shadow-Mode Backtest

_Generated: 2026-09-05 07:27 UTC_

**Coverage:** 300 / 506 failed payments scored (59.3%)

> Shadow mode: no `AgentDecision`/`PolicyCheck` rows written, no `case.status` changes, no Razorpay calls. Read-and-score only, safe to re-run.

## Headline numbers

| Metric | Value |
|---|---|
| Revenue at risk (scored subset) | ₹1,475,426.93 |
| Would recover (shadow EXECUTE, actually recoverable) | ₹65,548.28 |
| False-positive cost (shadow EXECUTE, NOT recoverable) | ₹13,456.89 |
| Precision | 49.8% (TP=142, FP=143) |
| Recall | 97.9% (TP=142, FN=3) |
| Correctly escalated | 56.1% (142/253 human-review/blocked cases) |

## Verdict breakdown

- EXECUTE: 47
- HUMAN_REVIEW: 253

## Recovery Strategy Agent tier usage (across all scored cases)

- gemini: 17
- groq: 283

---

Run `python -m scripts.shadow_backtest --limit 150` to score more cases (accumulates — already-scored cases are never re-scored).

This is a full-dataset, demo-facing number (dev + holdout combined). The strict, doc-of-record precision/recall claim is `scripts.evaluate_holdout` (holdout split only, touched once).
