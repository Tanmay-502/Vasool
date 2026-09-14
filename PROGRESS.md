# Build log — Vasool

## Baseline
The original implementation already had a strong safety-first backend: structured Gemini/Groq output, deterministic fallback, confidence calibration, a pure policy engine, circuit breakers, rate limits, Test Mode execution, idempotency, audit logging, and reproducible holdout evaluation.

## V2 — competition-ready rebuild ✅

The competition branch completed the verified recovery loop: failed payment → diagnosis → strategy → deterministic policy → human review or Test Mode execution → signed Razorpay webhook → verified Outcome → audit and metrics.

## V3 — hardened / future-use pass ✅

### 1. Terminal-state safety ✅
- [x] Added a single canonical `TERMINAL_STATUSES` set.
- [x] Force re-analysis of resolved/executed/partial/rejected/cancelled/expired cases is rejected with HTTP 409.
- [x] Policy evaluation rejects terminal or already-paid cases.
- [x] Execution rejects terminal or already-paid cases before any Razorpay call.
- [x] Added a second paid-state check immediately before the outbound provider call as defense in depth.
- [x] Existing deterministic idempotency remains intact.

The browser's normal Analyze request no longer forces re-analysis. The dedicated `reanalyzeCase` API function exists for an explicit operator action, while terminal states are still blocked by the backend.

### 2. State-changing authentication ✅
- [x] Added API-key / Bearer-token dependency to analyze, evaluate-policy, review, execute, and kill-switch mutation endpoints.
- [x] GET monitoring endpoints remain public for the dashboard.
- [x] Development/test environments can run without a configured key to preserve local ergonomics.
- [x] Production requires `VASOOL_API_KEY` to be configured.

### 3. Restart-safe operational state ✅
- [x] Added database-backed `RuntimeSetting` for the kill switch.
- [x] Runtime pause/resume survives FastAPI/Render process restarts.
- [x] `KILL_SWITCH_ENGAGED=true` remains a startup emergency floor.
- [x] Rate limiter and circuit breaker remain process-local and are documented as scaling limitations.

### 4. Metrics correctness ✅
- [x] Revenue-at-risk now aggregates a distinct failed-order scope rather than payment rows.
- [x] Failure-reason exposure uses the same distinct-order scope.
- [x] Added a regression test with multiple failed payment attempts on one order.

### 5. Real delayed retry semantics ✅
- [x] Added `Action.not_before`.
- [x] `retry_later` creates a persisted scheduled action instead of calling Razorpay immediately.
- [x] Scheduler executes due scheduled actions through the same execution boundary.
- [x] Delay is configurable through `RETRY_LATER_DELAY_MINUTES`.

### 6. Autonomous processing ✅
- [x] Added a lightweight FastAPI-lifespan background scheduler.
- [x] Newly detected cases are automatically analyzed and policy-evaluated.
- [x] Due scheduled retries are automatically executed.
- [x] Scheduler respects the persisted kill switch and execution-time backstops.
- [x] Scheduler work is bounded per sweep to reduce runaway behavior.

### 7. Frontend cleanup ✅
- [x] Removed the eight orphaned v2 component files that were not imported by the active command center.
- [x] Kept the active experience consolidated in `VasoolConsole.tsx`.

### 8. Frontend regression tests ✅
- [x] Added a dependency-free Node test suite for status/action gating and terminal-state re-analysis rules.
- [x] Wired `npm test` into the main frontend CI job.

### 9. Holdout quality gate ✅
- [x] Added a manual GitHub Actions holdout workflow with configurable precision/recall floors.
- [x] The workflow evaluates the frozen holdout split and fails its internal quality gate when floors are missed.
- [x] The workflow is intentionally non-blocking initially (`continue-on-error: true`) because it requires a configured evaluation database and live model credentials.
- [x] Existing frozen shadow results remain documented separately; future evaluations must not imply that a live LLM was used for every case when quota/fallback tiers were active.

### 10. Security hygiene ✅
- [x] `/docs` and `/redoc` are disabled outside development/test.
- [x] Production CORS is documented as an explicit allowlist rather than a wildcard.
- [x] Added backend and frontend environment examples for API authentication and scheduler controls.
- [x] Documented demo API-key limitations and the need for a real identity/session system before production money movement.

## Tests added in V3
- [x] terminal policy evaluation rejection
- [x] paid execution rejection before Razorpay
- [x] terminal force-analysis rejection
- [x] duplicate failed-payment rows do not duplicate operational revenue risk
- [x] `retry_later` schedules instead of calling Razorpay immediately
- [x] frontend status/action-gating regression tests

## Honest validation boundary
- [ ] A real Razorpay Test Mode payment and external webhook round-trip has not been claimed here. The repository contains automated/provider-simulated coverage; an actual external transaction must be performed and recorded separately.
- [ ] A distributed deployment still needs shared rate-limit/circuit state and a distributed scheduler lease to prevent duplicate sweeps across replicas.
- [ ] The browser API-key approach is demo-friendly, not a replacement for user identity and authorization.

## Final state for this branch
- [x] Work based on `main` after the competition-ready merge
- [x] Safety-critical terminal/paid backstops hardened
- [x] State-changing endpoints authenticated
- [x] Kill switch persisted
- [x] Metrics double-counting risk removed
- [x] Delayed retries implemented
- [x] Automatic first-contact processing implemented
- [x] Orphaned frontend files removed
- [x] Frontend regression suite added
- [x] Manual holdout quality gate added
- [x] Documentation updated
- [ ] Live external Razorpay Test Mode round-trip
