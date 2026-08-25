import pytest

from app.agents import circuit_breaker
from app.executor import CaseNotPendingExecutionError, CircuitOpenError, execute_case
from app.models import Action, AgentDecision, AuditLog, Customer, Merchant, Order, Payment, RecoveryCase
from app.rate_limit import RateLimitExceeded, check_and_record
from app.razorpay_client import RazorpayError


class FakeRazorpayClient:
    """Stands in for RazorpayClient — mirrors FakeTierClient's pattern from
    tests/test_agents_fallback.py: configure with either a canned response
    or an exception."""

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls = []

    def create_payment_link(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _seed_pending_execution_case(db, *, action="retry_now", amount_paise=20000, opted_out=False):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()
    customer = Customer(
        merchant_id=merchant.id,
        name="Test User",
        email="t@example.com",
        phone="9000000000",
        opted_out=opted_out,
    )
    db.add(customer)
    db.flush()
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=amount_paise, status="failed")
    db.add(order)
    db.flush()
    payment = Payment(order_id=order.id, method="upi", status="failed", failure_reason="otp_timeout", attempt_number=1)
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="pending_execution")
    db.add(case)
    db.flush()
    db.add(
        AgentDecision(
            recovery_case_id=case.id,
            agent_name="recovery_strategy_agent",
            model_used="rules_fallback:rules-v1",
            input_snapshot={},
            output={"action": action, "confidence": 0.9, "reasoning": "test"},
            confidence=0.9,
        )
    )
    db.commit()
    return case


def test_raises_if_case_not_pending_execution(db_session):
    merchant = Merchant(name="M")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, name="C", email="c@example.com", phone="9000000000")
    db_session.add(customer)
    db_session.flush()
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=1000, status="failed")
    db_session.add(order)
    db_session.flush()
    payment = Payment(order_id=order.id, method="upi", status="failed", attempt_number=1)
    db_session.add(payment)
    db_session.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db_session.add(case)
    db_session.commit()

    with pytest.raises(CaseNotPendingExecutionError):
        execute_case(db_session, case, razorpay=FakeRazorpayClient())


def test_successful_execution_creates_action_and_marks_case_executed(db_session):
    case = _seed_pending_execution_case(db_session, action="retry_now")
    fake = FakeRazorpayClient(response={"id": "plink_ABC123", "short_url": "https://rzp.io/i/abc"})

    result = execute_case(db_session, case, razorpay=fake)

    assert result["case_status"] == "executed"
    assert result["razorpay_reference"] == "plink_ABC123"
    assert result["payment_link"] == "https://rzp.io/i/abc"

    action = db_session.query(Action).filter(Action.recovery_case_id == case.id).one()
    assert action.status == "sent"
    assert action.razorpay_reference == "plink_ABC123"
    assert db_session.get(RecoveryCase, case.id).status == "executed"


def test_idempotency_key_passed_as_reference_id(db_session):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "plink_X", "short_url": "https://rzp.io/i/x"})

    execute_case(db_session, case, razorpay=fake)

    action = db_session.query(Action).filter(Action.recovery_case_id == case.id).one()
    assert fake.calls[0]["reference_id"] == action.idempotency_key


def test_notify_flag_set_for_send_payment_link_and_not_for_retry_now(db_session):
    case = _seed_pending_execution_case(db_session, action="send_payment_link")
    fake = FakeRazorpayClient(response={"id": "plink_Y", "short_url": "https://rzp.io/i/y"})
    execute_case(db_session, case, razorpay=fake)
    assert fake.calls[0]["notify"] is True


def test_retry_now_does_not_request_razorpay_notification(db_session):
    case = _seed_pending_execution_case(db_session, action="retry_now")
    fake = FakeRazorpayClient(response={"id": "plink_Z", "short_url": "https://rzp.io/i/z"})
    execute_case(db_session, case, razorpay=fake)
    assert fake.calls[0]["notify"] is False


def test_razorpay_error_marks_action_and_case_failed_and_trips_breaker(db_session):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(error=RazorpayError("simulated outage"))

    with pytest.raises(RazorpayError):
        execute_case(db_session, case, razorpay=fake)

    action = db_session.query(Action).filter(Action.recovery_case_id == case.id).one()
    assert action.status == "failed"
    assert db_session.get(RecoveryCase, case.id).status == "execution_failed"
    assert circuit_breaker.is_open("razorpay") is False  # only 1 failure, threshold is 3


def test_circuit_breaker_skips_call_after_threshold_failures(db_session):
    for _ in range(circuit_breaker.FAILURE_THRESHOLD):
        circuit_breaker.record_failure("razorpay")

    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(error=RazorpayError("should never be called"))

    with pytest.raises(CircuitOpenError):
        execute_case(db_session, case, razorpay=fake)

    assert fake.calls == []
    assert db_session.get(RecoveryCase, case.id).status == "execution_failed"


def test_rate_limit_exceeded_marks_case_failed_without_calling_razorpay(db_session):
    from app.executor import RAZORPAY_RATE_LIMIT_KEY, RAZORPAY_RATE_LIMIT_PER_MINUTE

    for _ in range(RAZORPAY_RATE_LIMIT_PER_MINUTE):
        check_and_record(RAZORPAY_RATE_LIMIT_PER_MINUTE, key=RAZORPAY_RATE_LIMIT_KEY)

    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "should_not_be_reached"})

    with pytest.raises(RateLimitExceeded):
        execute_case(db_session, case, razorpay=fake)

    assert fake.calls == []
    assert db_session.get(RecoveryCase, case.id).status == "execution_failed"


def test_analyze_rate_limit_bucket_is_independent_of_razorpay_bucket(db_session):
    for _ in range(20):
        check_and_record(20, key="default")  # simulate 20 analyze calls

    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "plink_OK", "short_url": "https://rzp.io/i/ok"})

    result = execute_case(db_session, case, razorpay=fake)  # should NOT be rate limited
    assert result["case_status"] == "executed"


def test_audit_log_rows_written_on_success(db_session):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(response={"id": "plink_AUD", "short_url": "https://rzp.io/i/aud"})

    execute_case(db_session, case, razorpay=fake)

    events = [
        row.event_type
        for row in db_session.query(AuditLog).filter(AuditLog.recovery_case_id == case.id).all()
    ]
    assert events == ["execution_started", "execution_succeeded"]


def test_audit_log_rows_written_on_failure(db_session):
    case = _seed_pending_execution_case(db_session)
    fake = FakeRazorpayClient(error=RazorpayError("boom"))

    with pytest.raises(RazorpayError):
        execute_case(db_session, case, razorpay=fake)

    events = [
        row.event_type
        for row in db_session.query(AuditLog).filter(AuditLog.recovery_case_id == case.id).all()
    ]
    assert events == ["execution_started", "execution_failed"]