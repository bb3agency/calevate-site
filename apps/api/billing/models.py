"""Billing & metering (DATA-MODEL §8). Money = NUMERIC(12,4) INR, never floats
(hard rule 7). usage_events is INSERT-only — the immutability trigger ships in the
same migration; fixes are compensating entries."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

# D-34 runs BOTH motions on ONE product: a self-serve org is the same `organizations`
# row as a managed one, distinguished by this column, so nothing forks.
PLAN_TIERS = ("managed", "self_serve", "trial")
CREDIT_REASONS = ("topup", "usage", "adjustment", "refund")

UNIT_TYPES = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
)

MONEY = Numeric(12, 4)


class UsageEvent(PKMixin, Base):
    """Append-only ledger. Records OUR cost (unit_cost_paid) next to billable qty —
    per-client margin is a query (D-12). Maps 1:1 onto Get Call's cost.breakdown."""

    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint(f"unit_type IN {UNIT_TYPES!r}", name="unit_type_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))
    unit_type: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost_paid: Mapped[Decimal | None] = mapped_column(MONEY)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Plan(PKMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    setup_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    monthly_fee: Mapped[Decimal | None] = mapped_column(MONEY)
    included_min: Mapped[int | None] = mapped_column(Integer)
    overage_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    hard_cap_min: Mapped[int | None] = mapped_column(Integer)
    hard_cap_spend: Mapped[Decimal | None] = mapped_column(MONEY)
    concurrency_ceiling: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    effective_from: Mapped[datetime | None]
    effective_to: Mapped[datetime | None]


class SpendState(TimestampMixin, Base):
    """Per-tenant monthly counters; `capped` is the cap the compliance gate enforces.

    The ONE reader that can stop a call is `compliance.service.check_dispatch`, which
    every outbound path goes through — the campaign dispatch worker, the "call this
    lead" button and the instant-lead-callback webhook all call it. `apps/voice-runtime`
    reads NOTHING here (it acks a webhook and defers to ARQ — hard rule 3), so nobody
    should build on the idea that the runtime enforces spend. The remaining readers are
    reporting only: the client usage panel, the admin tenant detail and the attention
    queue.

    Inbound is deliberately outside all of it: the gate is outbound-only, because the
    caller initiated an inbound call and capping it would be an outage, not a control.

    `minutes_used`, `spend_used` and `capped` are all maintained by the post-call
    pipeline's upsert, in one statement: the flag is computed from the same accumulated
    totals that are being written, against the tenant's newest `plans` row, so two calls
    finishing at once cannot both read a pre-cap total and neither arm the cap. Either
    ceiling arms it (`hard_cap_min` or `hard_cap_spend`); a tenant with no plan row or a
    NULL ceiling is never capped.

    The meter is the ONLY writer, which has a consequence worth knowing before you read
    the flag anywhere: a capped tenant meters nothing, so the flag cannot clear itself.
    Both readers therefore check `month` as well — a cap belonging to a closed billing
    month is not a cap. Without that, an outbound-only tenant capped in July would be
    refused every dial in August with no call able to complete and clear it.
    """

    __tablename__ = "spend_state"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True
    )
    month: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM' (IST billing month)
    minutes_used: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, server_default="0"
    )
    spend_used: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    capped: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class CreditLedgerEntry(PKMixin, Base):
    """Prepaid credit balance, append-only (DATA-MODEL §8, D-39).

    Shipped in M1 even though the self-serve top-up UI is M2, and the reason is D-12:
    **metering is not retrofittable**. A balance derived after the fact from usage rows
    is a reconstruction, not a ledger — and the moment a client disputes a charge, the
    difference is the whole argument.

    `balance_after` is denormalized ON PURPOSE. The running balance could be summed
    from `delta`, but then every pre-dispatch check pays for a full-table aggregate, and
    a single bad row silently shifts every balance after it. Storing it makes each entry
    a self-contained assertion that can be verified against its predecessor.

    Append-only like the other ledgers (hard rule 4): a refund is a NEW entry, never an
    edit to the charge.

    What is NOT here, and is missing deliberately rather than by oversight: a partial
    unique index on `(tenant_id, ref) WHERE reason IN ('topup','usage')`. That is what
    would make double-crediting structurally impossible instead of merely unlikely —
    today both dedupes are check-then-write under a per-tenant advisory lock. It cannot
    be created while the table holds rows that violate it (21 such pairs), and being
    append-only, those rows can only be corrected by compensating entries, never
    deleted. Migration a6f2e84b1d37 carries the reasoning and the route to the follow-up.

    A SECOND attempt (2026-08-11) tried the way around that: keep the predicate but fence
    off the history with a literal cutoff —

        UNIQUE (tenant_id, ref)
        WHERE reason IN ('topup','usage') AND ref IS NOT NULL
          AND occurred_at >= '<literal>'::timestamptz

    which builds cleanly, since every violating pair predates any cutoff one would pick.
    It was refused too, for a NEW reason that the first attempt could not have seen: the
    repository manufactures fresh violations on purpose. `tests/credit_reconciliation_
    test.py::_double_credit` reproduces the race by calling `record_entry` twice with one
    `ref` — through the ledger's only writer, deliberately, because "a hand-rolled INSERT
    would seed a shape the production bug never produced". Those rows land NOW, i.e.
    after any cutoff, so the index turns the reconciler's own fixtures into integrity
    errors: measured, 11 of that module's 13 tests fail with the index present and all 13
    pass without it. Trading the reconciler's test coverage for the constraint is a bad
    trade in the one place where the reconciler is the thing repairing money.

    The route is therefore a fixture change and not schema work, and it is small: the
    residue must be seeded with an explicit pre-cutoff `occurred_at` (or through a seed
    helper that bypasses the production writer on purpose), after which the index lands
    with the cutoff as its fence. Until then the advisory lock remains load-bearing and
    this docstring is the record of why.
    """

    __tablename__ = "credit_ledger"
    __table_args__ = (
        CheckConstraint(f"reason IN {CREDIT_REASONS!r}", name="reason_enum"),
        # The balance read (`_newest_balance`, and the credits panel behind it) is
        # `WHERE tenant_id = :tid ORDER BY occurred_at DESC, id DESC LIMIT 1`. This index
        # carries that ordering, so the plan walks to the newest row instead of sorting a
        # tenant's whole ledger to answer LIMIT 1. Declared with `text()` because the
        # DESC matters and is the point; autogenerate cannot diff expression indexes, so
        # migration a6f2e84b1d37 is the source of truth for its existence.
        Index(
            "ix_credit_ledger_tenant_recent",
            "tenant_id",
            text("occurred_at DESC"),
            text("id DESC"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Signed: a top-up is positive, usage is negative. One column, one sign convention,
    # no "type flips the meaning" bug at 2am.
    delta: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    # What caused it: a call id, a Razorpay payment id, an operator's note reference.
    ref: Mapped[str | None] = mapped_column(Text)
    balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# Referenced (not yet modeled — M2): invoices, engine_capacity.
