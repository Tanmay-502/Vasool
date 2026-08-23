import pytest
from pydantic import ValidationError

from app.agents.schemas import RecoveryStrategyOutput, RootCauseOutput


def test_root_cause_output_rejects_off_taxonomy_category():
    with pytest.raises(ValidationError):
        RootCauseOutput(
            root_cause_category="server_is_on_fire",
            is_transient=True,
            confidence=0.5,
            reasoning="x",
        )


def test_root_cause_output_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        RootCauseOutput(
            root_cause_category="otp_timeout", is_transient=True, confidence=1.5, reasoning="x"
        )


def test_root_cause_output_accepts_valid_payload():
    output = RootCauseOutput(
        root_cause_category="otp_timeout", is_transient=True, confidence=0.8, reasoning="clean signal"
    )
    assert output.root_cause_category.value == "otp_timeout"


def test_recovery_strategy_output_only_accepts_canonical_actions():
    with pytest.raises(ValidationError):
        RecoveryStrategyOutput(action="give_up", confidence=0.5, reasoning="x")


def test_recovery_strategy_output_accepts_valid_payload():
    output = RecoveryStrategyOutput(action="retry_now", confidence=0.7, reasoning="transient")
    assert output.action.value == "retry_now"