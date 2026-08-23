# Build log — Vasool

## Day 1 — Foundation ✅
- [x] Schema (10 tables) defined in `models.py`
- [x] FastAPI skeleton, `/health` test passes
- [x] CI running on push
- [x] Neon DB created, tables created via `init_db.py`
- [x] Razorpay test keys + Gemini + Groq keys obtained

## Day 2 — Synthetic data + revenue intelligence ✅
- [x] Transaction generator, ~1,500 records (`scripts/generate_synthetic_data.py`)
- [x] 80/20 split, ground-truth labels frozen (seed=42, `ground_truth_labels` table)
- [x] `/metrics` endpoint — no LLM involved
- [x] Fixed a landmine before it hit CI: `JSONB` columns are Postgres-only and
      fail to compile on SQLite. Switched to `JSON().with_variant(JSONB,
      "postgresql")` so tests run on in-memory SQLite (fast, zero external
      deps) while prod on Neon still gets real JSONB. Added `tests/conftest.py`
      with a shared SQLite fixture + `get_db` dependency override.

## Day 2.5 — Hardening before Day 3 starts ✅
Caught by re-checking Day 2 output against the actual generated dataset,
not just the code that produces it — four fields existed in the schema or
the generator's own logic but were never actually exercised:
- [x] `Payment.attempt_number` now varies (55% / 30% / 15% across 1/2/3)
      instead of being hardcoded to 1 on every row. This makes the
      diminishing-returns decay already written and unit-tested in
      `compute_ground_truth()` actually affect the frozen dataset.
- [x] `Customer.opted_out` now has a real ~7% cohort instead of being `False`
      for all 500 customers — gives the Day 4 policy engine (and the Day 6
      "policy correctly blocked a bad call" scenario) real cases to catch.
- [x] `AgentDecision.tokens_used` / `latency_ms` columns added — Day 3's
      planned per-call cost/latency logging now has somewhere to write to.
- [x] `Action.idempotency_key` added (auto-generated, unique, client-side
      default) — verified it actually blocks a duplicate key at the DB
      level, not just that the column exists.
- [x] Golden-snapshot regression test (`test_golden_snapshot_seed_42_count_1500`)
      locks in the exact stats of the frozen dataset — 506 failed payments,
      258 recoverable, 404/102 dev/holdout split, {1: 296, 2: 136, 3: 74}
      attempt distribution — so a future accidental change to the RNG
      stream fails CI loudly instead of silently invalidating every eval
      number.
- [x] All 10 tests pass; regenerated the real 1,500-row dataset and
      confirmed both previously-dead fields now vary in the actual output,
      not just in theory.

**Action for you:** since there's no Alembic yet, these are new columns —
wipe your local/dev table state (or cut a fresh Neon branch) and re-run
`python -m scripts.init_db`, then `python -m scripts.generate_synthetic_data --reset`
to get a frozen dataset that actually has these fixes baked in.

## Day 3 — Root Cause + Strategy agents
- [ ] Both agents return structured JSON (Gemini -> Groq -> rules fallback)
- [ ] Fallback chain tested by forcing a failure at each tier
- [ ] **Cost/latency logging per agent call** — `model_used`, tokens, ms, on
      `AgentDecision`. Judges notice when you can say "this cost ₹0.0004 and
      380ms per decision" instead of just "we used an LLM."
- [ ] **Confidence must be calibrated, not decorative** — a case with 0.55
      confidence should genuinely be worse than one at 0.95. Spot-check this
      against the `dev` split before trusting it downstream.
- [ ] Frontend track kicks off in parallel (doesn't block agent work):
      Next.js + TypeScript + Tailwind + shadcn/ui + Recharts, deployed to
      Vercel from day 1 so there's always a live URL, not just localhost.

## Day 4 — Policy engine + Razorpay execution
- [ ] Policy engine unit-tested, zero LLM inside
- [ ] Real Razorpay Test Mode call wired to EXECUTE
- [ ] Every decision + API call in `audit_log`
- [ ] **Idempotency key on every Action** before it touches Razorpay — a
      retried request or a double-click must never double-charge or
      double-send. This is the single most common way a "money agent" demo
      goes visibly wrong in front of judges.
- [ ] **Global kill switch** — one flag/endpoint that halts all auto-execution
      and drops everything to HUMAN_REVIEW. Costs almost nothing to build,
      and directly answers the safety question every judge asks a team
      touching real payments.
- [ ] **Rate limit / circuit breaker** on outbound Razorpay calls so a bad
      loop can't hammer the API mid-demo.

## Day 5 — Orchestration + dashboard
- [ ] LangGraph pipeline end to end
- [ ] Command-center + case explorer UI
- [ ] **Live case feed** (WebSocket/SSE) — cases visibly moving through
      detected → analyzed → policy-checked → executed → resolved as the
      pipeline runs. This is the single highest-leverage visual for a demo:
      judges *watch* the agent work instead of reading a static table.
- [ ] **Explainability panel per case** — root cause, chosen strategy, the
      policy checks that passed/failed (green/red chips), and the model's
      stated reasoning, all in one click. Directly answers "why did it do
      that?" before anyone has to ask.
- [ ] **Human review queue** with approve/reject buttons that write back into
      the pipeline — demonstrates the "compliant escalation" language from
      the PRD isn't just a slide, it's a working control.
- [ ] Big top-line numbers matching the PRD metrics exactly: ₹ at risk vs ₹
      recovered, precision/recall, false-positive cost, % escalated.

## Day 6 — Evaluation + failure lab
- [ ] Metrics reproducible via one script, run **only against the `holdout`
      split** (the `dev` split was for iterating, this is the number you
      actually report)
- [ ] Precision/recall vs `ground_truth_labels`, false-positive cost, %
      correctly escalated — pull straight from the schema built on Day 2
- [ ] 3 failure scenarios documented
- [ ] **A 4th "failure" scenario that's actually a save**: show one case
      where the policy engine correctly blocked an LLM's bad call. Proves
      the guardrail layer isn't decorative.
- [ ] **Shadow-mode backtest**: replay the full synthetic dataset with
      execution disabled, log what *would* have happened. Cheap to build
      since Day 2 already gives you labeled data to replay against.

## Day 7 — Pitch + dry run
- [ ] 5-minute pitch recorded
- [ ] Full live demo dry run
- [ ] **Seeded demo dataset frozen the night before** — don't regenerate
      data or re-run migrations the morning of the pitch. A live Wi-Fi
      hiccup shouldn't be able to break the story.
- [ ] Deployed URLs (backend + frontend) in the README, not just
      instructions to run locally — judges who can click a link before the
      pitch starts form an impression before you say a word.