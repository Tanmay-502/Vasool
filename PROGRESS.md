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