from app.agents import circuit_breaker


def test_circuit_closed_by_default():
    assert circuit_breaker.is_open("gemini") is False


def test_circuit_opens_after_threshold_failures():
    for _ in range(circuit_breaker.FAILURE_THRESHOLD):
        circuit_breaker.record_failure("gemini")
    assert circuit_breaker.is_open("gemini") is True


def test_circuit_stays_closed_below_threshold():
    for _ in range(circuit_breaker.FAILURE_THRESHOLD - 1):
        circuit_breaker.record_failure("gemini")
    assert circuit_breaker.is_open("gemini") is False


def test_success_resets_the_failure_count():
    for _ in range(circuit_breaker.FAILURE_THRESHOLD - 1):
        circuit_breaker.record_failure("gemini")
    circuit_breaker.record_success("gemini")
    circuit_breaker.record_failure("gemini")
    assert circuit_breaker.is_open("gemini") is False


def test_tiers_are_tracked_independently():
    for _ in range(circuit_breaker.FAILURE_THRESHOLD):
        circuit_breaker.record_failure("gemini")
    assert circuit_breaker.is_open("gemini") is True
    assert circuit_breaker.is_open("groq") is False