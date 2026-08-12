"""One typed accessor for `rowcount`.

The CAS doctrine (BACKEND-PATTERNS §5) reads `rowcount == 0` as "another worker won"
everywhere — outbox claims, inbox claims, idempotency retries, status transitions,
invitation burn. So the value is load-bearing, not diagnostic.

SQLAlchemy's async API declares `Result[Any]`, which has no `rowcount`; the object
returned for an UPDATE/DELETE is a `CursorResult`, which does. Rather than scattering
`# type: ignore` across every CAS site — where a silenced type error would eventually
hide a real one — the narrowing happens once, here, with the reason attached.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CursorResult


def rowcount_of(result: Any) -> int:
    """Rows affected by the statement that produced `result`.

    Returns 0 for a result that reports no rowcount, which is the safe direction: every
    caller treats 0 as "I lost the race" and skips, rather than proceeding on an
    assumption it cannot check.
    """
    if isinstance(result, CursorResult):
        return int(result.rowcount or 0)
    count = getattr(result, "rowcount", None)
    return int(count) if isinstance(count, int) and count >= 0 else 0


__all__ = ["rowcount_of"]
