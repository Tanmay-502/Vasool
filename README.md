# Vasool

AI that finds revenue slipping away — failed payments, abandoned checkouts,
failed subscription charges — and wins it back through a bounded, auditable
multi-agent recovery pipeline.

Built for the Razorpay AI Buildathon 2026 (Track 03 — AI Revenue Recovery).

## Status
Day 1 of 7 — foundation (schema, config, CI). See [PROGRESS.md](./PROGRESS.md).

## Why
A payment doesn't fail for one reason and stay failed forever — insufficient
balance, a bank decline, a dropped OTP, a timed-out checkout. Most of that
revenue is recoverable if something notices in time, figures out why it
failed, and takes one safe, well-timed action. Vasool is that something —
every money-touching decision is explainable, bounded, and logged before it
executes.

## Architecture
See [ARCHITECTURE.md](./ARCHITECTURE.md).

## Setup
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
pytest -q
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/health`.

### Environment variables (`backend/.env`)
- `DATABASE_URL` — Neon Postgres connection string
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — Test Mode keys from the Razorpay dashboard
- `GEMINI_API_KEY` — from Google AI Studio
- `GROQ_API_KEY` — from console.groq.com

## License
MIT — see [LICENSE](./LICENSE).