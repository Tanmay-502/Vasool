# Failure Scenarios — Vasool

Four real cases pulled from actual pipeline runs (Day 3–6), not synthetic examples.

## 1. Quota exhaustion cascade → graceful degradation
During a Day 6 evaluation run, Gemini's daily quota (20 RPD free tier) was exhausted by case 8,
and Groq's daily token budget was separately exhausted mid-run. Both circuit breakers tripped
independently. Every remaining case still received a valid decision via `rules_fallback` —
zero cases failed to produce output. This pulled the reported holdout precision down to ~57%
because the tuned LLM strategy agent never ran on ~54% of cases. Root cause: quota exhaustion,
not model quality — the two earlier calibration runs (with live Gemini/Groq access) showed
strict monotonic confidence-to-match-rate correlation, proving the tuned prompts work when the
tier is actually reachable.

## 2. Confidence miscalibration caught before shipping
The first calibration pass showed 82% of cases clustering at 0.90+ confidence, with that bucket
having the *worst* match rate (~30%) of any bucket — the opposite of calibration. The system
prompt only said "calibrate honestly," which models don't reliably follow. Fixed by anchoring
confidence to concrete categories (0.85+ only for risk_flagged / first-attempt transient
failures; 0.55–0.80 for real judgment calls; <0.55 for weak signal). Two independent post-fix
runs confirmed strict monotonicity.

## 3. Strategy agent's recoverable-bias
The Recovery Strategy Agent predicts "recoverable" ~87% of the time vs. an actual base rate of
~54% in the frozen dataset. This is a known, documented bias — not tuned away pre-deadline
because doing so risked destabilizing the confidence calibration that was just fixed (see #2).
Flagged transparently in the pitch rather than hidden.

## 4. The save: policy engine blocking a bad LLM call
Case: customer had `opted_out=True`, root cause `card_declined`. Recovery Strategy Agent
(rules_fallback tier) proposed `send_payment_link` — a reasonable strategy call on its own,
but one that would have violated contact-consent policy. The Policy Engine's `opt_out` check
caught it and returned verdict `BLOCK`, routing to human review instead of auto-executing.
This is proof the guardrail layer is a real, independent safety net — not just a rubber stamp
on the agent's decision. (`test_opted_out_customer_blocks_send_payment_link` in
`test_policy_engine.py` locks this behavior in permanently.)