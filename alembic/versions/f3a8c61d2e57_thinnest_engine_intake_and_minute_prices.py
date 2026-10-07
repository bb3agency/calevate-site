"""ThinnestAI engine: webhook endpoints on the route row, attested minute prices (D-678)

Revision ID: f3a8c61d2e57
Revises: a6d2f81c4e3b
Create Date: 2026-10-06 12:00:00.000000

Three changes, one per need of `docs/THINNEST-INTEGRATION.md` §3 and §5.

1. `ck_agents_engine_enum` ADMITS `thinnest`. `config.EngineName` gains it in the same
   build, and `tests/engine_name_drift_test.py` reads the live constraint against
   `SELECTABLE_ENGINES`. Drop-and-add, widening only, for `d7b1c48a2e93`'s reasons; the
   downgrade refuses while any agent carries the engine rather than deleting client agents.

2. `engine_agent_routes` CARRIES THE AGENT'S WEBHOOK ENDPOINT. ThinnestAI signs each
   delivery with a secret returned once by `POST /webhooks` (`thinnest-findings/mirror/
   pages/api-reference/webhooks.md:36-40`), one endpoint per vendor agent. The route row
   already stands for one vendor agent object and is the one table the voice-runtime
   receiver may read without a tenant (`RLS_EXEMPT_TENANT_COLUMNS`), so the secret lives
   beside it rather than in a second globally-readable table. It is stored SEALED under
   the engine intake key (`reliability/engine_intake_keys.py`), never in plaintext, and
   the five envelope columns are all-or-nothing with `webhook_id`. `engine_rate_key` names
   which attested per-minute price a call on this vendor agent is metered at.

3. `platform_engine_minute_prices` — the operator-attested ₹/min per engine and rate key.
   ThinnestAI reports no per-call cost (`api-reference/get-call.md:199-204`), so the only
   figure that may reach `unit_cost_paid` is one a human read off an invoice (hard rule 7).
   Append-only and effective-dated exactly like `platform_tts_prices`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import probe_skipped_offline
from sqlalchemy.dialects import postgresql

revision: str = "f3a8c61d2e57"
down_revision: str | None = "a6d2f81c4e3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENGINE_CONSTRAINT = "ck_agents_engine_enum"
_WIDENED = "engine IN ('bolna', 'cartesia', 'fake', 'pipecat', 'thinnest')"
_ORIGINAL = "engine IN ('bolna', 'cartesia', 'fake', 'pipecat')"

# Frozen copies, not imports: a migration records what the schema became at this revision.
_RATE_KEYS = "('platform', 'standard', 'premium', 'studio')"
_SEALED = (
    "webhook_secret_ciphertext",
    "webhook_secret_nonce",
    "webhook_secret_dek_wrapped",
    "webhook_secret_dek_nonce",
    "webhook_secret_kek_version",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.drop_constraint(op.f(_ENGINE_CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(_ENGINE_CONSTRAINT), "agents", _WIDENED)

    op.add_column("engine_agent_routes", sa.Column("webhook_id", sa.Text(), nullable=True))
    for column in _SEALED[:-1]:
        op.add_column("engine_agent_routes", sa.Column(column, sa.LargeBinary(), nullable=True))
    op.add_column(
        "engine_agent_routes",
        sa.Column("webhook_secret_kek_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "engine_agent_routes",
        sa.Column("webhook_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("engine_agent_routes", sa.Column("engine_rate_key", sa.Text(), nullable=True))
    # A webhook id with no secret is an endpoint whose deliveries we can never verify, and a
    # secret with no id is one no sweep can check is still switched on. Either half alone is
    # a registration that half-happened, so the row refuses it.
    all_null = " AND ".join(f"{c} IS NULL" for c in ("webhook_id", *_SEALED))
    none_null = " AND ".join(f"{c} IS NOT NULL" for c in ("webhook_id", *_SEALED))
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_webhook_sealed_whole"),
        "engine_agent_routes",
        f"({all_null}) OR ({none_null})",
    )
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_webhook_id_shape"),
        "engine_agent_routes",
        "webhook_id IS NULL OR (length(webhook_id) BETWEEN 1 AND 128)",
    )
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_engine_rate_key"),
        "engine_agent_routes",
        f"engine_rate_key IS NULL OR engine_rate_key IN {_RATE_KEYS}",
    )

    op.create_table(
        "platform_engine_minute_prices",
        # OUR engine name, text rather than an enum for `platform_tts_prices.provider`'s
        # reason: a price read back for a closed month must resolve for an engine that is
        # no longer selectable.
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("rate_key", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # RUPEES PER BILLED MINUTE. NUMERIC(12,6) like the other attested rates.
        sa.Column("inr_per_min", sa.Numeric(12, 6), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_engine_minute_prices_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "engine", "rate_key", "effective_from", name=op.f("pk_platform_engine_minute_prices")
        ),
        # An attested ₹0 meters every minute at nothing while looking like a working leg.
        sa.CheckConstraint(
            "inr_per_min > 0", name=op.f("ck_platform_engine_minute_prices_positive")
        ),
        sa.CheckConstraint(
            f"rate_key IN {_RATE_KEYS}",
            name=op.f("ck_platform_engine_minute_prices_rate_key"),
        ),
        sa.CheckConstraint(
            "length(btrim(source_note)) >= 3",
            name=op.f("ck_platform_engine_minute_prices_source_note"),
        ),
    )
    op.create_index(
        "ix_platform_engine_minute_prices_key",
        "platform_engine_minute_prices",
        ["engine", "rate_key", sa.text("effective_from DESC")],
    )
    op.execute(
        "CREATE TRIGGER platform_engine_minute_prices_append_only "
        "BEFORE UPDATE OR DELETE ON platform_engine_minute_prices "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER platform_engine_minute_prices_forbid_truncate "
        "BEFORE TRUNCATE ON platform_engine_minute_prices "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE platform_engine_minute_prices "
        "ENABLE ALWAYS TRIGGER platform_engine_minute_prices_append_only"
    )
    op.execute(
        "ALTER TABLE platform_engine_minute_prices "
        "ENABLE ALWAYS TRIGGER platform_engine_minute_prices_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_stranded_engines()

    op.execute(
        "DROP TRIGGER IF EXISTS platform_engine_minute_prices_forbid_truncate "
        "ON platform_engine_minute_prices"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS platform_engine_minute_prices_append_only "
        "ON platform_engine_minute_prices"
    )
    op.drop_index(
        "ix_platform_engine_minute_prices_key", table_name="platform_engine_minute_prices"
    )
    op.drop_table("platform_engine_minute_prices")

    for name in (
        "ck_engine_agent_routes_engine_rate_key",
        "ck_engine_agent_routes_webhook_id_shape",
        "ck_engine_agent_routes_webhook_sealed_whole",
    ):
        op.drop_constraint(op.f(name), "engine_agent_routes", type_="check")
    for column in ("engine_rate_key", "webhook_checked_at", *reversed(_SEALED), "webhook_id"):
        op.drop_column("engine_agent_routes", column)

    op.drop_constraint(op.f(_ENGINE_CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(_ENGINE_CONSTRAINT), "agents", _ORIGINAL)


def _refuse_stranded_engines() -> None:
    """Refuse BEFORE anything is dropped, so a refused downgrade changes nothing.

    Dropping the webhook columns would destroy signing secrets ThinnestAI shows only once,
    and narrowing the CHECK would reject (or require deleting) client agents.
    """
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to drop ThinnestAI webhook secrets\n"
        "and narrow ck_agents_engine_enum was NOT run. The narrower CHECK re-validates\n"
        "the agents rows, so a stranded `thinnest` agent still aborts the script. Check\n"
        "first with: SELECT count(*) FROM agents WHERE engine = 'thinnest';"
    ):
        return
    bind = op.get_bind()
    agents = bind.execute(
        sa.text("SELECT count(*) FROM agents WHERE engine = 'thinnest'")
    ).scalar_one()
    secrets = bind.execute(
        sa.text("SELECT count(*) FROM engine_agent_routes WHERE webhook_id IS NOT NULL")
    ).scalar_one()
    if agents or secrets:
        raise RuntimeError(
            f"{agents} agent row(s) run on `thinnest` and {secrets} route row(s) hold a "
            "webhook signing secret the vendor will not show again. Repoint those agents "
            "and delete their ThinnestAI webhook endpoints first, then re-run this "
            "downgrade."
        )
