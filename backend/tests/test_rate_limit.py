import pytest

from app.rate_limit import RateLimitExceeded, caller_bucket_key, check_and_record


def test_allows_calls_under_the_limit():
    for _ in range(5):
        check_and_record(limit=5)


def test_blocks_calls_over_the_limit():
    for _ in range(5):
        check_and_record(limit=5)
    with pytest.raises(RateLimitExceeded):
        check_and_record(limit=5)


def test_different_callers_get_different_rate_limit_buckets(client):
    from app.config import settings

    previous_env = settings.ENV
    settings.ENV = "production"
    try:
        request_a = client.build_request("POST", "/cases/1/analyze", headers={"X-API-Key": "key-a"})
        request_b = client.build_request("POST", "/cases/1/analyze", headers={"X-API-Key": "key-b"})
        key_a = caller_bucket_key(request_a)
        key_b = caller_bucket_key(request_b)

        check_and_record(limit=1, key=key_a)
        check_and_record(limit=1, key=key_b)
    finally:
        settings.ENV = previous_env
