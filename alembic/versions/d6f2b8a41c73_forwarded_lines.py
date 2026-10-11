"""A client's existing number forwarded to its Calevate number, its tests, and "save our number" (D-746)

Revision ID: d6f2b8a41c73
Revises: e9b4c2a7d136
Create Date: 2026-10-11 18:00:00.000000

1. `forwarded_lines` (tenant, FORCE-RLS): the number a client already publishes, its line
   kind, carrier, chosen mode and ring time, the Calevate number it forwards to, its test
   status and the two findings a test records (which caller number arrived, and whether two
   calls at once both got through), plus the quiet-line episode.
2. `forwarding_tests` (tenant, FORCE-RLS): one run of the verification call, CAS-updated
   through `placing -> ringing -> settled | failed`; every run is also in `audit_log`.
3. `forwarding_test_legs` (platform, no RLS, listed in `RLS_EXEMPT_TENANT_COLUMNS`): each
   outbound leg rung from a platform number in our developer workspace, read untenanted by
   the shared-number line lock and by the ingest of the voice platform's report.
4. `save_number_messages` (tenant, FORCE-RLS): at most one "save our number" WhatsApp per
   caller per client, keyed on a keyed hash of the caller's number.
5. `calls.forwarding_test_id` (the inbound arrival of a test) and `calls.caller_id_hidden`
   (a forwarded call that showed the client's own number instead of the caller's).
6. `organizations.save_number_message_enabled`, off by default.
7. Two absorbed `usage_events` units: `forwarding_test_min` (the verification call's
   minutes) and `whatsapp_msg` (Calevate's own WhatsApp sends). Both are ours, never billed.

Downgrade refuses while any row of the two new units exists (`usage_events` is append-only).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6f2b8a41c73"
down_revision: str | None = "e9b4c2a7d136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINES = "forwarded_lines"
TESTS = "forwarding_tests"
LEGS = "forwarding_test_legs"
SAVES = "save_number_messages"
TENANT_TABLES = (LINES, TESTS, SAVES)

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

_UNITS_BEFORE = (
    "telephony_s",
    "stt_s",
    "stt_min",
    "tts_chars",
    "tts_kchars",
    "llm_tok_in",
    "llm_tok_out",
    "llm_ktok_in",
    "llm_ktok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
    "ai_stt_min",
)
_NEW_UNITS = ("forwarding_test_min", "whatsapp_msg")
_UNITS_AFTER = (*_UNITS_BEFORE, *_NEW_UNITS)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(*names: str) -> list[sa.Column[object]]:
    return [
        sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for n in names
    ]


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def _units(units: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN {units!r})"
    )


_FINDINGS = ("caller_shown", "business_number_shown", "other_number_shown")
_CONCURRENCY = ("both_arrived", "one_arrived", "not_tested")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        LINES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("e164", sa.String(length=16), nullable=False),
        sa.Column("line_kind", sa.String(length=16), nullable=False),
        sa.Column("carrier", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("ring_seconds", sa.SmallInteger(), nullable=False),
        sa.Column("calevate_number_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="untested", nullable=False),
        sa.Column("attested_by", sa.UUID(), nullable=True),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_test_id", sa.UUID(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("caller_id_finding", sa.String(length=24), nullable=True),
        sa.Column("concurrency_finding", sa.String(length=16), nullable=True),
        sa.Column("quiet_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quiet_alerted_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(LINES, "e164_india", r"e164 ~ '^\+91[0-9]{10}$'"),
        _ck(LINES, "line_kind_enum", _in("line_kind", ("mobile", "landline", "office_system"))),
        _ck(LINES, "carrier_enum", _in("carrier", ("airtel", "jio", "vi", "bsnl", "other"))),
        _ck(LINES, "mode_enum", _in("mode", ("conditional", "all_calls"))),
        _ck(
            LINES,
            "ring_seconds_fit_mode",
            "(mode = 'all_calls' AND ring_seconds = 0) OR (mode = 'conditional' "
            "AND ring_seconds BETWEEN 5 AND 30 AND ring_seconds % 5 = 0)",
        ),
        _ck(
            LINES, "status_enum", _in("status", ("untested", "testing", "working", "not_working"))
        ),
        _ck(
            LINES,
            "caller_id_finding_enum",
            "caller_id_finding IS NULL OR " + _in("caller_id_finding", _FINDINGS),
        ),
        _ck(
            LINES,
            "concurrency_finding_enum",
            "concurrency_finding IS NULL OR " + _in("concurrency_finding", _CONCURRENCY),
        ),
        _ck(LINES, "quiet", "(quiet_alerted_at IS NULL) OR (quiet_since IS NOT NULL)"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_forwarded_lines_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["calevate_number_id"],
            ["phone_numbers.id"],
            name=op.f("fk_forwarded_lines_calevate_number_id_phone_numbers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forwarded_lines")),
        sa.UniqueConstraint("tenant_id", "e164", name=op.f("uq_forwarded_lines_tenant_id_e164")),
    )
    op.create_index(op.f("ix_forwarded_lines_tenant_id"), LINES, ["tenant_id"])

    op.create_table(
        TESTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("line_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="placing", nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=True),
        sa.Column("legs_placed", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "lookup_arrivals",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "call_arrivals",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("caller_id_finding", sa.String(length=24), nullable=True),
        sa.Column("concurrency_finding", sa.String(length=16), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_inr", sa.Numeric(precision=12, scale=4), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(TESTS, "status_enum", _in("status", ("placing", "ringing", "settled", "failed"))),
        _ck(
            TESTS,
            "outcome_enum",
            "outcome IS NULL OR "
            + _in("outcome", ("arrived", "not_arrived", "answered_on_phone", "not_placed")),
        ),
        _ck(
            TESTS,
            "caller_id_finding_enum",
            "caller_id_finding IS NULL OR " + _in("caller_id_finding", _FINDINGS),
        ),
        _ck(
            TESTS,
            "concurrency_finding_enum",
            "concurrency_finding IS NULL OR " + _in("concurrency_finding", _CONCURRENCY),
        ),
        _ck(TESTS, "legs_placed_range", "legs_placed BETWEEN 0 AND 2"),
        _ck(
            TESTS, "settled_iff", "(status IN ('settled', 'failed')) = (settled_at IS NOT NULL)"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_forwarding_tests_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            [f"{LINES}.id"],
            name=op.f("fk_forwarding_tests_line_id_forwarded_lines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forwarding_tests")),
    )
    op.create_index(
        "ix_forwarding_tests_tenant_recent", TESTS, ["tenant_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_forwarding_tests_open",
        TESTS,
        ["tenant_id"],
        postgresql_where=sa.text("status IN ('placing', 'ringing')"),
    )

    op.create_table(
        LEGS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("test_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("leg", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="placing", nullable=False),
        sa.Column("engine_call_ref", sa.Text(), nullable=True),
        sa.Column("answered", sa.Boolean(), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(LEGS, "status_enum", _in("status", ("placing", "live", "ended", "failed"))),
        _ck(LEGS, "leg_range", "leg BETWEEN 1 AND 2"),
        _ck(LEGS, "seconds_nonnegative", "seconds IS NULL OR seconds >= 0"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forwarding_test_legs")),
        sa.UniqueConstraint("test_id", "leg", name=op.f("uq_forwarding_test_legs_test_id_leg")),
    )
    op.create_index(
        "ux_forwarding_test_legs_engine_call",
        LEGS,
        ["engine_call_ref"],
        unique=True,
        postgresql_where=sa.text("engine_call_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_forwarding_test_legs_live",
        LEGS,
        ["created_at"],
        postgresql_where=sa.text("status IN ('placing', 'live')"),
    )

    op.create_table(
        SAVES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("caller_ref", sa.String(length=64), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("refusal_code", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        _ck(SAVES, "status_enum", _in("status", ("queued", "sent", "refused", "failed"))),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_save_number_messages_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_save_number_messages_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_save_number_messages")),
        sa.UniqueConstraint(
            "tenant_id", "caller_ref", name=op.f("uq_save_number_messages_tenant_id_caller_ref")
        ),
    )

    for table in TENANT_TABLES:
        _rls(table)

    op.add_column("calls", sa.Column("forwarding_test_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_calls_forwarding_test_id_forwarding_tests"),
        "calls",
        TESTS,
        ["forwarding_test_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "calls",
        sa.Column("caller_id_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "save_number_message_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    _units(_UNITS_AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM usage_events WHERE unit_type IN "
        f"{_NEW_UNITS!r}) THEN RAISE EXCEPTION 'usage_events holds forwarding_test_min or "
        "whatsapp_msg rows, which are append-only: this revision cannot be downgraded'; "
        "END IF; END $$"
    )
    _units(_UNITS_BEFORE)
    op.drop_column("organizations", "save_number_message_enabled")
    op.drop_column("calls", "caller_id_hidden")
    op.drop_constraint(
        op.f("fk_calls_forwarding_test_id_forwarding_tests"), "calls", type_="foreignkey"
    )
    op.drop_column("calls", "forwarding_test_id")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table(SAVES)
    op.drop_table(LEGS)
    op.drop_table(TESTS)
    op.drop_table(LINES)
