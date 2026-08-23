"""
Proves the fallback chain (Gemini -> Groq -> rules) actually falls through,
by forcing a failure at each tier with fake clients — no real network calls,
no API keys required. This is the test PROGRESS.md's Day 3 checklist calls
out explicitly: "fallback chain tested by forcing a failure at each tier."
"""
from app.agents.llm_clients import AgentTierError
from app.agents.recovery_strategy_agent import run_recovery_strategy_agent
from app.agents.root_cause_agent import run_root_cause_agent

ROOT_CONTEXT = {
    "failure_reason": "otp_timeout",
    "method": "upi",
    "attempt_number": 1,
    "amount_paise": 50000,
    "hours_since_order": 0.5,
    "customer_opted_out": False,
}

STRATEGY_CONTEXT = {
    **ROOT_CONTEXT,
    "root_cause_category": "otp_timeout",
    "is_transient": True,
    "root_cause_confidence": 0.8,
}


class FakeTierClient:
    """Stands in for GeminiClient/GroqClient. Configure with either a
    canned (parsed, tokens, latency_ms) response, or an exception to raise —
    mirrors the two ways a real provider call can go for us."""

    model = "fake-model"

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.called = False

    def complete_json(self, *args, **kwargs):
        self.called = True
        if self._error is not None:
            raise self._error
        return self._response


def test_root_cause_uses_gemini_when_it_succeeds():
    gemini = FakeTierClient(
        response=(
            {
                "root_cause_category": "otp_timeout",
                "is_transient": True,
                "confidence": 0.9,
                "reasoning": "clean gateway signal",
            },
            30,
            90,
        )
    )
    groq = FakeTierClient(error=AgentTierError("should never be called"))

    result = run_root_cause_agent(ROOT_CONTEXT, gemini=gemini, groq=groq)

    assert result.tier == "gemini"
    assert result.output.root_cause_category.value == "otp_timeout"
    assert result.tokens_used == 30
    assert groq.called is False


def test_root_cause_falls_back_to_groq_when_gemini_fails():
    gemini = FakeTierClient(error=AgentTierError("gemini timed out"))
    groq = FakeTierClient(
        response=(
            {
                "root_cause_category": "otp_timeout",
                "is_transient": True,
                "confidence": 0.8,
                "reasoning": "groq confirms",
            },
            42,
            120,
        )
    )

    result = run_root_cause_agent(ROOT_CONTEXT, gemini=gemini, groq=groq)

    assert result.tier == "groq"
    assert result.tokens_used == 42
    assert result.latency_ms == 120


def test_root_cause_falls_back_to_rules_when_both_llm_tiers_fail():
    gemini = FakeTierClient(error=AgentTierError("gemini down"))
    groq = FakeTierClient(error=AgentTierError("groq down"))

    result = run_root_cause_agent(ROOT_CONTEXT, gemini=gemini, groq=groq)

    assert result.tier == "rules_fallback"
    assert result.tokens_used is None
    assert result.latency_ms == 0
    # otp_timeout is a known, transient reason -> rules fallback should still land correctly
    assert result.output.root_cause_category.value == "otp_timeout"
    assert result.output.is_transient is True


def test_root_cause_falls_back_to_rules_when_gemini_returns_off_schema_json():
    # valid JSON, but doesn't match RootCauseOutput -> ValidationError -> fallback
    gemini = FakeTierClient(response=({"unexpected_field": "shape"}, 10, 50))
    groq = FakeTierClient(error=AgentTierError("groq also down"))

    result = run_root_cause_agent(ROOT_CONTEXT, gemini=gemini, groq=groq)

    assert result.tier == "rules_fallback"


def test_recovery_strategy_falls_back_through_all_three_tiers():
    gemini = FakeTierClient(error=AgentTierError("gemini down"))
    groq = FakeTierClient(error=AgentTierError("groq down"))

    result = run_recovery_strategy_agent(STRATEGY_CONTEXT, gemini=gemini, groq=groq)

    assert result.tier == "rules_fallback"
    # is_transient=True in STRATEGY_CONTEXT -> rules heuristic picks retry_now
    assert result.output.action.value == "retry_now"


def test_recovery_strategy_risk_flagged_always_escalates_even_on_rules_fallback():
    context = {
        **STRATEGY_CONTEXT,
        "root_cause_category": "risk_flagged",
        "is_transient": False,
    }
    gemini = FakeTierClient(error=AgentTierError("gemini down"))
    groq = FakeTierClient(error=AgentTierError("groq down"))

    result = run_recovery_strategy_agent(context, gemini=gemini, groq=groq)

    assert result.tier == "rules_fallback"
    assert result.output.action.value == "escalate_human"