import pytest

from app.config import settings
from app.executor import AutomationPausedError, execute_case
from app.models import Action

from tests.test_executor import FakeRazorpayClient, _seed_pending_execution_case


def test_execution_boundary_honors_kill_switch(db_session, monkeypatch):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "never", "short_url": "never"})
    monkeypatch.setattr(settings, "KILL_SWITCH_ENGAGED", True)

    with pytest.raises(AutomationPausedError):
        execute_case(db_session, case, razorpay=fake)

    assert fake.calls == []


def test_repeated_execution_reuses_same_action_and_does_not_call_provider_twice(db_session):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "plink_once", "short_url": "https://rzp.io/i/once"})

    first = execute_case(db_session, case, razorpay=fake)
    second = execute_case(db_session, case, razorpay=fake)

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(fake.calls) == 1
    assert db_session.query(Action).filter(Action.recovery_case_id == case.id).count() == 1


def test_failed_execution_can_retry_with_same_reference_id(db_session):
    case = _seed_pending_execution_case(db_session)
    first_fake = FakeRazorpayClient(error=__import__("app.razorpay_client", fromlist=["RazorpayError"]).RazorpayError("timeout"))

    with pytest.raises(Exception):
        execute_case(db_session, case, razorpay=first_fake)

    second_fake = FakeRazorpayClient(response={"id": "plink_retry", "short_url": "https://rzp.io/i/retry"})
    result = execute_case(db_session, case, razorpay=second_fake)

    assert result["case_status"] == "executed"
    assert second_fake.calls[0]["reference_id"] == first_fake.calls[0]["reference_id"]
    assert db_session.query(Action).filter(Action.recovery_case_id == case.id).count() == 1
