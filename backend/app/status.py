"""Canonical recovery-case lifecycle constants shared by all state-changing paths."""

TERMINAL_STATUSES = frozenset(
    {
        "resolved",
        "executed",
        "partially_recovered",
        "rejected",
        "recovery_cancelled",
        "recovery_expired",
    }
)
