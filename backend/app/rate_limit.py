"""
Minimal in-memory rate limiter for LLM-cost-incurring endpoints. Not a
general middleware or an external dependency — same single-process
assumption as everything else here. Enough to stop a runaway loop or a
double-click storm from burning Gemini/Groq quota mid-demo.
"""
import time
from collections import deque

_WINDOW_SECONDS = 60
_calls: deque[float] = deque()


class RateLimitExceeded(Exception):
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        super().__init__(f"Rate limit exceeded: {limit} calls per {window_seconds}s")


def check_and_record(limit: int, window_seconds: int = _WINDOW_SECONDS) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    while _calls and _calls[0] < cutoff:
        _calls.popleft()
    if len(_calls) >= limit:
        raise RateLimitExceeded(limit, window_seconds)
    _calls.append(now)


def reset() -> None:
    """Test-only hook."""
    _calls.clear()