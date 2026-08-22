# PRD — Vasool

## Problem
Revenue leaks in disconnected steps: a payment fails, a checkout gets
abandoned, a subscription charge doesn't go through — and by the time anyone
notices, the moment to recover it has usually passed.

## Flagship scope (v1 — the only flow being built)
Failed payment / subscription-retry recovery:
Payment fails → root cause identified → recovery strategy chosen →
policy-gated → executed via Razorpay Test Mode → outcome tracked.

**Explicitly out of scope for v1:** checkout-abandonment recovery, B2B
receivables chasing. Add only if the core flow finishes early.

## Success metrics (defined now, Day 1 — not adjusted after seeing results)
- Revenue at risk (₹) vs revenue recovered (₹) across a held-out batch
- Precision / recall on "is this actually recoverable" vs pre-labeled ground truth
- False-positive cost (₹ wasted on actions that shouldn't have fired)
- % of cases correctly escalated to human review instead of auto-executed

## The bar
Don't just detect — show measured money recovered, with compliant
escalation, stopping rules, and a full audit trail.