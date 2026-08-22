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

*(Add a row every day you make a real call — this is what you defend in the panel round.)*