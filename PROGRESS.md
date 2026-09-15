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

## V4 — scheduler, auth, caller isolation, and console hardening

### Implemented ✅
- [x] Moved the synchronous scheduler sweep behind `asyncio.to_thread()` so a long agent/provider/DB sweep no longer occupies the FastAPI event loop.
- [x] Added a scheduler concurrency regression test and a local pre-fix/post-fix timing verification.
- [x] Added a production startup warning when `ENV=production` but `VASOOL_API_KEY` is empty.
- [x] Scoped analyze and Razorpay limiter buckets by API key, with production IP fallback and existing `default` behavior preserved for development/test.
- [x] Added caller-isolation rate-limit regression coverage.
- [x] Added Vitest + React Testing Library coverage for the active `VasoolConsole`, including analyze → review → execute, kill-switch-disabled mutation controls, and terminal-state mutation hiding.
- [x] Tightened the manual holdout defaults to 0.60 precision / 0.90 recall and made pass/fail visible in the GitHub Actions job summary even when the job remains non-blocking.

### Verified ✅
- [x] Remote branch tree contains only `VasoolConsole.tsx` under `frontend/src/components`; the eight previously orphaned component filenames are absent.
- [x] GitHub commit comparison from the current `main` tip shows no changes to `backend/app/agents/*` or `backend/scripts/shadow_backtest.py`.
- [x] `backend/scripts/shadow_backtest.py` remains unchanged by this pass; no committed shadow case fixture exists in the repository to diff.
- [x] Scheduler timing reproduction: pre-fix health latency ~1.00s while the sweep blocked the loop; post-fix health latency ~0.002s with the same 1s blocking workload moved to a thread.

### Not verified in this environment ⚠️
- [ ] A literal `grep -r` could not be executed against a local Git clone because this environment cannot resolve `github.com`; the remote repository tree and component directory were checked directly instead.
- [ ] The full pytest/Vitest suite still needs the CI run on this branch for final green status.
- [ ] The real live Render deployment auth behavior can only be verified against the deployed URL with `ENV=production` and a configured `VASOOL_API_KEY`.
- [ ] A real Razorpay Test Mode payment/webhook round-trip remains unperformed.

### Open limitations
- [ ] Rate limiter and circuit breaker remain process-local/in-memory.
- [ ] The scheduler remains single-process and has no distributed lease for horizontal scaling.
- [ ] The browser API-key model remains demo-oriented rather than a full identity/authorization system.

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
