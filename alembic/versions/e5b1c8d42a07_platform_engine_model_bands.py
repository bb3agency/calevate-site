"""platform_engine_model_bands: the per-minute band of each engine model, recorded by an operator

Revision ID: e5b1c8d42a07
Revises: a9c4e7d2b815
Create Date: 2026-10-11 12:00:00.000000

ThinnestAI's `GET /models` says whether a model can answer a call, whether our plan may pick
it and whether it may run beside our own voice key, but not whether it lifts a call to a
dearer per-minute band (snapshots/2026-10-08/pages/api-reference/models/list-models.md:
463-505). That band was a hand-edited table in `engine/thinnest.py`, so a model the vendor
added (Composer v0.1, Qwen3.6 27B) stayed unsellable until somebody shipped code. Founder
decision, 11 Oct 2026: an operator records the band in the ops console, step-up confirmed
and audited, and the newest row per (engine, model_id) is in force.

Append-only with the shared `calevate_forbid_mutation` / `calevate_forbid_truncate`
triggers, `ENABLE ALWAYS`, for `platform_engine_minute_prices`' reason: the band decides
which rate a minute is metered at, and an editable row would let today's reading rewrite
what a past publish was priced against. Platform-scoped (one engine account for the
deployment), so no `tenant_id` and no policy; registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS`.

`recorded_by` is NULL only on the rows this migration carries over from the code table it
replaces, which were not entered by an operator; the CHECK makes any unattributed row say
where it came from. Keyed by the engine's raw model id, not the console name.

Locking: one `CREATE TABLE`, one index, two triggers, seed rows into the new table; nothing
existing is touched. Downgrade drops the table and every band an operator recorded since;
models then read as unpriced and are not offered until the code table is restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b1c8d42a07"
down_revision: str | None = "a9c4e7d2b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "platform_engine_model_bands"

#: `engine/thinnest._MODEL_CONSOLE_READING` as it stood when this migration replaced it,
#: mapped from console name to id with the live `GET /models` the founder relayed on
#: 11 Oct 2026. A frozen copy, not an import: a migration records what it wrote.
_CARRIED_OVER: tuple[tuple[str, str], ...] = (
    ("prana", "none"),
    ("gpt-oss-120b", "none"),
    ("prana-voice", "none"),
    ("gpt-4.1-nano", "none"),
    ("gpt-5.4-nano", "none"),
    ("gpt-5-nano", "none"),
    ("gpt-5.6-luna", "none"),
    ("gpt-5-mini", "premium"),
)
_CARRIED_OVER_NOTE = (
    "Carried over from the founder-relayed reading of the ThinnestAI console model "
    "dropdown, 10 Oct 2026 (engine/thinnest._MODEL_CONSOLE_READING)."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        _TABLE,
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.CheckConstraint("band IN ('none', 'premium')", name=op.f(f"ck_{_TABLE}_band")),
        sa.CheckConstraint(
            "length(model_id) BETWEEN 1 AND 128", name=op.f(f"ck_{_TABLE}_model_id_shape")
        ),
        sa.CheckConstraint(
            "source_note IS NULL OR length(btrim(source_note)) >= 3",
            name=op.f(f"ck_{_TABLE}_source_note"),
        ),
        sa.CheckConstraint(
            "recorded_by IS NOT NULL OR source_note IS NOT NULL",
            name=op.f(f"ck_{_TABLE}_attributed"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["admin_users.id"],
            name=op.f(f"fk_{_TABLE}_recorded_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f(f"pk_{_TABLE}")),
    )
    op.create_index(
        "ix_platform_engine_model_bands_model",
        _TABLE,
        ["engine", "model_id", sa.text("seq DESC")],
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_append_only BEFORE UPDATE OR DELETE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_forbid_truncate BEFORE TRUNCATE ON {_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_append_only")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_forbid_truncate")

    rows = sa.table(
        _TABLE,
        sa.column("engine", sa.Text()),
        sa.column("model_id", sa.Text()),
        sa.column("band", sa.Text()),
        sa.column("source_note", sa.Text()),
    )
    op.bulk_insert(
        rows,
        [
            {
                "engine": "thinnest",
                "model_id": model_id,
                "band": band,
                "source_note": _CARRIED_OVER_NOTE,
            }
            for model_id, band in _CARRIED_OVER
        ],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_forbid_truncate ON {_TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {_TABLE}_append_only ON {_TABLE}")
    op.drop_index("ix_platform_engine_model_bands_model", table_name=_TABLE)
    op.drop_table(_TABLE)
