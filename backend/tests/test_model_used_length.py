"""
Guards against a real landmine: SQLite (what CI runs against) doesn't
enforce VARCHAR(n) length, so a `model_used` string too long for Postgres
would pass CI clean and only fail against the real Neon DB — the same
category of bug as the JSONB dialect issue and the schema-drift problem
reset_schema.py exists to fix. This makes the length constraint checkable
without standing up a Postgres service container in CI (already rejected
for Day 2, same reasoning still applies).
"""
from app.config import settings
from app.models import AgentDecision


def test_model_used_fits_column_for_every_configured_model():
    max_len = AgentDecision.__table__.c.model_used.type.length
    for tier, model in [
        ("gemini", settings.GEMINI_MODEL),
        ("groq", settings.GROQ_MODEL),
        ("rules_fallback", "rules-v1"),
    ]:
        combined = f"{tier}:{model}"
        assert len(combined) <= max_len, (
            f"'{combined}' is {len(combined)} chars, exceeds model_used "
            f"column width {max_len} — would silently break on Postgres."
        )