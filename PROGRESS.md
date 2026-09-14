# Build log — Vasool

## Baseline — what the original submission established
The original implementation already had a strong safety-first backend: structured Gemini/Groq output, deterministic fallback, confidence calibration, a pure policy engine, circuit breakers, rate limits, Test Mode execution, idempotency, audit logging, and reproducible holdout evaluation.

The main v1 weakness was completion of the business loop: the project could create a recovery action, but the dashboard and backend did not yet turn a successful customer payment into a verified `Outcome`. The frontend also buried the core story under too many implementation surfaces.

## V2 hardening — competition-ready rebuild ✅

### Product loop ✅
- [x] Explicit end-to-end state model: failed payment → diagnose → recommend → policy → human/execute → verify → audit.
- [x] Razorpay signed webhook ingestion for `payment_link.paid`, `payment_link.partially_paid`, `payment_link.cancelled`, and `payment_link.expired`.
- [x] Verified payment updates `Action`, `RecoveryCase`, `Payment`, `Order`, and `Outcome`.
- [x] Recovery is credited only from trusted webhook evidence; Payment Link creation alone never counts as recovered revenue.
- [x] Paid state is monotonic against late expiry/cancellation events.

### Execution safety ✅
- [x] Stable execution idempotency key derived from case + strategy decision.
- [x] Client retry after a successful Test Mode call returns the existing action instead of creating a second Payment Link.
- [x] Kill switch is checked again at the execution boundary, not only during policy evaluation.
- [x] Non-executable strategies are rejected at execution time even if a caller bypasses the UI.
- [x] Failed outbound attempts remain retryable while preserving the same logical action/reference.

### Human review ✅
- [x] `POST /cases/{id}/review` with approve/reject decisions.
- [x] Approval is blocked while kill switch is engaged.
- [x] Approval cannot bypass hard `opt_out` or invalid-action gates.
- [x] Review decisions are appended to the audit ledger.
- [x] Frontend exposes operator-friendly Approve / Reject controls.

### Metrics ✅
- [x] Historical revenue-at-risk denominator stays stable after successful recovery.
- [x] Verified and partial recovery amounts are included in recovered revenue.
- [x] Dashboard receives resolved, partially recovered, and executed counts.
- [x] Ground-truth recoverable percentage is calculated against labeled cases rather than a mutable payment-status denominator.

### Frontend ✅
- [x] Rebuilt as a responsive recovery command center rather than a collection of dense cards.
- [x] Clear financial headline: revenue at risk, verified recovered revenue, recovery rate, and review queue.
- [x] Search and status filters for the case queue.
- [x] Per-case AI diagnosis, recommended action, confidence/model metadata, context, policy checks, action status, payment link, and verified outcome.
- [x] Human review controls and explicit Test Mode confirmation.
- [x] Kill-switch state is visible globally and locally.
- [x] Loading skeletons, connection state, partial-refresh errors, retry/refresh controls, mobile navigation, and 30-second polling.
- [x] Reduced-motion and keyboard focus support retained.

### CI / security ✅
- [x] Backend and frontend split into separate CI jobs.
- [x] Backend unit/integration suite passes in CI.
- [x] Frontend `npm ci`, production dependency audit, TypeScript typecheck, ESLint, and production build run in CI.
- [x] Frontend dependency lockfile regenerated after security upgrade.
- [x] Next.js patched to the current branch target used by the rebuild and `sharp` pinned to a non-vulnerable release through an override.
- [x] GitHub Actions migrated to current checkout/setup-node action majors used by the rebuild, with Node 22 for the frontend runtime.
- [x] FastAPI startup diagnostics migrated to the lifespan API.

### Regression coverage ✅
- [x] Signed webhook tests: valid signature, invalid signature, missing event id.
- [x] Webhook tests: paid, partial, unmatched link, duplicate event, and late terminal event ordering.
- [x] Human-review tests: approve, reject, invalid action, hard consent gate, kill switch.
- [x] Execution safety tests: kill switch, successful idempotent replay, failed retry.
- [x] Metrics tests: stable denominator, recovered amount, empty database behavior.
- [x] Existing 139+ test baseline remains green after V2 changes; CI is the source of truth for the current branch.

## Known limitations / honest status
- [ ] A real Razorpay Test Mode payment has to be completed once in the deployed environment so the live webhook path can be validated end to end. The code and tests cover the lifecycle, but repository inspection cannot prove a real external payment was completed.
- [ ] Live LLM quotas remain an infrastructure constraint. Holdout evaluation should be reported with clear tier-usage breakdown rather than implying all cases used a live model.
- [ ] LangGraph/WebSocket orchestration remains intentionally out of the critical path; the explicit pipeline is easier to test and defend. Add only when it improves judge-visible value.
- [ ] Production authentication/authorization for operator endpoints is outside the public demo scope and should be added before any real-money deployment.

## Day 7 / final competition pass
- [x] Competition-ready command-center frontend
- [x] Verified outcome loop in backend
- [x] Human review workflow
- [x] Hardened execution idempotency
- [x] Security and CI hardening
- [ ] Final 5-minute pitch recording
- [ ] Final full live demo dry run with one curated Test Mode case
