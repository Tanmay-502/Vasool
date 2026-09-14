# Architecture — Vasool v2

## Core principle

> **AI proposes. Deterministic policy decides. Razorpay evidence proves recovery.**

Vasool separates probabilistic reasoning from safety-critical decisions and from external payment evidence. No AI output directly moves money or counts revenue as recovered.

## End-to-end flow

```text
Payment fails
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
HUMAN_REVIEW     EXECUTE
    │               │
    │               ▼
    │         Razorpay Test Mode
    │               │
    │               ▼
    │          Payment Link
    │               │
    │               ▼
    │        Signed Razorpay webhook
    │               │
    └───────────────┤
                    ▼
             Verified Outcome
                    │
                    ▼
               Audit + Metrics
```

## Data boundaries

### Agent boundary
`app/agents/` can read payment/customer/order context and must not read `ground_truth_labels`. A syntax-tree integrity test enforces the rule in CI.

### Policy boundary
`app/policy_engine.py` is a pure function with no database or network dependencies. It evaluates every configured gate on every request and returns `EXECUTE`, `HUMAN_REVIEW`, or `BLOCK`.

### Execution boundary
`app/executor.py` is the only application path that calls the Razorpay client. It independently checks executable action taxonomy and the kill switch before any outbound call.

The logical execution idempotency key is derived from the recovery case and the specific strategy decision. A client retry after a successful call therefore resolves to the existing `Action` rather than creating a second Payment Link.

### Evidence boundary
`app/routers/webhooks.py` accepts Razorpay events only after HMAC-SHA256 verification over the raw request body. `X-Razorpay-Event-Id` is used to deduplicate events. `payment_link.paid` is the authority for a verified recovery; Payment Link creation alone is never treated as recovered revenue.

Paid state is monotonic: a later cancellation/expiry event cannot downgrade a case that was already verified as paid.

## Persistence model

```text
Merchant
  └── Customer
  └── Order
       └── Payment
            └── RecoveryCase
                 ├── AgentDecision (AI evidence)
                 ├── PolicyCheck  (deterministic evidence)
                 ├── Action       (outbound execution)
                 ├── Outcome      (trusted recovery result)
                 └── AuditLog     (operational timeline)

GroundTruth
  └── separate evaluation-only answer key
```

The separation lets the evaluator score decisions after the fact while keeping the decision-making path blind to the answer key.

## Human review contract

`POST /cases/{id}/review` is intentionally narrower than a generic admin override:

- `reject` is terminal for that recovery attempt.
- `approve` can move only `HUMAN_REVIEW` → `pending_execution`.
- Approval is blocked while the global kill switch is engaged.
- Approval cannot bypass hard consent or invalid-action gates.
- Every review decision is appended to `AuditLog`.

## Metrics contract

`/metrics` reports two different classes of truth:

1. **Operational recovery truth:** revenue at risk, verified recovered amount, recovery rate, resolved/partial/executed counts. Recovered revenue comes from `Outcome` rows.
2. **Model-evaluation truth:** ground-truth recoverable counts and offline evaluation scripts. These numbers do not feed operational decisions.

Revenue-at-risk is a historical denominator over failed/recovery-scope payments so successful recovery does not make the denominator disappear.

## Failure containment

- LLM provider failure → fallback chain.
- Repeated provider failure → circuit breaker.
- Runaway requests → per-endpoint rate limits.
- Unsafe policy state → human review or block.
- Kill switch → outbound automation paused.
- Duplicate client execution → deterministic idempotency key.
- Duplicate webhook event → event-id deduplication.
- Out-of-order terminal webhook → monotonic paid state.
- Malformed AI output → schema validation + fallback.

## Deliberate trade-offs

| Decision | Rationale |
|---|---|
| Explicit Python pipeline instead of LangGraph | Easier to test, inspect, and defend; orchestration is not on the critical safety path. |
| Postgres/Neon + SQLAlchemy | Real relational constraints and JSON-capable decision storage while still supporting fast SQLite CI tests. |
| Razorpay Payment Links for recovery | Produces a concrete customer-facing recovery artifact instead of pretending a failed charge itself can be retried through a nonexistent API. |
| Test Mode execution behind explicit UI action | Prevents demo rehearsal from accidentally creating outbound payment artifacts. |
| Webhook-backed Outcome | Prevents the dashboard from claiming money was recovered when only a link was generated. |

## Security posture

The repository does not contain application secrets. Production secrets are injected through environment variables. The frontend never receives the Razorpay webhook secret. Operator/admin endpoints remain a demo-scope boundary and should receive authentication and authorization before any real-money deployment.
