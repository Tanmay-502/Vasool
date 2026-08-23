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

*(Add a row every day you make a real call — this is what you defend in the panel round.)*