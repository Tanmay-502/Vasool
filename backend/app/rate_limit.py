"""
Minimal in-memory rate limiter for cost/quota-incurring outbound calls. Not
a general middleware or an external dependency — same single-process
assumption as everything else here.

Day 4 update: now keyed. Originally a single global deque shared by every
caller, which was fine when the only caller was /cases/{id}/analyze — but
adding a second caller (the Razorpay execution endpoint) on the *same*
shared deque would have meant analyzing cases silently ate into the
execution budget and vice versa. Each key gets its own independent window;
`key="default"` preserves the exact behavior every Day 3 call site already
relies on, so nothing upstream had to change.
"""
import hashlib
import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import settings

_WINDOW_SECONDS = 60
_calls: dict[str, deque[float]] = defaultdict(deque)


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        super().__init__(f"Rate limit exceeded: {limit} calls per {window_seconds}s")


def check_and_record(limit: int, window_seconds: int = _WINDOW_SECONDS, key: str = "default") -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    bucket = _calls[key]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise RateLimitExceeded(limit, window_seconds)
    bucket.append(now)


def caller_bucket_key(request: Request | None) -> str:
    if request is None:
        return "default"

    api_key = request.headers.get("x-api-key")
    if not api_key:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            api_key = token.strip()

    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"api-key:{digest}"

    if settings.ENV.lower() in {"development", "test"}:
        return "default"

    return f"ip:{request.client.host if request.client else 'unknown'}"


def reset() -> None:
    """Test-only hook."""
    _calls.clear()
