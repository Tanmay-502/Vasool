# Vasool

> **AI-assisted revenue recovery for failed payments, with deterministic policy, human control, and verified outcomes.**

Vasool turns a failed payment into an explainable recovery workflow:

**detect → diagnose → recommend → policy-gate → execute → verify → audit**

Built for the Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery.

## Live surfaces

| Surface | Link |
|---|---|
| **Dashboard** | [vasool-two.vercel.app](https://vasool-two.vercel.app/) |
| **Backend health** | [vasool-ta24.onrender.com/health](https://vasool-ta24.onrender.com/health) |
| **API docs** | Development/test only; disabled in non-development environments |

The UI is safe to rehearse: analysis and policy evaluation do not touch Razorpay. Test Mode execution is a separate, explicit operator action and can only run after the policy boundary permits it.

## The product loop

```text
Failed payment
      ↓
Root Cause Agent
      ↓
Recovery Strategy Agent
      ↓
Deterministic Policy Engine
   ↙              ↘
Human review     Test Mode execution
                    ↓
              Razorpay Payment Link
                    ↓
          Signed webhook verification
                    ↓
              Verified Outcome
                    ↓
              Recovery metrics
                    ↓
                 Audit log
```

The important product boundary is deliberate: **AI proposes; deterministic policy decides; Razorpay webhook evidence decides whether revenue was actually recovered.**

## What a reviewer can verify quickly

1. Open the dashboard and see revenue at risk, verified recovery, recovery rate, review queue, safety posture, and recent audit events.
2. Open a case to inspect the failure, AI root cause, recommended action, confidence/model metadata, and every policy gate.
3. For a `HUMAN_REVIEW` case, approve or reject it. Approval never bypasses hard consent/action gates and is paused while the global kill switch is engaged.
4. For a `pending_execution` case, explicitly create a Razorpay Test Mode Payment Link.
5. After payment, Razorpay's signed `payment_link.paid` webhook moves the case to `resolved` and writes the verified amount into `Outcome`.
6. A background scheduler automatically processes newly detected cases and executes due `retry_later` actions; the manual Analyze action remains available for operators.

## Safety architecture

- **Structured AI:** Gemini and Groq responses are validated against strict Pydantic schemas.
- **Fallback chain:** Gemini → Groq → deterministic rules, so provider failure does not become an undefined decision.
- **Policy boundary:** deterministic gates cover kill switch, risk escalation, action type, opt-out, confidence floor, amount ceiling, and retry ceiling.
- **Canonical lifecycle:** terminal states are defined once and are protected consistently across analysis, policy, review, and execution.
- **Paid backstop:** execution independently checks `Payment.status` immediately before provider calls so a paid case cannot mint another recovery link.
- **Human control:** uncertain and policy-escalated cases stay in review; hard blocked actions cannot be approved as-is.
- **Execution idempotency:** the execution reference is deterministic for a case + strategy decision, so client retries do not mint a second logical recovery action.
- **Delayed retry semantics:** `retry_later` persists a `not_before` timestamp and never calls Razorpay immediately; the scheduler executes it only after the delay.
- **Razorpay verification:** webhook signatures are checked against the raw request body and duplicate event IDs are ignored.
- **Monotonic recovery state:** once a payment is verified as paid, later out-of-order expiry/cancellation events cannot downgrade the case.
- **Auditability:** agent decisions, policy checks, execution lifecycle, webhook processing, and outcome evidence are inspectable per case.
- **Operational controls:** persisted kill switch, circuit breakers, rate limits, and explicit Test Mode confirmation reduce provider and execution risk.
- **State-changing auth:** protected POST endpoints require `X-API-Key` or `Authorization: Bearer ...` outside development/test. GET monitoring surfaces stay public for the dashboard.
- **API docs posture:** `/docs` and `/redoc` are disabled outside development/test environments.

## Metrics correctness

Revenue-at-risk is calculated over distinct failed orders, not payment rows. This prevents duplicate failed-attempt records for one order from inflating the historical denominator or recovery-by-reason breakdown.

## Evaluation discipline

The evaluation dataset uses a fixed random seed with an 80/20 dev/holdout split. Agent code is prohibited from reading the `ground_truth_labels` table; ground truth is used only after the model decision for scoring.

The evaluation reports precision, recall, false-positive cost, correct escalation rate, and shadow revenue. Live provider quotas are treated as an infrastructure constraint and never presented as model quality.

```powershell
cd backend
.venv\Scripts\activate
python -m scripts.calibrate_confidence --limit 30
python -m scripts.evaluate_holdout --limit 50
python -m scripts.shadow_backtest --limit 150
```

The existing frozen shadow report covers 300 of 506 failed payments and records 49.8% precision and 97.9% recall on that scored subset; do not treat this as a guarantee for future data.

## Local setup

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m scripts.init_db
python -m scripts.migrate_v3
python -m scripts.generate_synthetic_data --count 1500
python -m uvicorn app.main:app --reload
```

For production, set `ENV=production`, a strong `VASOOL_API_KEY`, explicit `CORS_ORIGINS`, and the Razorpay webhook credentials documented in `backend/.env.example`. The database-backed kill switch survives process restarts. `KILL_SWITCH_ENGAGED=true` is an emergency startup floor that cannot be cleared through the runtime API.

### Frontend

```powershell
cd frontend
npm ci
npm run dev
```

Set `NEXT_PUBLIC_API_URL` to the backend URL. For the browser demo, set `NEXT_PUBLIC_VASOOL_API_KEY` to the same API key configured on the backend. This is suitable for a controlled demo, but a real multi-user production deployment should use a proper identity/session system rather than exposing a long-lived shared key in browser code.

## Verification

```powershell
cd backend
.venv\Scripts\activate
pytest -q

cd ..\frontend
npm ci
npm test
npm audit --omit=dev --audit-level=high
npm run typecheck
npm run lint
npm run build
```

GitHub Actions runs backend pytest plus frontend regression tests, production-dependency audit, typecheck, lint, and build on every pull request to `main`.

## Important validation boundary

Automated tests cover the signed webhook path with simulated provider events and enforce the safety/idempotency invariants. No real Razorpay Test Mode payment or external webhook round-trip is claimed by this repository unless it is explicitly recorded in `PROGRESS.md` after an actual provider transaction.

## Known scaling limitations

The autonomous scheduler is intentionally lightweight and runs inside the FastAPI process. A multi-replica deployment should add a distributed scheduler/lease so multiple instances cannot sweep the same case concurrently. The current rate limiter and circuit breaker remain process-local; a distributed deployment should move those counters to shared storage.

The API-key layer is intentionally demo-friendly rather than a full enterprise identity system. Use an identity provider/service-to-service authorization layer before putting real customer data or production payment operations behind the API.

## Repository map

| Path | Purpose |
|---|---|
| `backend/app/agents/` | Root-cause and recovery-strategy agents |
| `backend/app/policy_engine.py` | Pure deterministic policy decision logic |
| `backend/app/policy_runner.py` | Persist policy decisions and case state |
| `backend/app/executor.py` | Idempotent Razorpay Test Mode execution and delayed retry handling |
| `backend/app/scheduler.py` | Background detection and scheduled recovery sweep |
| `backend/app/state.py` | Persisted runtime kill-switch state |
| `backend/app/status.py` | Canonical terminal lifecycle states |
| `backend/app/routers/webhooks.py` | Signed Razorpay outcome ingestion |
| `backend/app/routers/policy.py` | Policy evaluation, human review, execution routes |
| `backend/app/routers/cases.py` | Case queue, explainability, and outcome surfaces |
| `backend/tests/` | Policy, agent fallback, execution, webhook, scheduler-safety, metrics, and API coverage |
| `frontend/src/components/VasoolConsole.tsx` | Competition-facing recovery command center |
| `frontend/src/lib/recovery-actions.mjs` | Pure action-gating logic covered by frontend tests |
| `ARCHITECTURE.md` | Design decisions and system rationale |
| `FAILURE_SCENARIOS.md` | Failure lab and mitigations |
| `PROGRESS.md` | Build and validation record |
| `PRD.md` | Product requirements and success metrics |

## Safety notes

Use Razorpay **Test Mode** credentials only. Configure the Razorpay webhook to point at `/webhooks/razorpay` and use the same secret in `RAZORPAY_WEBHOOK_SECRET`.

Never treat a Payment Link creation response as recovered revenue. Vasool credits recovery only from a verified webhook outcome.

Keep `.env` and `.env.local` outside source control and rotate any credential that has been exposed.

## License

MIT — see `LICENSE`.
