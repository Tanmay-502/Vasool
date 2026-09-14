# Architecture — Vasool v3

## Core principle

> **AI proposes. Deterministic policy decides. Razorpay evidence proves recovery.**

Vasool separates probabilistic reasoning from safety-critical decisions and external payment evidence. No AI output directly moves money or counts revenue as recovered.

## End-to-end flow

```text
Failed payment
    │
    ▼
Background scheduler / operator
    │
    ▼
Root Cause Agent
(Gemini → Groq → rules fallback)
    │ structured diagnosis
    ▼
Recovery Strategy Agent
(Gemini → Groq → rules fallback)
    │ structured action + confidence
    ▼
Deterministic Policy Engine
    ├── kill switch
    ├── risk escalation
    ├── action taxonomy
    ├── consent / opt-out
    ├── confidence floor
    ├── amount ceiling
    └── retry ceiling
    │
    ├───────────────┐
    ▼               ▼
HUMAN_REVIEW     EXECUTE / SCHEDULE
    │               │
    │               ├── retry_later → persisted not_before
    │               │                 → scheduler executes when due
    │               │
    │               └── retry_now / payment link → Razorpay Test Mode
    │                                      │
    └──────────────────────────────────────┤
                                           ▼
                              Signed Razorpay webhook
                                           │
                                           ▼
                                  Verified Outcome
                                           │
                                           ▼
                                      Audit + Metrics
```

## Data boundaries

### Agent boundary
`app/agents/` can read payment/customer/order context and must not read `ground_truth_labels`. The syntax-tree integrity test continues to enforce this in CI.

### Policy boundary
`app/policy_engine.py` is a pure function with no database or network dependencies. It evaluates every configured gate on every request and returns `EXECUTE`, `HUMAN_REVIEW`, or `BLOCK`.

### Lifecycle boundary
`app/status.py` is the single source of truth for terminal recovery states. Analysis, policy evaluation, review, and execution reject terminal or already-paid cases. This prevents a curiosity click or a stale API client from reopening a recovered case.

### Execution boundary
`app/executor.py` is the only application path that calls the Razorpay client. It independently checks terminal state, executable action taxonomy, the persisted kill switch, and `Payment.status == "paid"` before the provider call. The paid check is deliberate defense in depth.

Execution idempotency is derived from the case and specific strategy decision. A successful retry returns the existing logical action rather than creating another Payment Link.

### Evidence boundary
`app/routers/webhooks.py` accepts Razorpay events only after HMAC-SHA256 verification over the raw request body. `X-Razorpay-Event-Id` is used to deduplicate events. `payment_link.paid` is authoritative for verified recovery; Payment Link creation alone never counts as recovered revenue.

Paid state is monotonic: a later cancellation/expiry event cannot downgrade a case already verified as paid.

## Persistence model

```text
Merchant
  └── Customer
  └── Order
       └── Payment
            └── RecoveryCase
                 ├── AgentDecision
                 ├── PolicyCheck
                 ├── Action (including not_before for delayed retry)
                 ├── Outcome
                 └── AuditLog

RuntimeSetting
  └── persisted global kill-switch state

GroundTruth
  └── separate evaluation-only answer key
```

The v3 runtime setting survives process restarts. An environment-level `KILL_SWITCH_ENGAGED=true` remains an emergency floor and cannot be cleared by the runtime API.

## Human review contract

`POST /cases/{id}/review` is intentionally narrower than a generic admin override:

- `reject` is terminal for that recovery attempt.
- `approve` can move only `HUMAN_REVIEW` → `pending_execution`.
- Approval is blocked while the persisted kill switch is engaged.
- Approval cannot bypass hard consent or invalid-action gates.
- Every review decision is appended to `AuditLog`.

## Authentication contract

State-changing endpoints require `X-API-Key` or `Authorization: Bearer <key>` outside development/test:

- `/admin/kill-switch/*`
- `POST /cases/{id}/analyze`
- `POST /cases/{id}/evaluate-policy`
- `POST /cases/{id}/review`
- `POST /cases/{id}/execute`

Read-only dashboard surfaces remain public. The browser demo can supply `NEXT_PUBLIC_VASOOL_API_KEY`, but that shared key is deliberately documented as demo-only; a real multi-user deployment should use a proper identity/session layer.

## Metrics contract

Operational metrics use `Outcome` for recovered revenue. Revenue-at-risk is scoped to distinct failed orders, preventing multiple failed payment rows for one order from double-counting historical exposure. Model-evaluation metrics remain separate from operational state and never feed decisions.

## Autonomous processing

`app/scheduler.py` is a lightweight background loop started by FastAPI lifespan. It:

1. Finds newly `detected` cases and runs analyze → policy on its own.
2. Finds due `scheduled` actions and calls the same execution boundary.
3. Re-checks the persisted kill switch before sweeps and relies on execution-time safety checks before provider calls.

The scheduler is intentionally simple. It is safe for the single-process deployment shape used by the project, but a multi-replica production deployment should add a distributed lease/leader election so two instances cannot sweep the same work simultaneously.

## Failure containment

- LLM provider failure → fallback chain.
- Repeated provider failure → circuit breaker.
- Runaway requests → process-local rate limits.
- Unsafe policy state → human review or block.
- Restart-safe automation pause → database-backed kill switch.
- Duplicate client execution → deterministic idempotency key.
- Duplicate webhook event → event-id deduplication.
- Out-of-order terminal webhook → monotonic paid state.
- Delayed retry → database-persisted `not_before` timestamp.
- Malformed AI output → schema validation + fallback.

## Operational limitations

The rate limiter and circuit breaker are still process-local and therefore reset on process restart. A multi-instance deployment should move those controls to shared storage. The in-process scheduler likewise needs a distributed lease for horizontal scaling.

The API-key layer protects the mutation surface but is not a full identity/authorization system. Do not treat the demo configuration as sufficient for real-money production.

## Security posture

Production API docs `/docs` and `/redoc` are disabled outside development/test. Production CORS should be an explicit comma-separated allowlist, not `*`. Keep `.env` and `.env.local` outside source control and rotate any exposed credential.
