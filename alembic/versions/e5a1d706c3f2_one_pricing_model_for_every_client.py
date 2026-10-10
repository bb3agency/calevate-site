"""one pricing model for every client: prepaid credits, and an optional monthly platform fee

Revision ID: e5a1d706c3f2
Revises: c2b7e5a94d18
Create Date: 2026-10-10

D-707 (founder, 10 Oct 2026) supersedes D-34's two motions and D-11's setup fee plus
retainer. Every client buys prepaid credits; the operator may switch on a platform-wide
monthly fee that is collected as a separate payment. This revision does five things:

1. `organizations` gains the per-client fee waiver (instant, reason, operator) and
   `moved_to_credits_at`, which records the accounts this revision moves.
2. `monthly_fee_charges` (one fee per client per IST month) and `monthly_fee_payments`
   (append-only, hard rule 4) are created with the FORCEd tenant policy (hard rule 1).
3. `razorpay_object_routes.purpose` admits `platform_fee`, the order a fee is paid through.
4. Retainer terms stop applying from now. For every `plans` row that quotes a setup fee,
   monthly fee, included minutes or an overage rate and can still apply now or later, a
   SUCCESSOR row is inserted from `max(effective_from, now())` carrying the same ceilings
   and model surcharge and no retainer price. Nothing is edited: the rows that priced
   earlier months stay, so every invoice already issued renders exactly as it did
   (`billing/plans.py` resolves a month by its own instant).
5. Every `managed` account moves to `prepaid`, stamped with `moved_to_credits_at`.

WHAT THE MOVE DOES TO A LIVE ACCOUNT. A moved account now pays for calls from its wallet.
If it holds no credit, every OUTBOUND dial is refused `no_credits` until it is topped up,
and its inbound line follows the zero-credit rule (D-551) on the next call the meter
settles. No credit is granted here: `credit_ledger` is append-only and a migration must not
invent money (the argument `a8d3f61c04e7` makes). The revision prints how many accounts
moved and how many of those hold no credit, so the person running the deploy reads the
consequence from the output.

`managed` stays in the `plan_tier` CHECK for one release (hard rule 8's two-step): nothing
writes it after this, and the next release narrows the CHECK and deletes its readers.

DOWNGRADE refuses while any fee payment is recorded (dropping the table would destroy a
record of money received) or any fee order route exists. Otherwise it puts the moved
accounts back on `managed`, deletes the successor plan rows this revision inserted
(identified by their `created_at`, which is this revision's transaction instant and is
also every moved account's `moved_to_credits_at`), and drops what upgrade created.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import (
    emit_note,
    execute_data_statement,
    is_offline,
    probe_skipped_offline,
)

revision: str = "e5a1d706c3f2"
down_revision: str | None = "c2b7e5a94d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHARGES = "monthly_fee_charges"
PAYMENTS = "monthly_fee_payments"
ROUTES = "razorpay_object_routes"
ROUTE_PURPOSE_CHECK = "ck_razorpay_object_routes_purpose_enum"
PURPOSES_BEFORE = "('topup', 'mandate', 'auto_recharge')"
PURPOSES_AFTER = "('topup', 'mandate', 'auto_recharge', 'platform_fee')"
WAIVER_CHECK = "ck_organizations_platform_fee_waiver_together"

_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"
_MONEY = sa.Numeric(12, 4)

#: A `plans` row that still quotes a retainer price. Spelled out rather than imported from
#: `billing/terms.py`: a migration records the statement that ran.
_PRICED = (
    "(p.setup_fee IS NOT NULL OR p.monthly_fee IS NOT NULL OR p.included_min IS NOT NULL "
    "OR p.overage_rate IS NOT NULL OR p.overage_rate_second IS NOT NULL "
    "OR p.overage_rate_value IS NOT NULL)"
)

_CLOSE_RETAINERS = f"""
INSERT INTO plans (id, tenant_id, llm_model_surcharge, hard_cap_min, hard_cap_spend,
                   client_cap_min, client_cap_spend, concurrency_ceiling,
                   effective_from, effective_to, created_at, updated_at)
SELECT gen_random_uuid(), p.tenant_id, p.llm_model_surcharge, p.hard_cap_min,
       p.hard_cap_spend, p.client_cap_min, p.client_cap_spend, p.concurrency_ceiling,
       GREATEST(COALESCE(p.effective_from, '-infinity'::timestamptz), now()),
       p.effective_to, now(), now()
FROM plans p
WHERE {_PRICED}
  AND (p.effective_to IS NULL OR p.effective_to > now())
"""

_MOVE = (
    "UPDATE organizations SET plan_tier = 'prepaid', moved_to_credits_at = now(), "
    "updated_at = now() WHERE plan_tier = 'managed'"
)

#: Moved accounts holding no positive balance on their newest ledger row — the ones whose
#: outbound calling stops at the next dispatch tick.
_STOPPED_COUNT = """
SELECT count(*) FROM organizations o
WHERE o.deleted_at IS NULL
  AND o.moved_to_credits_at IS NOT NULL
  AND COALESCE((
        SELECT l.balance_after FROM credit_ledger l
        WHERE l.tenant_id = o.id
        ORDER BY l.occurred_at DESC, l.id DESC LIMIT 1
      ), 0) <= 0
"""

_RESTORE = (
    "UPDATE organizations SET plan_tier = 'managed', moved_to_credits_at = NULL, "
    "updated_at = now() WHERE moved_to_credits_at IS NOT NULL"
)

_DELETE_SUCCESSORS = """
DELETE FROM plans s
WHERE s.created_at IN (
        SELECT DISTINCT o.moved_to_credits_at FROM organizations o
        WHERE o.moved_to_credits_at IS NOT NULL)
  AND s.setup_fee IS NULL AND s.monthly_fee IS NULL AND s.included_min IS NULL
  AND s.overage_rate IS NULL AND s.overage_rate_second IS NULL
  AND s.overage_rate_value IS NULL
"""


def _ts(*names: str, nullable: bool = False) -> list[sa.Column[object]]:
    return [
        sa.Column(
            n,
            sa.DateTime(timezone=True),
            server_default=None if nullable else sa.text("now()"),
            nullable=nullable,
        )
        for n in names
    ]


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def _purposes(values: str) -> None:
    op.execute(f"ALTER TABLE {ROUTES} DROP CONSTRAINT {ROUTE_PURPOSE_CHECK}")
    op.execute(
        f"ALTER TABLE {ROUTES} ADD CONSTRAINT {ROUTE_PURPOSE_CHECK} "
        f"CHECK (purpose IS NULL OR purpose IN {values})"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.add_column(
        "organizations", sa.Column("platform_fee_waived_at", sa.DateTime(timezone=True))
    )
    op.add_column("organizations", sa.Column("platform_fee_waiver_reason", sa.Text()))
    op.add_column("organizations", sa.Column("platform_fee_waived_by", sa.UUID()))
    op.add_column("organizations", sa.Column("moved_to_credits_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        op.f("fk_organizations_platform_fee_waived_by_admin_users"),
        "organizations",
        "admin_users",
        ["platform_fee_waived_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {WAIVER_CHECK} CHECK ("
        "(platform_fee_waived_at IS NULL) = (platform_fee_waiver_reason IS NULL) "
        "AND (platform_fee_waiver_reason IS NULL "
        "OR length(btrim(platform_fee_waiver_reason)) > 0))"
    )

    op.create_table(
        CHARGES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_order_id", sa.String(length=64), nullable=True),
        *_ts("issued_notice_sent_at", "reminder_sent_at", "paused_notice_sent_at", nullable=True),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            "period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name=op.f(f"ck_{CHARGES}_period_shape")
        ),
        sa.CheckConstraint("amount > 0", name=op.f(f"ck_{CHARGES}_amount_positive")),
        sa.CheckConstraint(
            "grace_ends_at > issued_at", name=op.f(f"ck_{CHARGES}_grace_after_issue")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CHARGES}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{CHARGES}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ux_monthly_fee_charges_tenant_period", CHARGES, ["tenant_id", "period"], unique=True
    )
    op.create_index(
        "ux_monthly_fee_charges_order",
        CHARGES,
        ["provider_order_id"],
        unique=True,
        postgresql_where=sa.text("provider_order_id IS NOT NULL"),
    )
    _rls(CHARGES)

    op.create_table(
        PAYMENTS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("charge_id", sa.UUID(), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("payment_ref", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.UUID(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        *_ts("created_at"),
        sa.CheckConstraint("amount > 0", name=op.f(f"ck_{PAYMENTS}_amount_positive")),
        sa.CheckConstraint(
            "method IN ('razorpay', 'manual')", name=op.f(f"ck_{PAYMENTS}_method_enum")
        ),
        sa.CheckConstraint(
            "length(btrim(payment_ref)) > 0", name=op.f(f"ck_{PAYMENTS}_payment_ref_present")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PAYMENTS}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{PAYMENTS}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["charge_id"],
            [f"{CHARGES}.id"],
            name=op.f(f"fk_{PAYMENTS}_charge_id_{CHARGES}"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ux_monthly_fee_payments_charge", PAYMENTS, ["charge_id"], unique=True)
    op.create_index(
        "ux_monthly_fee_payments_ref", PAYMENTS, ["method", "payment_ref"], unique=True
    )
    op.create_index("ix_monthly_fee_payments_tenant", PAYMENTS, ["tenant_id", "paid_at"])
    _rls(PAYMENTS)
    op.execute(
        f"CREATE TRIGGER {PAYMENTS}_append_only BEFORE UPDATE OR DELETE ON {PAYMENTS} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {PAYMENTS}_forbid_truncate BEFORE TRUNCATE ON {PAYMENTS} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ALWAYS, so a restore running as `session_replication_role = replica` cannot step
    # around the guarantee — every other ledger is armed the same way.
    op.execute(f"ALTER TABLE {PAYMENTS} ENABLE ALWAYS TRIGGER {PAYMENTS}_append_only")
    op.execute(f"ALTER TABLE {PAYMENTS} ENABLE ALWAYS TRIGGER {PAYMENTS}_forbid_truncate")

    _purposes(PURPOSES_AFTER)

    # THE DATA HALF, inside the RLS bracket: `plans`, `organizations` and `credit_ledger`
    # are FORCE-RLS, which subjects the owner to a policy that is fail-closed on an unset
    # `app.tenant_id`, so without it both writes match zero rows and report success.
    op.execute("ALTER TABLE plans NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_ledger NO FORCE ROW LEVEL SECURITY")
    try:
        closed = execute_data_statement(
            sa.text(_CLOSE_RETAINERS),
            note="offline `--sql`: the retainer successor rows are emitted in full.",
        )
        moved = execute_data_statement(
            sa.text(_MOVE),
            note="offline `--sql`: the managed -> prepaid move is emitted in full.",
        )
        stopped = (
            None if is_offline() else op.get_bind().execute(sa.text(_STOPPED_COUNT)).scalar_one()
        )
    finally:
        op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE plans FORCE ROW LEVEL SECURITY")

    if is_offline():
        emit_note(
            "D-707: this script ends every retainer price from now and moves every "
            "'managed' account to 'prepaid'.\nAFTER APPLYING, count the moved accounts "
            "that hold no calling credit (their OUTBOUND calls\nare refused 'no_credits' "
            f"until topped up):\n{_STOPPED_COUNT.strip()};"
        )
        return
    print(  # noqa: T201 - the deploy log is this statement's only reader
        f"D-707: ended {closed} retainer plan row(s) from now (earlier months keep their "
        f"terms); moved {moved} organisation(s) from 'managed' to 'prepaid'. {stopped} "
        "moved account(s) hold no calling credit and are refused 'no_credits' on every "
        "OUTBOUND dial until topped up."
    )


def downgrade() -> None:
    if not probe_skipped_offline(
        f"offline `--sql`: the pre-flights that refuse to drop {PAYMENTS} while a platform\n"
        "fee payment is recorded, or while a platform fee order exists at the payment\n"
        "provider, were NOT run, and nothing in this script re-checks them. Check first with:\n"
        f"SELECT count(*) FROM {PAYMENTS};\n"
        f"SELECT count(*) FROM {ROUTES} WHERE purpose = 'platform_fee';"
    ):
        bind = op.get_bind()
        payments = bind.execute(sa.text(f"SELECT count(*) FROM {PAYMENTS}")).scalar_one()
        if payments:
            raise RuntimeError(
                f"refusing to downgrade: {payments} platform fee payment(s) are recorded and "
                f"dropping {PAYMENTS} would destroy a record of money received"
            )
        routes = bind.execute(
            sa.text(f"SELECT count(*) FROM {ROUTES} WHERE purpose = 'platform_fee'")
        ).scalar_one()
        if routes:
            raise RuntimeError(
                f"refusing to downgrade: {routes} platform fee order(s) exist at the payment "
                "provider and the older schema cannot route their payments"
            )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE plans NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_DELETE_SUCCESSORS)
        op.execute(_RESTORE)
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE plans FORCE ROW LEVEL SECURITY")

    _purposes(PURPOSES_BEFORE)
    op.drop_table(PAYMENTS)
    op.drop_table(CHARGES)
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT {WAIVER_CHECK}")
    op.drop_constraint(
        op.f("fk_organizations_platform_fee_waived_by_admin_users"),
        "organizations",
        type_="foreignkey",
    )
    op.drop_column("organizations", "moved_to_credits_at")
    op.drop_column("organizations", "platform_fee_waived_by")
    op.drop_column("organizations", "platform_fee_waiver_reason")
    op.drop_column("organizations", "platform_fee_waived_at")
