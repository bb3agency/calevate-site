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
    # The second rung of D-36's TTS ladder, as a PRICE. `billing/rates.py` already
    # resolves every call to `premium` or `value` and stamps it on the usage row; this
    # is the only place billing can quote the two differently.
    #
    # **NULL means "this plan quotes no separate value rate" — bill everything at
    # `overage_rate`.** That is every plan row that existed before migration
    # b1d5c8e73f04, so the column changed no client's bill on the day it landed. It is
    # NOT "the value rate is zero": a rate of zero is free minutes, and an unset rate is
    # a plan that never offered a discount for the cheaper voice.
    #
    # No default is supplied and none should be guessed. TRD §10.1's cost bands are
    # explicitly unmeasured (the chars-per-minute ratio and the platform fee are both
    # pilot gates), so a retail number derived from them would be invention wearing a
    # citation. What goes here is a founder decision.
    overage_rate_value: Mapped[Decimal | None] = mapped_column(MONEY)
    # ADMIN-owned ceilings. The client cannot move these — that is what makes them a
    # ceiling rather than a suggestion.
    hard_cap_min: Mapped[int | None] = mapped_column(Integer)
    hard_cap_spend: Mapped[Decimal | None] = mapped_column(MONEY)
    # CLIENT-owned ceilings (D-34 R-11, SURFACES §2b:89). A client may set these as low
    # as they like — including 0, which is "stop my outbound calling now" — and may
    # never set one looser than the admin's. The EFFECTIVE cap is the stricter of the
    # pair, derived and never stored: `apps/api/billing/caps.py` holds that expression
    # once, and both the meter and the client route read it from there.
    client_cap_min: Mapped[int | None] = mapped_column(Integer)
    client_cap_spend: Mapped[Decimal | None] = mapped_column(MONEY)
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

    **Two writers, and the second one exists because the first cannot clear the flag.**
    The meter is the writer that ARMS it, and a capped tenant meters nothing — so on the
    meter alone the flag can never clear itself. Both readers therefore check `month` as
    well: a cap belonging to a closed billing month is not a cap, without which an
    outbound-only tenant capped in July would be refused every dial in August with no
    call able to complete and clear it.

    `billing.caps.apply_client_caps` is the second writer. It recomputes `capped` from
    the counters ALREADY in the row — it writes only the flag, only for the current
    month, and never moves a total — so a client who lowers their own cap is stopped on
    the next dial rather than the dial after the next call happens to meter, and a client
    who raises it is released the same way. Both writers derive the flag from the one
    shared `over_cap_sql`, which is what stops two writers becoming two definitions.

    Known dead end, not yet closed: ops has no writer at all. Raising `plans.hard_cap_*`
    through the audited admin path does not recompute the flag, so a capped
    outbound-only tenant stays blocked until the client themselves calls
    `PUT /v1/billing/caps` — which `org:manage` being in MUTATING_PERMISSIONS stops an
    impersonating admin doing for them — or the IST month rolls over. An ops-realm
    recompute is what closes it; `runbooks/calls-stopped.md` documents the workaround.
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
