import pytest

from app.rate_limit import RateLimitExceeded, check_and_record


def test_allows_calls_under_the_limit():
    for _ in range(5):
        check_and_record(limit=5)


def test_blocks_calls_over_the_limit():
    for _ in range(5):
        check_and_record(limit=5)
    with pytest.raises(RateLimitExceeded):
        check_and_record(limit=5)