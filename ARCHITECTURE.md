# Architecture — Vasool

## Flow

Payment fails
v
Root Cause Agent (Gemini -> Groq fallback -> rules fallback)
v
Recovery Strategy Agent (same fallback chain)
v
Policy / Guardrail Engine (deterministic, zero LLM, unit-tested)
v
EXECUTE or HUMAN_REVIEW / BLOCK
v
Razorpay Test Mode API (real sandbox call)
v
Outcome Engine
v
Audit Log (append-only — every step above writes here)


## Decisions log
| Day | Decision | Why | Alternative considered |
|---|---|---|---|
| 1 | Postgres via Neon, no migration tool yet | Free, instant branching; Alembic overhead isn't worth it for 7 days — reset via a fresh branch instead | Alembic migrations |
| 1 | SQLAlchemy 2.0 models, `create_all` via script | Fast to iterate on a hackathon timeline | Raw SQL migrations |
| 2 | `JSON().with_variant(JSONB, "postgresql")` instead of raw `JSONB` | Tests run on in-memory SQLite (no external DB needed for CI), prod on Neon still gets real JSONB indexing | Spin up a Postgres service container in CI |
| 2 | Ground truth lives in its own `ground_truth_labels` table, not columns on `Payment` | Keeps the "answer key" physically separate from what agents can see; makes the integrity rule ("agents never read this table") enforceable by convention and easy to audit | Add `is_recoverable` column directly to `Payment` |
| 2 | Ground truth generated with a fixed seed (42) and frozen once agent work starts | Reproducible eval numbers across Days 3–6; re-seeding mid-build silently invalidates every metric collected so far | Regenerate data fresh each day |
| 2 | Canonical action taxonomy fixed now: `retry_now`, `retry_later`, `send_payment_link`, `escalate_human`, `no_action` | Recovery Strategy Agent (Day 3) and ground truth must speak the same vocabulary, or precision/recall on Day 6 can't be computed | Let the LLM free-form the action and parse it later |
| 2 | 80/20 dev/holdout split assigned at generation time, stored per case | Standard eval hygiene — iterate against `dev`, report only against `holdout` once at the end, avoids unconsciously overfitting agent prompts to the numbers you're being judged on | Split randomly at evaluation time (no persisted assignment) |
| 3 | LLM circuit breaker tracked per *tier* ("gemini", "groq") shared across both agents, not per (agent, tier) pair | If Gemini is down, it's down for both agents equally — no reason to track root-cause's Gemini failures separately from strategy's | Independent breaker state per agent |
| 3 | Recovery Strategy Agent's confidence anchored to concrete category-based rules in the system prompt, not a vague "calibrate honestly" instruction | First calibration run showed the opposite of calibration — 82% of cases at 0.90+ confidence, and that bucket had the worst match rate of any bucket. Models default to reporting high confidence unless given concrete anchors for when *not* to | Post-hoc confidence rescaling fitted on top of raw model output |
| 3 | In-memory rate limiter on `/cases/{id}/analyze`, not Redis-backed despite Upstash Redis already being in the stack | Single-process demo deployment — good enough to stop a runaway loop burning quota mid-demo; a Redis-backed limiter is real work for a benefit that only matters with more than one server process | Upstash Redis-backed sliding window |
| 4 | Razorpay execution built on the Payment Links API, not a "retry the specific failed charge" API | Razorpay doesn't expose the latter; Payment Links is Razorpay's own recommended recovery path and produces a real, demoable artifact (a URL) | A custom simulated-retry against the Orders API |
| 4 | `Action.idempotency_key` reused as Razorpay's `reference_id` | Razorpay itself rejects a duplicate `reference_id`, so idempotency is enforced by Razorpay's API, not just an internal DB unique constraint | Generate a separate internal-only key, never send it to Razorpay |
| 4 | Global kill switch is a runtime-mutable settings singleton flag, flipped via `POST /admin/kill-switch`, not a persisted DB row | Zero schema/migration cost; same single-process assumption already used for the rate limiter and circuit breaker | A `kill_switches` table checked per-request |
| 4 | `app/rate_limit.py` rewritten to key its buckets instead of one shared global deque | Caught before shipping: adding the Razorpay execute endpoint on the same counter as `/analyze` would have let one endpoint silently drain the other's budget | A separate rate-limiter module per endpoint |

*(Add a row every day you make a real call — this is what you defend in the panel round.)*