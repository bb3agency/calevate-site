"""Razorpay end to end: object routes, auto-recharge, disputes, authorised attempts (D-699)

Revision ID: e1a7c93b5d24
Revises: d3a7f5c19e42
Create Date: 2026-10-09 22:00:00.000000

1. `razorpay_object_routes`: which tenant an order, token or customer id belongs to, and
   what WE asked an order for. Read untenanted by the webhook receiver (one `FOR SELECT`
   policy for a session with no `app.tenant_id`); written only in the owning tenant's
   session.
2. `auto_recharge_settings`, `auto_recharge_charges`: the client's auto-recharge
   preferences, the Razorpay customer/token ids of their mandate, and every recharge we
   started. `ux_auto_recharge_charges_one_pending` holds one recharge in flight per tenant.
3. `payment_disputes`: one row per Razorpay dispute, with the credit held against it.
4. `topup_attempts.status` gains `authorized`.

DOWNGRADE drops the four tables and the status. It loses mandates (the tokens
stay valid at Razorpay and can be cancelled from its dashboard), the recharge history and
the dispute records; the ledger rows they wrote stay.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a7c93b5d24"
down_revision: str | None = "d3a7f5c19e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUTES = "razorpay_object_routes"
SETTINGS = "auto_recharge_settings"
CHARGES = "auto_recharge_charges"
DISPUTES = "payment_disputes"
OPS_READ = {
    ROUTES: "razorpay_object_routes_resolve",
    SETTINGS: "auto_recharge_settings_ops_read",
    CHARGES: "auto_recharge_charges_ops_read",
    DISPUTES: "payment_disputes_ops_read",
}

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_UNTENANTED = f"({_GUC} IS NULL)"
_MONEY = sa.Numeric(12, 4)


def _ts(*names: str) -> list[sa.Column[object]]:
    return [
        sa.Column(n, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for n in names
    ]


def _tenant_fk(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_tenant_id_organizations")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )
    op.execute(f"CREATE POLICY {OPS_READ[table]} ON {table} FOR SELECT USING {_UNTENANTED}")



def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        ROUTES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=True),
        *_ts("created_at"),
        sa.CheckConstraint(
            "kind IN ('order', 'token', 'customer')", name=op.f(f"ck_{ROUTES}_kind_enum")
        ),
        sa.CheckConstraint(
            "purpose IS NULL OR purpose IN ('topup', 'mandate', 'auto_recharge')",
            name=op.f(f"ck_{ROUTES}_purpose_enum"),
        ),
        sa.CheckConstraint(
            "amount_paise IS NULL OR amount_paise > 0", name=op.f(f"ck_{ROUTES}_amount_positive")
        ),
        sa.CheckConstraint(
            "(kind = 'order') = (amount_paise IS NOT NULL)",
            name=op.f(f"ck_{ROUTES}_order_has_amount"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ROUTES}")),
        sa.UniqueConstraint("object_id", name=op.f(f"uq_{ROUTES}_object_id")),
    )
    op.create_index(op.f(f"ix_{ROUTES}_tenant_recent"), ROUTES, ["tenant_id", "created_at"])
    _tenant_fk(ROUTES)
    _rls(ROUTES)

    op.create_table(
        SETTINGS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("threshold_inr", _MONEY, nullable=False),
        sa.Column("amount_inr", _MONEY, nullable=False),
        sa.Column("monthly_cap_inr", _MONEY, nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=True),
        sa.Column("token_id", sa.String(length=64), nullable=True),
        sa.Column("mandate_method", sa.String(length=8), nullable=True),
        sa.Column(
            "mandate_status", sa.String(length=16), server_default=sa.text("'none'"), nullable=False
        ),
        sa.Column("mandate_max_inr", _MONEY, nullable=True),
        sa.Column("mandate_order_id", sa.String(length=64), nullable=True),
        sa.Column(
            "consecutive_failures", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("authorised_by", sa.UUID(), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint("threshold_inr >= 0", name=op.f(f"ck_{SETTINGS}_threshold_non_negative")),
        sa.CheckConstraint("amount_inr > 0", name=op.f(f"ck_{SETTINGS}_amount_positive")),
        sa.CheckConstraint(
            "monthly_cap_inr >= amount_inr", name=op.f(f"ck_{SETTINGS}_cap_covers_one_charge")
        ),
        sa.CheckConstraint(
            "mandate_method IS NULL OR mandate_method IN ('upi', 'card')",
            name=op.f(f"ck_{SETTINGS}_method_enum"),
        ),
        sa.CheckConstraint(
            "mandate_status IN ('none', 'pending', 'confirmed', 'rejected', 'cancelled', "
            "'paused')",
            name=op.f(f"ck_{SETTINGS}_mandate_status_enum"),
        ),
        sa.CheckConstraint(
            "NOT enabled OR (mandate_status = 'confirmed' AND token_id IS NOT NULL)",
            name=op.f(f"ck_{SETTINGS}_enabled_needs_confirmed_token"),
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name=op.f(f"ck_{SETTINGS}_failures_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{SETTINGS}")),
        sa.UniqueConstraint("tenant_id", name=op.f(f"uq_{SETTINGS}_tenant_id")),
    )
    _tenant_fk(SETTINGS)
    op.execute(
        f"ALTER TABLE {SETTINGS} ADD CONSTRAINT fk_{SETTINGS}_authorised_by_users "
        "FOREIGN KEY (authorised_by) REFERENCES users (id) ON DELETE SET NULL"
    )
    _rls(SETTINGS)

    op.create_table(
        CHARGES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("amount_inr", _MONEY, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint("amount_inr > 0", name=op.f(f"ck_{CHARGES}_amount_positive")),
        sa.CheckConstraint(
            "status IN ('pending', 'captured', 'failed')", name=op.f(f"ck_{CHARGES}_status_enum")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (settled_at IS NULL)",
            name=op.f(f"ck_{CHARGES}_settled_iff_not_pending"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CHARGES}")),
        sa.UniqueConstraint("order_id", name=op.f(f"uq_{CHARGES}_order_id")),
    )
    op.create_index(
        "ux_auto_recharge_charges_one_pending",
        CHARGES,
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(op.f(f"ix_{CHARGES}_tenant_recent"), CHARGES, ["tenant_id", "created_at"])
    _tenant_fk(CHARGES)
    _rls(CHARGES)

    op.create_table(
        DISPUTES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("amount_inr", _MONEY, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_inr", _MONEY, nullable=False),
        sa.Column("action_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_event", sa.String(length=48), nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint("amount_inr > 0", name=op.f(f"ck_{DISPUTES}_amount_positive")),
        sa.CheckConstraint("hold_inr >= 0", name=op.f(f"ck_{DISPUTES}_hold_non_negative")),
        sa.CheckConstraint(
            "status IN ('open', 'under_review', 'won', 'lost', 'closed')",
            name=op.f(f"ck_{DISPUTES}_status_enum"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{DISPUTES}")),
        sa.UniqueConstraint("dispute_id", name=op.f(f"uq_{DISPUTES}_dispute_id")),
    )
    op.create_index(op.f(f"ix_{DISPUTES}_tenant_recent"), DISPUTES, ["tenant_id", "created_at"])
    _tenant_fk(DISPUTES)
    _rls(DISPUTES)

    op.execute("ALTER TABLE topup_attempts DROP CONSTRAINT ck_topup_attempts_status_enum")
    op.execute(
        "ALTER TABLE topup_attempts ADD CONSTRAINT ck_topup_attempts_status_enum "
        "CHECK (status IN ('created', 'authorized', 'captured', 'failed'))"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE topup_attempts DROP CONSTRAINT ck_topup_attempts_status_enum")
    op.execute("ALTER TABLE topup_attempts NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE topup_attempts SET status = 'created' WHERE status = 'authorized'")
    op.execute("ALTER TABLE topup_attempts FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE topup_attempts ADD CONSTRAINT ck_topup_attempts_status_enum "
        "CHECK (status IN ('created', 'captured', 'failed'))"
    )
    for table in (DISPUTES, CHARGES, SETTINGS, ROUTES):
        op.execute(f"DROP POLICY IF EXISTS {OPS_READ[table]} ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
