# Vasool dashboard

This is the Next.js dashboard for Vasool's explainable payment-recovery
pipeline.

## Start

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

The dashboard expects the FastAPI backend at
`http://127.0.0.1:8000`. Override it with:

```text
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

## Deployed environment

- Dashboard: [vasool-two.vercel.app](https://vasool-two.vercel.app/)
- API: [vasool-ta24.onrender.com](https://vasool-ta24.onrender.com)

For the Vercel deployment, set `NEXT_PUBLIC_API_URL` to the Render API URL
without a trailing slash:

```text
NEXT_PUBLIC_API_URL=https://vasool-ta24.onrender.com
```

## Demo flow

- Review headline recovery and risk metrics.
- Select a case in **Explainability & review queue**.
- Click **Analyze demo case** to run diagnosis and policy evaluation.
- Inspect root cause, recommended action, agent reasoning, and each guardrail.
- Use the confirmed kill-switch control to route new automation to human review.

The demo flow never calls the execution endpoint or creates a Razorpay Payment
Link.

## Commands

```powershell
npm run dev
npm run lint
npm run build
```
