"""
Lightweight circuit breaker for the LLM tiers (Gemini, Groq).

Day 4's checklist calls for a breaker on outbound Razorpay calls; this is
the equivalent for the LLM tiers, needed earlier — right now a Gemini
outage mid-demo means every single case eats a full AGENT_TIMEOUT_SECONDS
wait before falling through to Groq. Slow and visible at exactly the worst
moment.

Deliberately simple, in-process state, same single-worker assumption used
everywhere else in this project. If a tier fails FAILURE_THRESHOLD times
within COOLDOWN_SECONDS, it's skipped — no network call attempted — until
the cooldown lapses. Small chance of missing a tier's recovery, in exchange
for a much shorter, predictable failure path during an actual outage.

Tier state is shared across both agents on purpose ("gemini", "groq", not
"root_cause:gemini") — if Gemini is down, it's down for both agents equally.
"""
import time
from collections import defaultdict, deque

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60

_recent_failures: dict[str, deque[float]] = defaultdict(deque)


def record_failure(tier_name: str) -> None:
    now = time.monotonic()
    _recent_failures[tier_name].append(now)
    _prune(tier_name, now)


def record_success(tier_name: str) -> None:
    _recent_failures[tier_name].clear()


def is_open(tier_name: str) -> bool:
    """True means: skip this tier, don't even attempt the call."""
    now = time.monotonic()
    _prune(tier_name, now)
    return len(_recent_failures[tier_name]) >= FAILURE_THRESHOLD


def _prune(tier_name: str, now: float) -> None:
    cutoff = now - COOLDOWN_SECONDS
    q = _recent_failures[tier_name]
    while q and q[0] < cutoff:
        q.popleft()


def reset() -> None:
    """Test-only hook."""
    _recent_failures.clear()