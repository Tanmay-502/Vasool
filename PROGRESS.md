# Build log — Vasool

## Day 1 — Foundation
- [ ] Schema (10 tables) defined in `models.py`
- [ ] FastAPI skeleton, `/health` test passes
- [ ] CI running on push
- [ ] Neon DB created, tables created via `init_db.py`
- [ ] Razorpay test keys + Gemini + Groq keys obtained

## Day 2 — Synthetic data + revenue intelligence
- [ ] Transaction generator, ~1,500 records
- [ ] 80/20 split, ground-truth labels frozen
- [ ] `/metrics` endpoint — no LLM involved

## Day 3 — Root Cause + Strategy agents
- [ ] Both agents return structured JSON
- [ ] Gemini -> Groq -> rules fallback tested by forcing a failure

## Day 4 — Policy engine + Razorpay execution
- [ ] Policy engine unit-tested, zero LLM inside
- [ ] Real Razorpay Test Mode call wired to EXECUTE
- [ ] Every decision + API call in `audit_log`

## Day 5 — Orchestration + dashboard
- [ ] LangGraph pipeline end to end
- [ ] Command-center + case explorer UI

## Day 6 — Evaluation + failure lab
- [ ] Metrics reproducible via one script
- [ ] 3 failure scenarios documented

## Day 7 — Pitch + dry run
- [ ] 5-minute pitch recorded
- [ ] Full live demo dry run