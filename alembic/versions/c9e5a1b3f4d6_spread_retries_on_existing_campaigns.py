"""Spread retries over the day on existing campaigns left at the default (25 Nov 2026)

Revision ID: c9e5a1b3f4d6
Revises: b8d4f0a2e3c5
Create Date: 2026-11-25 10:20:00.000000

Founder, 25 Nov 2026: retries ring at another time of day (`retry_policy.spread`,
`campaigns/call_timing.spread_retry_at`) on existing campaigns too, not only new ones.

WHICH CAMPAIGNS. Non-archived ones whose retry settings were never changed: `retry_policy`
NULL, or exactly the default every campaign was stored with before the switch existed,
`{"max_attempts": 3, "backoff_minutes": [30, 120]}` (`DEFAULT_RETRY_POLICY` from the first
campaigns commit until the Improve tab added `spread`). Left alone:

* `spread` present, true or false: an owner who turned it off on the Improve tab stored
  `false`, and that choice is kept;
* other tries or gaps: the owner changed the retry settings, so they are not "the default".

Each row it moves gets `spread_set_by: "c9e5a1b3f4d6"` beside `spread`, which nothing reads,
so the downgrade can tell its own rows from a campaign made after the default turned on.
An owner who later edits the tries and gaps replaces the policy and drops the mark, so the
downgrade leaves that campaign as they set it.

NO SCHEMA CHANGE. Reversible: `downgrade()` removes `spread` and the mark from the rows that
still carry the mark.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "c9e5a1b3f4d6"
down_revision: str | None = "b8d4f0a2e3c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_DEFAULT = {"max_attempts": 3, "backoff_minutes": [30, 120]}
_MARK = "spread_set_by"
_SPREAD = {**_OLD_DEFAULT, "spread": True, _MARK: revision}


def _bracketed(statement: str) -> None:
    """`campaigns` is FORCE-RLS'd, which binds a non-superuser owner (production, DEPLOYMENT
    §9.3a) to the fail-closed tenant policy, so the statement runs with FORCE lifted and put
    back (`f2477c8d623d`)."""
    op.execute("ALTER TABLE campaigns NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(statement)
    finally:
        op.execute("ALTER TABLE campaigns FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Literals only (every character typed here), so `--sql` renders the same statement.
    _bracketed(
        "UPDATE campaigns SET retry_policy = "
        f"'{json.dumps(_SPREAD)}'::jsonb WHERE archived_at IS NULL "
        f"AND (retry_policy IS NULL OR retry_policy = '{json.dumps(_OLD_DEFAULT)}'::jsonb)"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _bracketed(
        f"UPDATE campaigns SET retry_policy = retry_policy - 'spread' - '{_MARK}' "
        f"WHERE retry_policy ->> '{_MARK}' = '{revision}'"
    )
