"""Billing & metering (DATA-MODEL §8). Money = NUMERIC(12,4) INR, never floats
(hard rule 7). usage_events is INSERT-only — the immutability trigger ships in the
same migration; fixes are compensating entries."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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

# NO `PLAN_TIERS` HERE. It was declared in this file too — the identical three-tuple, three
# hundred lines from the one in `tenancy/models.py` that the `plan_tier` CHECK is built
# from — and NOTHING imported it (D-192, `grep -rn PLAN_TIERS apps packages tests scripts`).
# Two spellings of one enum is a defect while they still agree, and this copy was the one
# that could drift silently because no constraint and no test read it. The column lives on
# `organizations`, so its vocabulary lives with that model; billing reads the tier off the
# row like everything else.
#
# D-34 runs BOTH motions on ONE product: a self-serve org is the same `organizations` row as
# a managed one, distinguished by that column, so nothing forks.
# `bonus` (added for credit packs) is credit we FUND, not money that arrived: a volume
# bonus granted on a prepaid pack (`billing/credit_packs.py`). It is a distinct reason
# rather than a second `topup` because `service.PAYMENT_REF_SQL`/reconciliation treats every
# `topup` row as part of a bank transfer, and a promotional grant is not one — folding it
# into `topup` would make the wallet claim a bank moved more than it did. It carries the
# payment id it was earned on as its `ref` (idempotent, `ux_credit_ledger_bonus_ref`).
CREDIT_REASONS = ("topup", "usage", "adjustment", "refund", "bonus")

# The DASHBOARD-AI units (D-127 G-3, migration e1a7c93d5b02). Their own unit types
# rather than a second meaning for the call-leg ones, and the reason is arithmetic
# rather than tidiness: `llm_tok_out` is written by `apps/workers/pipeline.py::_meter`
# as `qty = 1` meaning "one call's LLM leg" priced at the whole leg cost, because the
# engine bills legs with no token count (TRD §5). Metering real tokens into that column
# would put two units in one column and quietly change what `billing/service.py`'s cost
# sums mean. `llm_tok_in` was the other candidate and is worse: it has no writer at all,
# so it carries no meaning to preserve AND its emptiness is a live finding (PLAN Part 18
# owns it) that a new writer would erase without fixing.
#
# **`ktok`, NOT `tok`, and that is a MONEY decision, not a naming one.** `unit_cost_paid`
# is NUMERIC(12,4) and every reader multiplies it by `qty`, so the smallest non-zero
# price this ledger can express is ₹0.0001 per unit of qty. `gpt-4o-mini` input is $0.15
# per 1M tokens — ₹0.0000143 a token at ₹95.66/USD — which stores as 0.0000, so a
# per-TOKEN qty would meter the input leg of every dashboard assist at exactly zero
# rupees. The OUTPUT leg is the one worth spelling out because it looks survivable and is
# not: ₹0.0000574 a token stores as 0.0001, which is not zero and is the price WRONG BY
# 74% — over-stated here rather than discarded, which is no better on a ledger. Per
# THOUSAND tokens the two are ₹0.0143 and ₹0.0574, which the column holds with digits to
# spare. What the ₹0.0001/1k quantum costs is stated where it lands: it bounds the error
# on OUR OWN absorbed cost at 0.7% of the input rung, and no client-visible rupee is ever
# derived from it — past the quota a client is charged a FIXED block
# (`billing/ai_quota.py`), never a token count.
#
# THE FIGURES ABOVE HAVE MOVED THREE TIMES AND D-410 REVERSED THEIR DIRECTION. They were
# 3.1 Flash-Lite's ($0.25/$1.50, 30% wrong on the output leg), then `gemini-2.5-flash`'s
# ($0.30/$2.50, 16%) — and the note here read "the argument for counting in thousands gets
# weaker as the output price RISES". Azure OpenAI is cheaper, so the argument got stronger
# again: 74% on `gpt-4o-mini` and 31% on `gpt-4.1-mini`, whose $0.40/$1.60 is the dearest
# of the two models `azure_openai_model` selects between. The claim to re-argue rather than
# re-state, the day it comes due, is unchanged — a model whose output rounds to within a
# few percent of its per-token price would make this paragraph wrong. The prices themselves
# live in ONE place, `billing/rates.py::llm_inr_per_ktok(model)`, with their source;
# `tests/ai_quota_test.py` holds this paragraph to the arithmetic ON BOTH MODELS.
AI_ASSIST_UNIT_TYPES = ("ai_assist_ktok_in", "ai_assist_ktok_out")

# WHO PAYS FOR A ROW OF THIS UNIT — the one question every reader of `usage_events` has
# to answer, and until now the only place it was answered was a NEGATIVE predicate in
# `billing/service.py` (`_NOT_AI_UNITS`). Negative is the safe DIRECTION — a unit added
# tomorrow lands in the client's own cost rather than vanishing out of it, and a client
# under-charged is recoverable where a client over-charged is a dispute — but it is
# also silent: the author of the eleventh unit type never has to decide, and the default
# they get by saying nothing may be the wrong one for what they added.
#
# So the enum is DERIVED from the classification instead of the classification being
# derived from the enum. There is no longer a place to add a unit type without saying
# which side of the money it falls on, which is the whole of the guarantee — an
# `assert` further down the file would only have said so after the fact.
#
# Order is preserved exactly as it was: `UNIT_TYPES` is rendered verbatim into
# `ck_usage_events_unit_type_enum`, and reordering it would make every autogenerate diff
# propose rewriting a CHECK constraint for nothing.

#: Units a CLIENT is billed for and sees in their own spend, margin and invoice.
CLIENT_BILLED_UNIT_TYPES = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
)

#: Units CALEVATE absorbs (D-127 G-3): metered per tenant so "which client is expensive"
#: stays a query, and excluded from every client-facing rupee figure.
PLATFORM_ABSORBED_UNIT_TYPES = AI_ASSIST_UNIT_TYPES


def assert_units_are_disjoint(billed: tuple[str, ...], absorbed: tuple[str, ...]) -> None:
    """A unit type may be billed to a client OR absorbed by us, never both.

    Both lists would put it in the CHECK constraint twice, and — the half that costs
    money — `_tier_totals`'s split would count it on both sides of the margin.

    A FUNCTION rather than the `if` that used to sit here at module scope. That `if` was
    unreachable while the two tuples are disjoint, so it could only be written with a
    coverage-exclusion comment — and the ratchet counts an excluded unit AS uncovered,
    precisely so that suppressing a branch is not a way to stop owning it (D-29). The
    rule is the same either way; what changes is that a test can now hand it a colliding
    pair and watch it raise, on a `ledgers-and-money` surface whose budget is 1 and where
    an unproved guard is worth very little.

    (This paragraph does not spell that comment out, and that is not squeamishness:
    `coverage`'s `exclude_lines` is a regex over SOURCE LINES and does not care that it
    is reading a docstring, so naming the marker here excluded this very function and
    put the ratchet back where it started — the same trap `check_model_residency` hit
    when its docstring named the hosts it bans, and the reason that guard parses an AST
    rather than grepping.)

    Raised rather than asserted: `python -O` strips an assert, and this one is a money
    boundary. Still called at import, so a bad edit fails the process rather than the
    first invoice of the month.
    """
    both = sorted(set(billed) & set(absorbed))
    if both:
        raise RuntimeError(f"a usage unit type is both client-billed and platform-absorbed: {both}")


UNIT_TYPES = (*CLIENT_BILLED_UNIT_TYPES, *PLATFORM_ABSORBED_UNIT_TYPES)

assert_units_are_disjoint(CLIENT_BILLED_UNIT_TYPES, PLATFORM_ABSORBED_UNIT_TYPES)

MONEY = Numeric(12, 4)


class UsageEvent(PKMixin, Base):
    """Append-only ledger. Records OUR cost (unit_cost_paid) next to billable qty —
    per-client margin is a query (D-12). Maps 1:1 onto Get Call's cost.breakdown.

    TWO KINDS OF ROW, TWO DISJOINT UNIQUE KEYS, AND THE DISJOINTNESS IS THE DESIGN.

    A CALL row carries `call_id` and no `ref`; a DASHBOARD-AI row carries `ref` and no
    `call_id`. `ux_usage_events_tenant_call_unit` (migration b8d3f47c2a19) is partial on
    `call_id IS NOT NULL` and `ux_usage_events_tenant_unit_ref` (migration e1a7c93d5b02)
    is partial on `ref IS NOT NULL AND call_id IS NULL`, so **no row is in both indexes
    and no row is in neither by accident** — which is what stops the second key from
    shadowing the first and stops an AI row from colliding with a call row that happens
    to share a unit type. It is also why the AI writer could not simply be added to the
    older index's `unit_type IN (...)` list: that index's leading key is `call_id`, and
    a row with a NULL there is not "unprotected", it is EXCLUDED by predicate — every
    duplicate would have been legal and invisible.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(f"unit_type IN {UNIT_TYPES!r}", name="unit_type_enum"),
        # Declared here so autogenerate does not propose dropping it; CREATEd
        # CONCURRENTLY by migration e1a7c93d5b02, which is the source of truth for its
        # predicate. The predicate is repeated VERBATIM by the writer's `ON CONFLICT`
        # as an index_predicate — Postgres will not infer a partial index otherwise
        # (postgresql.org/docs/16/sql-insert.html, "unique index inference").
        Index(
            "ux_usage_events_tenant_unit_ref",
            "tenant_id",
            "unit_type",
            "ref",
            unique=True,
            postgresql_where=text("ref IS NOT NULL AND call_id IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))
    unit_type: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_cost_paid: Mapped[Decimal | None] = mapped_column(MONEY)
    # THE IDEMPOTENCY KEY for a row that has no call to be keyed by, and it is minted by
    # the SERVER, once per attempt (`billing/ai_quota.py::new_assist_ref`). The partial
    # unique index above makes a second write of the same attempt a no-op in the DATABASE
    # rather than in a reader's `if` — the same doctrine
    # `ux_one_time_charges_tenant_kind_ref` states.
    #
    # This note used to read "the caller mints one `ref` per request and re-sends it",
    # meaning a browser could supply it so that a double-click deduped. That is a hole
    # rather than a feature: no-op-on-duplicate means NOT METERED, so a caller that
    # chooses its own key can spend Calevate's AI credential without moving its quota or
    # the platform brake. Double-click protection belongs at the endpoint and BEFORE the
    # model runs; deduping after the provider is paid hides the spend, it does not save
    # it. `ASSIST_REF_PREFIX` enforces the shape so the ambiguity is not re-readable.
    #
    # NULL on every call row, deliberately: a call already has a stronger key
    # (`call_id`), and a second one would be two ways to say one thing.
    ref: Mapped[str | None] = mapped_column(Text)
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
    # WHAT A CLIENT PAYS, PER MINUTE, FOR CHOOSING A DEARER LANGUAGE MODEL (D-455,
    # migration e4a91c6b02d7). D-454 gave them the choice; this is the only place billing
    # can put a price on it. `billing/rates.py::llm_surcharge_applies` decides WHICH
    # minutes carry it, from the ledger's own `meta.llm_model` / `meta.llm_model_source`
    # stamp and never from `agents.llm_model` — the live column would re-price every
    # closed month the day a client switched.
    #
    # **IT ADDS TO `overage_rate`, it does not replace it.** The plan's per-minute rate is
    # the base and the base-rate model (`rates.BASE_RATE_LLM_MODEL`) carries no surcharge
    # at all, which is what makes the column safe on a live database: every plan that
    # existed before it is NULL and bills exactly as it did.
    #
    # **NULL means "this plan quotes no model surcharge"** — an upgraded minute is billed
    # at `overage_rate` like any other. It is NOT "the surcharge is zero": giving the
    # better model away is a decision, never having been asked is not. The number is a
    # founder decision and no default is invented here, for `overage_rate_value`'s reason.
    llm_model_surcharge: Mapped[Decimal | None] = mapped_column(MONEY)
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


class OneTimeCharge(PKMixin, Base):
    """Charges that are billed ONCE and are not usage — today only `plans.setup_fee`.

    Append-only (hard rule 4), and it is a LEDGER rather than a flag column for the
    reason `credit_ledger` is: an invoice here is a DERIVED statement
    (`billing/invoice.py`), so anything it prints has to be re-derivable, and "has this
    tenant's setup fee been billed?" is a fact that must survive the invoice being
    regenerated, the plan being re-priced and the tenant being re-onboarded. A boolean
    on `plans` would move with the plan row; a row here is the tenant's own history.

    **`ux_one_time_charges_tenant_kind_ref` is what makes ONCE provable.** The writer
    (`billing/charges.py`) does an unconditional `INSERT … ON CONFLICT DO NOTHING` on
    `(tenant_id, kind, ref)`; there is no `WHERE NOT EXISTS` read-then-write anywhere on
    the path, so two invoice generations racing on the same tenant-month cannot both
    append (BACKEND-PATTERNS §5 — the guard is IN the write). The loser blocks on the
    index until the winner commits and then writes nothing.

    `ref` is in the key, not just `kind`, so hard rule 4 keeps its escape hatch: a setup
    fee that has to be undone is a NEW row (a negative amount under its own `ref`) which
    the same invoice prints as a credit line, never an edit or a delete of this one.

    `billing_month` is WHICH STATEMENT the charge belongs to, and it is not derivable
    from `occurred_at`: the fee belongs to the tenant's onboarding month, while
    `occurred_at` is the moment we recorded it — which is later, and possibly much later
    if that month's invoice is first rendered in arrears. Same separation, and the same
    reason, as `record_tier_correction` stamping the original call's month.

    `amount` is the fee AS BILLED, copied from the plan at the moment of billing rather
    than read back through the plan each time. `plans` rows are mutable, so a derived
    amount would let an edit today change a statement a client already paid.
    """

    __tablename__ = "one_time_charges"
    __table_args__ = (
        CheckConstraint("kind IN ('setup_fee')", name="kind_enum"),
        # ONCE, enforced by the database rather than by a reader's `if`.
        Index("ux_one_time_charges_tenant_kind_ref", "tenant_id", "kind", "ref", unique=True),
        # The invoice's read: this tenant's charges for one billing month.
        Index("ix_one_time_charges_tenant_month", "tenant_id", "billing_month"),
    )

    # No `index=True`: the composite above leads with this column, so a single-column
    # index would be a strict prefix that no query can use (the argument migration
    # e7c3d10a9f52 records for `credit_ledger`), and this table is append-only too.
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # The dedupe key WITHIN a kind. `'onboarding'` for the setup fee: one onboarding per
    # tenant, so one setup charge per tenant.
    ref: Mapped[str] = mapped_column(Text, nullable=False)
    # What the invoice line says. Stored rather than derived from `kind` so a manually
    # appended compensating row can explain itself on the client's statement.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Signed like `credit_ledger.delta`: a charge is positive, a reversal negative.
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    billing_month: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM' (IST)
    # Which plan row quoted the amount — provenance for a client who asks why.
    plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


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

    **Three writers, and the other two exist because the meter cannot clear the flag.**
    The meter is the writer that ARMS it, and a capped tenant meters nothing — so on the
    meter alone the flag can never clear itself. Both readers therefore check `month` as
    well: a cap belonging to a closed billing month is not a cap, without which an
    outbound-only tenant capped in July would be refused every dial in August with no
    call able to complete and clear it.

    The other two both go through `billing.caps.recompute_capped`, which recomputes
    `capped` from the counters ALREADY in the row — writing only the flag, only for the
    current month, never moving a total:

    - the CLIENT's `PUT /v1/billing/caps` (`caps.apply_client_caps`), so a client who
      lowers their own cap is stopped on the next dial rather than the dial after the
      next call happens to meter, and a client who raises it is released the same way;
    - OPS's `POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute` (step-up confirmed
      per tenant, audited), which is what an operator runs after raising
      `plans.hard_cap_*` on the audited admin path. Raising a ceiling does not by itself
      release a derived flag, and the client's route needs `org:manage` — in
      MUTATING_PERMISSIONS, so an impersonating admin (D-22) cannot press it for them —
      which used to leave a capped outbound-only tenant stopped until they acted or the
      IST month rolled over. `runbooks/calls-stopped.md` §2 walks the procedure.

    All three derive the flag from the one shared `over_cap_sql`, which is what stops
    three writers becoming three definitions. There is deliberately no writer anywhere
    that sets `capped` directly.
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
    #: What the CLIENT owes for this month, at the CLIENT's rate — the other half of
    #: P1.3, and the number the compliance gate's ceiling, the client's own cap route and
    #: the client usage panel all compare against. `spend_used` above is what the ENGINE
    #: charged US; keeping both is what makes margin (`billed - paid`) answerable at all,
    #: including retrospectively.
    #:
    #: SAME TYPE AS `spend_used` EXACTLY (`MONEY` is NUMERIC(12,4)): the two are compared
    #: against caps by one expression and summed onto one screen, and a pair of money
    #: columns with different scales is how a rounding difference becomes a support
    #: ticket (hard rule 7).
    #:
    #: Declared here in the same sweep that closed P4.3's other seven — and it was the
    #: EIGHTH instance, created by migration `c4f18a6b90e2` in this same session and
    #: missed. That is the argument for the guard rather than the list: a rule kept by
    #: remembering is a rule that fails on the next migration, and this one failed on the
    #: one being written while the rule was being read.
    billed_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
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

    **`refund` HAS THAT BACKSTOP GAP TODAY, AND IT IS NAMED HERE RATHER THAN LEFT TO BE
    REDISCOVERED.** Five reasons exist; three are covered by the index above and `bonus`
    by `ux_credit_ledger_bonus_ref` (migration c3a9f1e6b820, partial on
    `reason = 'bonus'`). `refund` is covered by NEITHER, and it is not keyless — a
    `payments.credit_refund` row carries the PROVIDER'S REFUND ID as its `ref`, which is
    a perfectly good unique key (partial refunds carry different refund ids, so they
    separate exactly as two top-ups do). The reason for the gap is chronological, not
    principled: `f9c2b41a8e57` predates the refund writer. Nothing is loose today —
    `credit_refund` takes `lock_tenant_credits` BEFORE its `find_entry_by_ref` and is the
    only writer of the reason — so the exposure is precisely the one the paragraph above
    says the index exists for, and no more. Closing it is a partial unique index on
    `(tenant_id, ref) WHERE reason = 'refund' AND ref IS NOT NULL`, in its own migration.
    `tests/credit_ledger_unique_index_test.py` carries both halves: the pin that refund is
    absent from the older predicate, and the pin that its rows really do carry a ref — the
    fact whose earlier denial is what let this look harmless.
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

    # NO `index=True`, deliberately: the composite above already leads with this column,
    # so a single-column index on it is a strict PREFIX and adds nothing a query can
    # use. Migration e7c3d10a9f52 dropped `ix_credit_ledger_tenant_id` for that reason
    # (step two of a6f2e84b1d37's two-step deprecation, hard rule 8), and `index=True`
    # left here would have autogenerate recreate it at the next revision. On an
    # append-only table a second index is a write cost with no read to pay it back.
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
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


class PlatformAiSpend(Base):
    """WHAT THE DASHBOARD-AI KEY HAS COST **US** THIS MONTH, across every tenant.

    G-3 says Calevate owns the dashboard-AI credential and absorbs the cost — Azure
    OpenAI in `AZURE_LOCATION` since D-410, and this sentence said "the Gemini
    credential" for long enough that the pricing block at the top of this same file had
    already been re-argued for `gpt-4o-mini` while this one had not. The VENDOR is named
    where the vendor is decided (`workers/extraction.py::azure_credentials`) rather than
    restated on an ORM row, because that is the half that moves. That makes an
    unbounded bug a bill addressed to us, and no per-tenant quota can see it: a hundred
    tenants each politely inside their own ceiling is still a hundred ceilings of our
    money. This row is the brake that is independent of all of them
    (`billing/ai_quota.py::platform_brake_tripped`).

    WHY A TABLE AND NOT A SUM OVER `usage_events`. The obvious implementation — sum the
    AI rows across all tenants — is **unaskable in app code**. `usage_events` is FORCE
    RLS'd, an untenanted session sees zero rows by design (`db/session.py`), and hard
    rule 1 forbids reaching for the admin DB role to get around that. So the platform's
    own total has to be maintained where a tenant transaction can write it and any
    session can read it: no `tenant_id`, no policy, exactly the shape `platform_state`
    and `platform_settings` already have and for the same reason.

    WHY NOT A COLUMN ON `platform_state`. That row is the load-shed mode and the big red
    switch — read on every dispatch tick by every tenant. Incrementing it on every
    console button press would serialize an unrelated hot path behind an AI counter.
    Keyed by MONTH here, so the contended row is one per month and rolls over on its own
    instead of needing a reset job.

    NOT append-only, and it must not be: it is a counter, not a ledger. The LEDGER is
    `usage_events` — every rupee counted here is re-derivable from the per-tenant rows
    that produced it, which is what makes a counter safe to keep. `requests` is carried
    beside the money because a brake that has tripped needs an operator to be able to
    tell a price spike from a request storm without opening a psql.
    """

    __tablename__ = "platform_ai_spend"

    # IST billing month, 'YYYY-MM' — the same month `billing/service._IST_MONTH` cuts
    # the per-tenant rows on, so the platform total and the tenant totals close on the
    # same instant.
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    spend_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False, server_default="0")
    requests: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PlatformAiUsage(PKMixin, Base):
    """One metered unit of AI spend the PLATFORM paid for, with no tenant behind it (D-499).

    THE SECOND AI LEDGER, and it exists because the first one has a tenant in its primary
    key. `usage_events` is FORCE RLS'd and tenant-scoped; an operator asking the admin
    copilot a question has no tenant at all, so their spend has exactly three possible
    homes and two of them are wrong — a client's ledger (which is charging somebody for our
    own support work), nowhere (hard rule 7, in as many words), or here.

    SAME UNITS, SAME SCALE, SAME `ref` DISCIPLINE as the tenant ledger, deliberately:
    `AI_ASSIST_UNIT_TYPES` on both, `MONEY` on both, and a server-minted `assist:<uuid>`
    key on both — enforced HERE by `ck_platform_ai_usage_ref_shape` in the database as
    well as by `ai_quota._ASSIST_REF_RE` in Python, because `ref` is the meter's off
    switch and a caller-chosen key is a way to spend our credential for free.

    `admin_user_id` is the attribution `usage_events` has no equivalent for. A tenant's
    assist is the tenant's, whichever member clicked; here the payer is the platform, so
    the operator is the only answer to "who spent this" worth recording.

    `viewing_tenant_id` IS NOT A PAYER and nothing prices it. It records the account an
    operator had open — a tenant admin page, or a D-22 view-as session — so "what did we
    spend supporting this client" is a query rather than an archaeology. SET NULL on
    delete: platform accounting outlives the account it was about.

    Append-only (migration `f2c81a4d05e7`, `db/registry.APPEND_ONLY_TABLES`). Unlike
    `PlatformAiSpend` above — which is a COUNTER and re-derivable — this is the ledger the
    counter is derived from, so hard rule 4 binds it exactly as it binds `usage_events`.
    """

    __tablename__ = "platform_ai_usage"

    admin_user_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    viewing_tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    unit_type: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unit_cost_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ref: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: Ids, a model name and a feature name. Never a prompt and never an answer (rule 6).
    meta: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("qty >= 0", name="qty_not_negative"),
        CheckConstraint("unit_cost_paid >= 0", name="cost_not_negative"),
        CheckConstraint(
            "ref ~ '^assist:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name="ref_shape",
        ),
        Index("ux_platform_ai_usage_unit_ref", "unit_type", "ref", unique=True),
        Index(
            "ix_platform_ai_usage_occurred",
            text("occurred_at DESC"),
            "admin_user_id",
        ),
    )


class PlatformListRate(Base):
    """One published list rate, and the instant it came into force (D-492).

    THE SELF-SERVE MINUTE PRICE ACQUIRES A VALID TIME. `Settings.self_serve_inr_per_min` is
    one number with no history — `platform_settings` is keyed by `key`, so an operator's
    change OVERWRITES the row — and two money readers were asking it a question it cannot
    answer: `billing/service.calling_revenue_inr` re-priced a CLOSED month's minutes at
    today's setting, and `workers/pipeline` debited a LATE-SETTLING call at next month's.
    A row here says what the rate was, from when.

    APPEND-ONLY (hard rule 4) and effective-dated, which here is one property: a correction
    is a NEW row at a distinct `effective_from`, never an edit, so a statement re-rendered a
    year later resolves the figure it was struck at. The trigger is the blanket
    `calevate_forbid_mutation` with no carve-out — unlike `platform_secrets`, nothing in this
    table ever needs an in-place edit.

    NOT tenant-scoped and never will be: one published price for the whole self-serve motion
    at an instant, and a MANAGED client's price is their `plans` row rather than this. It is
    `platform_*`-named for the family it belongs to and registered in
    `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason (the RLS sweep's
    rule 7a REQUIRES a `platform_*` table to appear there).

    Declared as an ORM model so `Base.metadata` knows about it and `check_rls_coverage` can
    compare the live schema against it; `billing/list_rates.py` is the reader and the writer,
    and it uses SQL text like every other money reader in this package.
    """

    __tablename__ = "platform_list_rates"

    #: WHICH published rate this row dates — the name of the `Settings` field it mirrors, so
    #: nothing has to guess the relation. Text and not an enum for `platform_model_prices
    #: .model`'s reason: a figure read back for a historical statement must resolve even for
    #: a key this build no longer carries. Today there is exactly one,
    #: `billing/list_rates.SELF_SERVE_PER_MIN`.
    rate_key: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The instant this figure becomes the published rate. Part of the PK with `rate_key`, so
    #: two writes at one instant collide rather than silently both existing. Resolution at
    #: instant T is this key's row with the greatest `effective_from <= T`
    #: (`ix_platform_list_rates_key`).
    effective_from: Mapped[datetime] = mapped_column(primary_key=True)
    #: INR, at `MONEY`'s scale — `usage_events.unit_cost_paid`'s storage precision, which is
    #: also what `billing/rates.prepaid_billed_inr` quantizes a wallet debit at, so the rate
    #: and the debit derived from it round in one place. NUMERIC, never a float.
    inr_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: The operator whose console write published it. NOT NULL, referencing `admin_users`
    #: exactly as `platform_settings.updated_by` does: every row here was typed by a person.
    recorded_by: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: WHY the price moved, in the operator's words — the `reason` the ops console already
    #: requires for the setting change this row dates.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


# Referenced (not yet modeled — M2): invoices, engine_capacity.
