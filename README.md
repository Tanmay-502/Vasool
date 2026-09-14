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
| **API docs** | [vasool-ta24.onrender.com/docs](https://vasool-ta24.onrender.com/docs) |

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

## Safety architecture

- **Structured AI:** Gemini and Groq responses are validated against strict Pydantic schemas.
- **Fallback chain:** Gemini → Groq → deterministic rules, so provider failure does not become an undefined decision.
- **Policy boundary:** seven deterministic gates: kill switch, risk escalation, action type, opt-out, confidence floor, amount ceiling, retry ceiling.
- **Human control:** uncertain and policy-escalated cases stay in review; hard blocked actions cannot be approved as-is.
- **Execution idempotency:** the execution reference is deterministic for a case + strategy decision, so client retries do not mint a second logical recovery action.
- **Razorpay verification:** webhook signatures are checked against the raw request body and duplicate event IDs are ignored.
- **Monotonic recovery state:** once a payment is verified as paid, later out-of-order expiry/cancellation events cannot downgrade the case.
- **Auditability:** agent decisions, policy checks, execution lifecycle, webhook processing, and outcome evidence are inspectable per case.
- **Operational controls:** circuit breakers, independent rate limits, runtime kill switch, and explicit Test Mode confirmation reduce provider and execution risk.

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

## Local setup

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m scripts.init_db
python -m scripts.generate_synthetic_data --count 1500
python -m uvicorn app.main:app --reload
```

Required environment variables are documented in `backend/.env.example`, including `RAZORPAY_WEBHOOK_SECRET` for signed outcome verification.

### Frontend

```powershell
cd frontend
npm ci
npm run dev
```

Set `NEXT_PUBLIC_API_URL` to the backend URL when the frontend and API are deployed separately.

## Verification

```powershell
cd backend
.venv\Scripts\activate
pytest -q

cd ..\frontend
npm ci
npm audit --omit=dev --audit-level=high
npm run typecheck
npm run lint
npm run build
```

GitHub Actions runs the backend test suite plus frontend production-dependency audit, typecheck, lint, and build on every pull request to `main`.

## Repository map

| Path | Purpose |
|---|---|
| `backend/app/agents/` | Root-cause and recovery-strategy agents |
| `backend/app/policy_engine.py` | Pure deterministic policy decision logic |
| `backend/app/policy_runner.py` | Persist policy decisions and case state |
| `backend/app/executor.py` | Idempotent Razorpay Test Mode execution |
| `backend/app/routers/webhooks.py` | Signed Razorpay outcome ingestion |
| `backend/app/routers/policy.py` | Policy evaluation, human review, execution routes |
| `backend/app/routers/cases.py` | Case queue, explainability, and outcome surfaces |
| `backend/tests/` | Policy, agent fallback, execution, webhook, and API coverage |
| `frontend/src/components/VasoolConsole.tsx` | Competition-facing recovery command center |
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
