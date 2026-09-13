"""

Time utilities - canonical timezone-aware UTC clock

IMPORTANT:
- D8 migration (Iteration 018): all new/updated model timestamps MUST be
  timezone-aware UTC. Naive datetimes are deprecated in this codebase because
  aware/naive arithmetic raises TypeError and the project has already been
  bitten by timezone ambiguity (Step 12 v5 expiry incident).
- `ensure_utc` normalizes historical naive datetimes by ATTACHING UTC (they
  were all produced by datetime.utcnow(), i.e. already UTC wall-clock).
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Current time as timezone-aware UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return `value` as timezone-aware UTC; naive input is assumed UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
