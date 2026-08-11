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

    **`(tenant_id, reason, ref)` is unique for entries at or after 2026-08-11 08:07 UTC**
    — migration f9c2b41a8e57, `ux_credit_ledger_tenant_reason_ref`, partial on
    `ref IS NOT NULL AND reason IN ('topup','usage','adjustment')`. Two facts about it
    are worth carrying next to the columns:

    - **`reason` is in the key, and `ref` alone is not unique.** Four earlier attempts
      proposed `UNIQUE (tenant_id, ref)` and all four were refused. `ref` is two
      namespaces in one column: a `usage` row carries a call id, a `topup` row carries
      whatever the bank printed, and `TopUpIn.payment_ref` accepts any 3-to-120-character
      string — a UUID among them. The platform TOLERATES that collision deliberately
      (`find_topup` and `charge_for_call` both scope their dedupe by reason), so a key
      without `reason` would turn a valid payment into a 500.
    - **It is partial on a cutoff**, because hard rule 4 forbids deleting the duplicates
      a pre-fix check-then-write race left behind. `scripts/reconcile_credit_ledger.py`
      repairs those balances with compensating entries and the duplicate rows REMAIN, so
      the residue is permanent and a full index could never build. The cutoff constant is
      `LEDGER_UNIQUE_INDEX_CUTOFF` in that script; the migration carries its own frozen
      copy and `tests/credit_ledger_unique_index_test.py` holds the two equal.

    The index is a backstop, not the primary guarantee: both dedupes are check-then-write
    under `lock_tenant_credits`, and `tests/credit_ledger_uniqueness_test.py` pins that
    the real writers cannot mint a duplicate key. What the index adds is protection from
    a FUTURE writer that forgets the lock — which is the failure mode an advisory lock
    can never cover, since it is only as good as every caller remembering it.
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
