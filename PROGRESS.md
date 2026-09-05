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

## Day 3 — Root Cause + Strategy agents ✅
- [x] Both agents return structured JSON (Gemini -> Groq -> rules fallback)
      — `root_cause_agent.py` / `recovery_strategy_agent.py`, three tiers,
      output validated against Pydantic schemas (`app/agents/schemas.py`)
      so a malformed or off-taxonomy response trips the fallback instead
      of crashing.
- [x] Fallback chain tested by forcing a failure at each tier
      (`tests/test_agents_fallback.py` — fakes both clients directly, no
      real network calls, no API keys needed to run in CI).
- [x] **Cost/latency logging per agent call** — `model_used`, `tokens_used`,
      `latency_ms` written on every `AgentDecision` row
      (`app/agents/pipeline.py`).
- [x] **Confidence must be calibrated, not decorative.** First calibration
      pass (`scripts/calibrate_confidence.py --all`) exposed the opposite
      of calibration: 82% of dev-split cases landed in the 0.90+ bucket,
      and that bucket had the *worst* match rate of the three (~30%) —
      confidence wasn't tracking correctness at all. Root cause: the
      Recovery Strategy Agent's system prompt only said "calibrate
      confidence to how certain the context genuinely makes you" — a
      vibe, not an instruction a model reliably follows. Rewrote the
      prompt with concrete anchors (0.85+ only for genuinely unambiguous
      cases — risk_flagged, or a first-attempt transient failure; 0.55–0.80
      for real judgment calls like card_declined or any repeat attempt;
      below 0.55 for weak/conflicting signal). Two independent post-fix
      runs confirm it held:
      | n | 0.90+ | 0.75–0.89 | 0.60–0.74 | <0.60 |
      |---|---|---|---|---|
      | 40 | 100.0% | 53.8% | 15.4% | — |
      | 150 | 100.0% | 58.8% | 33.3% | 29.1% |
      Match rate strictly decreases as the confidence bucket decreases in
      both runs — the property this checklist item originally asked for
      ("0.95 confidence should genuinely beat 0.55"), now actually true
      and verified twice, not assumed.
- [x] Frontend track (Next.js + TypeScript + Tailwind) — dashboard, case
      explorer, explainability panel, audit ledger, and safety controls are
      shipped. Deployment remains environment-specific.

**Extra hardening added beyond the original Day 3 scope**, same spirit as
Day 2.5 — found by actually running the pipeline under real failure
conditions today, not just reading the code:
- [x] **Circuit breaker on both LLM tiers** (`app/agents/circuit_breaker.py`)
      — after 3 failures within 60s, a tier is skipped entirely (no network
      call attempted) until cooldown. Without this, an outage mid-demo
      means every case eats a full 12s timeout before falling through.
      Verified for real today, not just in unit tests: Gemini 429s and a
      separate Groq daily-quota exhaustion both tripped the breaker
      correctly and independently, and every single case still produced a
      decision via the next tier down (or `rules_fallback` when both LLM
      tiers were open at once).
- [x] **Rate limit on `POST /cases/{id}/analyze`** (`app/rate_limit.py`)
      — 20 calls/minute, in-memory sliding window. Stops a runaway loop or
      double-click storm from burning LLM quota mid-demo.
- [x] **409 on re-analyzing an already-analyzed case**, with a
      `?force=true` escape hatch — prevents silently piling up duplicate
      `AgentDecision` rows for the same case on accidental re-calls.

**Known limitation, not urgent:** Groq's free-tier daily token budget
(200k TPD on `openai/gpt-oss-120b`) is easy to exhaust running repeated
calibration batches back-to-back — hit it twice today. Not a code problem;
just a real constraint to budget testing volume around before demo day.

## Day 4 — Policy engine + Razorpay execution ✅
- [x] **Policy engine, zero LLM inside** (`app/policy_engine.py`) — pure
      function, 7 deterministic guardrails (kill switch, risk_flagged
      escalation, action type, opt-out, confidence floor, amount ceiling,
      retry ceiling), every check evaluated and recorded every time
      regardless of which one decided the verdict. 15 unit tests.
- [x] **Wired to real cases** (`app/policy_runner.py`) — reads the latest
      `recovery_strategy_agent` / `root_cause_agent` decisions, writes one
      `PolicyCheck` row per check, sets `case.status` to
      `pending_execution` / `human_review` / `blocked`.
- [x] **Real Razorpay Test Mode call wired to EXECUTE** (`app/executor.py`,
      `app/razorpay_client.py`) — Payment Links API, confirmed against
      current Razorpay docs. `retry_now` / `retry_later` / `send_payment_link`
      all call the same endpoint; only `notify` (does Razorpay itself
      email/SMS the customer) differs.
- [x] **Idempotency key on every Action before it touches Razorpay** —
      `Action.idempotency_key` (already existed since Day 2.5) is generated
      once at object-creation time and reused as Razorpay's own
      `reference_id`, which Razorpay itself rejects as a duplicate if
      reused — idempotency enforced by Razorpay's API, not just an internal
      constraint.
- [x] **Global kill switch** — `settings.KILL_SWITCH_ENGAGED`, flipped at
      runtime via `POST /admin/kill-switch/engage|disengage`, no redeploy.
      Checked first in `evaluate_policy()`, short-circuits every other
      guardrail to `HUMAN_REVIEW`.
- [x] **Rate limit + circuit breaker on outbound Razorpay calls** — reused
      `app/agents/circuit_breaker.py`'s tier logic as-is (tier name
      `"razorpay"`); rate limiter caught a real bug before shipping (see
      below) and was fixed instead of just extended.
- [x] Every execution attempt writes to `audit_log`
      (`execution_started` / `execution_succeeded` / `execution_failed`),
      alongside the existing `AgentDecision` and `PolicyCheck` tables — the
      full "why did it do that" trail is deliberately split across three
      tables by concern (agent reasoning / guardrail results / outbound-call
      lifecycle), all queryable per case.

**Bug caught before it shipped:** `app/rate_limit.py` was a single global
deque shared by every caller. Adding the Razorpay execution endpoint on
that same counter would have meant analyzing cases silently ate into the
execution budget and vice versa. Rewrote it to key its buckets
(`key="default"` for `/analyze`, `key="razorpay_execute"` for `/execute`) —
existing call sites needed zero changes, new ones get an independent window.

**Known limitations, flagged not fixed:**
- Razorpay Test Mode caps **30 Payment Links per business**. The synthetic
  dataset has 500+ failed payments — do not batch-execute against it. Pick
  a small curated set for the actual demo; shadow-mode the rest (Day 6).
- Outcome tracking (did the customer actually pay via the link) needs a
  webhook listener or manual reconciliation — not built yet, deliberately
  deferred to Day 5/6, not silently skipped.
- The executor is unit-tested against a fake Razorpay client — the request
  shape matches current docs, but a real end-to-end call with real Test
  Mode keys hasn't been made yet. Do that once before demo day rather
  than assume it works.

All 83 tests passing (`pytest -q` from `backend/`).

## Day 5 — Orchestration + dashboard ✅
- [x] Command-center + interactive case explorer UI
- [x] **Explainability panel per case** — root cause, chosen strategy, the
      policy checks that passed/failed, and model reasoning in one click.
- [x] **Safety-first demo flow** — analyzes and evaluates policy without
      executing a payment or spending Razorpay quota.
- [x] Runtime kill-switch control with confirmation and visible errors.
- [ ] LangGraph pipeline end to end — current pipeline is intentionally
      explicit and testable; orchestration can be added without changing the
      policy contract.
- [ ] **Live case feed** (WebSocket/SSE) — cases visibly moving through
      detected → analyzed → policy-checked → executed → resolved as the
      pipeline runs.
- [ ] **Human review queue** with approve/reject buttons that write back into
      the pipeline — demonstrates the "compliant escalation" language from
      the PRD isn't just a slide, it's a working control.
- [ ] Big top-line numbers matching the PRD metrics exactly: ₹ at risk vs ₹
      recovered, precision/recall, false-positive cost, % escalated.

## Day 6 — Evaluation + failure lab ✅ (with known quota caveat)
- [x] Reproducible eval script (`scripts/evaluate_holdout.py`) — holdout split only, shadow mode
- [x] Shadow-mode full-dataset backtest (`scripts/shadow_backtest.py`) — accumulates across
      quota-limited runs, checkpointed to `reports/shadow_backtest_cases.json`
- [x] 3 failure scenarios + 1 policy-save scenario documented — see `FAILURE_SCENARIOS.md`
- [x] Precision/recall/false-positive-cost/escalation-% computed against `ground_truth_labels`
- [!] **Known caveat, disclosed not hidden:** the holdout run reported here was degraded by
      Gemini + Groq free-tier quota exhaustion mid-run (~54% of cases fell to `rules_fallback`
      instead of the tuned LLM tiers). Two earlier calibration runs with live LLM access show
      the tuned agents hit strict confidence-to-match-rate monotonicity — this is a quota
      artifact, not a model-quality finding. See `FAILURE_SCENARIOS.md` #1.

## Day 7 — Pitch + dry run
- [ ] 5-minute pitch recorded
- [ ] Full live demo dry run
- [ ] Deployed URLs in README (backend + frontend)
