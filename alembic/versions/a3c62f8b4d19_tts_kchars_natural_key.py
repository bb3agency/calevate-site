"""one `tts_kchars` metering row per (tenant, call) — the BYOK synthesizer leg's key

Revision ID: a3c62f8b4d19
Revises: f4b90c1d7e26
Create Date: 2026-09-07 00:00:00.000000

    CREATE UNIQUE INDEX CONCURRENTLY ux_usage_events_tenant_call_kchars
        ON usage_events (tenant_id, call_id, unit_type)
     WHERE call_id IS NOT NULL
       AND unit_type = 'tts_kchars'
       AND created_at >= '2026-09-07 00:00:00+00:00'::timestamptz;

`b8d3f47c2a19` gave `usage_events` its natural key and froze the five unit types
`pipeline._meter` wrote at that time. D-547 adds a sixth (`tts_kchars`, the BYOK
synthesizer leg metered from our own transcript — migration f4b90c1d7e26), and that
revision's own docstring names the consequence: *"covering a new unit type means a new
migration (this index cannot be widened in place)"*. This is that migration.

**A SECOND INDEX RATHER THAN A WIDER ONE, and the choice is about risk, not taste.**
Re-creating `ux_usage_events_tenant_call_unit` with a wider predicate means dropping the
key that protects the four live legs and rebuilding it CONCURRENTLY over the whole table —
a window in which a forgotten lock double-charges a real call, and a build whose failure
mode is an INVALID unique index that rejects insertions while being useless (that
revision's recovery note, at length). A disjoint predicate needs neither: the two indexes
cover disjoint unit types, so together they are exactly the wider key, and the old one is
never touched. `tts_chars` and `tts_kchars` are mutually exclusive per call by
construction — `pipeline._tts_cost_row` returns one row or none, decided by the voice.

Everything else follows b8d3f47c2a19 verbatim and for its reasons, which are not repeated
here: `created_at` and not `occurred_at` in the cutoff (a poller repair of a call that
ended yesterday must land INSIDE the index), the cutoff truncated DOWN to the minute with
an explicit offset, `tenant_id` leading the key so a unique violation cannot become a
cross-tenant side channel, no `ON CONFLICT` at the insert site, CONCURRENTLY outside the
migration's transaction with a 30s `lock_timeout`, and no RLS work because the table's
FORCEd policy already covers every row this index sees.

**Downgrade** drops the index. `lock_call_writes` remains the first line either way.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c62f8b4d19"
down_revision: str | None = "f4b90c1d7e26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ux_usage_events_tenant_call_kchars"
CUTOFF = "2026-09-07 00:00:00+00:00"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
            "ON usage_events (tenant_id, call_id, unit_type) "
            "WHERE call_id IS NOT NULL AND unit_type = 'tts_kchars' "
            f"AND created_at >= '{CUTOFF}'::timestamptz"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
