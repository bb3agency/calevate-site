"""Dashboard AI: what it costs us, what a client gets free, and what happens at the
ceiling (D-127 — G-3, G-4, G-5).

G-3 puts ONE Calevate-owned Gemini credential behind every client's dashboard assist and
absorbs the cost. Three things follow from that sentence and this module is all three:

- **absorbed is not unmetered.** Every assist lands in `usage_events` under its own unit
  types, per tenant, priced with what it cost US — so "which client is expensive" is a
  query and not an argument (D-12's whole point about metering not being retrofittable).
- **absorbed needs a ceiling, or it is a blank cheque.** The ceiling is counted in
  RUPEES, per tenant per IST billing month, because rupees are what actually protect us:
  one 1M-token context costs what a hundred autofills do, so a request count is a
  ceiling that varies by two orders of magnitude depending on what people paste in.
- **and one client's ceiling protects nothing against a hundred clients**, so there is a
  second, platform-wide brake on our own key (`platform_brake`, below).

WHY THE SCREEN SHOWS BOTH A COUNT AND A CEILING, AND WHICH ONE IS REAL
----------------------------------------------------------------------
A rupee ceiling does the work; "82 of about 500 assists used" is what an owner can plan
around. Nobody can reason about ₹41.7 of ₹250 of language-model inference. So the count
is published as an ESTIMATE and says so — `requests_included` is the ceiling divided by
`AI_ASSIST_NOMINAL_INR`, a reference price, and the word "about" is in the copy on the
screen rather than only in this comment. The number that blocks is always the rupee one.

WHERE THE CEILING LIVES, AND THE MECHANISM THIS DELIBERATELY DOES NOT DUPLICATE
-------------------------------------------------------------------------------
`AI_QUOTA_INR` is a per-TIER platform term: every tenant on a tier gets the same
included allowance, because that is what "one key, cost absorbed" means today — it is
not a negotiated commercial term, and nobody has priced one.

So it is NOT a `plans` column, and the reasoning matters more than the conclusion:
`plans` is resolved by valid time (`billing/plans.py::plan_in_effect_sql` — the half-open
window, the total order, `month_pricing_instant`), and that is THE mechanism for anything
a client and Calevate agreed. The day a founder prices per-tenant AI quota, it becomes a
nullable `plans` column resolved by that same function and defaulting to the tier value
here when NULL — exactly the shape `plans.overage_rate_value` already has. What is
refused is a SECOND effective-dating mechanism for one more number, and what is refused
just as firmly is a column with no writer (`billing/terms.py` is the only writer of a
`plans` row, and a term no operator can type is a defect that looks like a feature).

The TIER itself comes from `billing.service.plan_tier_of`, the one reader of
`organizations.plan_tier` — the same one `usage_summary` and `charge_for_call` use.

PAST THE CEILING: A BLOCK, A MODAL, AND EXACTLY ONE LEDGER ROW (G-4, G-5)
-------------------------------------------------------------------------
At the ceiling the feature BLOCKS. It does not degrade, it does not silently bill, and
it does not queue: `require_ai_assist` raises, the screen opens a modal naming the exact
rupee figure, and **nothing leaves the wallet until a person presses accept**.

What they accept is a FIXED BLOCK (`AI_OVERAGE_BLOCK_INR`), debited once, as ONE
`credit_ledger` row with reason `usage` and `ref = ai_assist:<YYYY-MM>` — an existing
reason, no new table, deduped by the existing `ux_credit_ledger_tenant_reason_ref`
(D-63's key shape). Three alternatives were considered and each fails on hard rule 4:

- *bill each assist as it happens* — G-4 rules it out in words ("no per-request
  billing"), and it would put one ledger row per button press on a client's statement;
- *one row per month that grows as they spend* — an UPDATE on an append-only ledger,
  which the `calevate_forbid_mutation` trigger refuses outright;
- *a row per assist netted at month end* — the same thing with extra steps, and it
  charges money before anyone agreed to it.

A block is also the only shape that lets the modal state a TRUE figure before the click:
"₹500 now" is checkable; "about ₹0.05 per assist for the rest of the month" is not.
The cost of the shape, stated rather than hidden: an unused part of the block is not
refunded and does not roll into next month. The screen says so in those words.

ONE BLOCK PER TENANT-MONTH, and that is the exposure limit rather than a UI convenience.
When it is spent the feature blocks again and the client is told the month is finished —
not offered a second modal. So the worst case for a client who mis-clicks is one block,
and the worst case for US is the included quota plus one block per tenant.

**Prepaid tiers only** (`self_serve`, `trial`), which is the split
`billing.service.charge_for_call` and the top-up panel already make: a managed client is
invoiced against a retainer, their wallet is not the mechanism that pays for anything
(`usage_summary`: "their wallet must not shorten their runway any more than it blocks a
dial"), and this product has no way to put an ad-hoc charge on a DERIVED invoice without
inventing an invoice line nobody priced. A managed client at the ceiling is therefore
refused with their account manager named — bounded, visible, and closed by a founder
pricing AI overage on a retainer, not by code.

Money is NUMERIC INR throughout (hard rule 7). No float is constructed in this module,
and every rupee that reaches a response goes through `billing.service.to_paise`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.models import AI_ASSIST_UNIT_TYPES
from apps.api.billing.plans import parse_billing_month
from apps.api.billing.service import (
    _IST_MONTH,
    current_billing_month,
    find_entry_by_ref,
    lock_tenant_credits,
    plan_tier_of,
    record_entry,
    to_paise,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

# --- the numbers ---------------------------------------------------------------
#
# THESE ARE PRODUCT TERMS AND THEY ARE THE FOUNDER'S TO MOVE. They are constants rather
# than console fields on purpose: `platform_config.managed_fields()` computes the
# console's editable set from `Settings.model_fields`, so a field named
# `ai_quota_inr` would be editable from a web form the day it is declared — and what it
# governs is how much of OUR money a bug can spend. That is the doctrine
# `check_bootstrap_keys` applies to `APP_ENV` (D-95 §4) and `check_model_residency`
# applies to the Vertex region (D-127), applied to the third value whose change is a
# commercial event wearing a config diff. Moving one is a code change with a review.

#: Included dashboard-AI allowance per tenant per IST billing month, in rupees, by plan
#: tier. Managed clients get the most because they pay the most; a trial gets enough to
#: form an opinion of the feature and not enough to be a business's whole workload.
AI_QUOTA_INR: Final[dict[str, Decimal]] = {
    "managed": Decimal("250.00"),
    "self_serve": Decimal("100.00"),
    "trial": Decimal("25.00"),
}

#: The reference cost of one assist, used ONLY to turn a rupee ceiling into the "about N
#: assists" a person can plan around. It is not a price, nothing is charged at it, and no
#: rupee figure on any screen is derived from it — the estimate it feeds is rendered with
#: the word "about" beside it. Grounded on a Flash-Lite-class call of a few thousand
#: tokens in and a few hundred out; the real per-assist cost is metered per row.
AI_ASSIST_NOMINAL_INR: Final = Decimal("0.50")

#: What the modal offers past the ceiling, debited once per tenant-month. Chosen to be
#: worth buying (two blocks' worth of assists on the smallest tier) and small enough that
#: a mis-click is a bad afternoon rather than a dispute.
AI_OVERAGE_BLOCK_INR: Final = Decimal("500.00")

#: The brake on OUR key, across every tenant, per IST billing month. Independent of every
#: tenant's quota by construction: a hundred tenants each inside their own ceiling is
#: still a hundred ceilings of our money, and the failure this exists for — a retry loop
#: in a worker, a prompt that grew a zero — does not respect a per-tenant boundary.
#:
#: HOW IT IS RELEASED, said here rather than discovered at 3am: it clears when the IST
#: month rolls over, and before that ONLY by raising this constant — a code change with a
#: review. There is deliberately no button. A spend brake a console can lift is a spend
#: brake, and the run that tripped it is exactly the run nobody wants a tired person
#: waving through; when it fires, every refusal is a 503 and this repo's error ladder
#: already alerts on 5xx with a `failure_stage`, so an operator learns about it without a
#: screen of its own. What a released brake costs is bounded by the same constant on the
#: next tick, which is not true of a switch.
PLATFORM_AI_BRAKE_INR: Final = Decimal("25000.00")

#: The `credit_ledger.ref` namespace for the one overage row per tenant-month. `reason`
#: is part of the key too (`find_entry_by_ref`), so this cannot collide with the call ids
#: `charge_for_call` writes under the same reason.
OVERAGE_REF_PREFIX: Final = "ai_assist"

#: `meta.kind` on both the ledger row and the usage rows, so a reader who finds one
#: knows what produced it without joining anything.
OVERAGE_META_KIND: Final = "ai_assist_overage"
ASSIST_META_KIND: Final = "ai_assist"

#: One thousand tokens — the unit `ai_assist_ktok_*` counts, because a per-token price is
#: not representable in NUMERIC(12,4) (`billing/models.py::AI_ASSIST_UNIT_TYPES`).
TOKENS_PER_KTOK: Final = Decimal("1000")

PREPAID_TIERS: Final = ("self_serve", "trial")

QuotaState = Literal["within", "ceiling_reached", "exhausted", "platform_paused"]

#: Why the extra block is not on offer. `None` means it IS.
ExtraUnavailable = Literal["not_at_ceiling", "already_purchased", "not_prepaid", "platform_paused"]


def overage_ref(month: str) -> str:
    """The idempotency key for the one overage row of a tenant-month.

    Content-addressed over the MONTH and nothing else, which is what makes a double-click
    a no-op rather than a second ₹500 (the argument `billing.service.adjustment_ref`
    makes at length). It deliberately does NOT carry the amount: a key of
    `ai_assist:2026-08:500.00` would let a client who reloads into a changed
    `AI_OVERAGE_BLOCK_INR` buy a second block in the same month, which is exactly the
    exposure "one block per tenant-month" exists to bound.
    """
    return f"{OVERAGE_REF_PREFIX}:{month}"


# --- what a tenant's month looks like -------------------------------------------


@dataclass(frozen=True, slots=True)
class AiQuota:
    """One tenant's dashboard-AI month: what they used, what they have, what they may do.

    Every rupee field is an exact `Decimal` and stays one until the route stringifies it
    (hard rule 7). The derived properties are properties rather than stored fields so
    that no caller can be handed a state that disagrees with the numbers beside it.
    """

    month: str
    plan_tier: str
    #: The tier's included allowance for the month.
    included_inr: Decimal
    #: What this tenant's assists have cost US this month, summed from `usage_events`.
    used_inr: Decimal
    #: Distinct request keys this month — the number the screen counts in "82 of ~500".
    requests_used: int
    #: The block already bought this month, or zero. Read from `credit_ledger`, so the
    #: wallet row IS the record of the acceptance and there is no second state to keep
    #: in step with it.
    extra_purchased_inr: Decimal
    #: The platform-wide brake, which overrides everything below it.
    platform_paused: bool

    @property
    def allowance_inr(self) -> Decimal:
        return self.included_inr + self.extra_purchased_inr

    @property
    def remaining_inr(self) -> Decimal:
        return max(Decimal("0"), self.allowance_inr - self.used_inr)

    @property
    def at_ceiling(self) -> bool:
        return self.used_inr >= self.allowance_inr

    @property
    def state(self) -> QuotaState:
        if self.platform_paused:
            return "platform_paused"
        if not self.at_ceiling:
            return "within"
        # At the ceiling with the block already spent, there is nothing left to offer:
        # `exhausted` is the state the screen refuses in rather than asking again.
        return "exhausted" if self.extra_purchased_inr > 0 else "ceiling_reached"

    @property
    def requests_included(self) -> int:
        """About how many assists the ALLOWANCE is worth, at the reference price."""
        return int(self.allowance_inr // AI_ASSIST_NOMINAL_INR)

    @property
    def requests_remaining(self) -> int:
        return int(self.remaining_inr // AI_ASSIST_NOMINAL_INR)

    @property
    def extra_unavailable(self) -> ExtraUnavailable | None:
        """Why the modal's button is not on offer — checked in the order the SERVER
        refuses in, so the screen's explanation and the route's refusal cannot disagree.

        Published rather than left for the browser to infer from three other fields: a
        client who cannot buy needs the reason, and a second copy of this precedence in
        TypeScript is a second place for it to drift.
        """
        if self.platform_paused:
            return "platform_paused"
        if self.plan_tier not in PREPAID_TIERS:
            return "not_prepaid"
        if self.extra_purchased_inr > 0:
            return "already_purchased"
        if not self.at_ceiling:
            return "not_at_ceiling"
        return None


# WHAT THE MONTH'S ASSISTS COST US. `COUNT(DISTINCT ref)` is the request count and not a
# row count: one assist writes two rows (in and out) under one key, so counting rows
# would report double and counting one unit type would under-report an assist that
# produced no output tokens.
_USAGE_SQL = (
    "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0), COUNT(DISTINCT ref) "
    "FROM usage_events "
    "WHERE tenant_id = :tid AND unit_type = ANY(:units) AND ref IS NOT NULL "
    f"AND {_IST_MONTH} = :month"
)


async def read_ai_quota(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> AiQuota:
    """This tenant's dashboard-AI month, from the two ledgers that hold it.

    `tenant_id` is in the predicate as well as in RLS for the reason `usage_summary`
    gives: the answer should depend on the argument rather than on which session it was
    handed, and RLS still fails the query closed.

    The month is VALIDATED through the shared `parse_billing_month`, not re-parsed here —
    two panels reading one ledger must not disagree about what a month is, and a month we
    cannot parse is one we cannot honestly report a ceiling for.
    """
    period = month or current_billing_month()
    parse_billing_month(period)

    row = (
        await session.execute(
            text(_USAGE_SQL),
            {"tid": tenant_id, "units": list(AI_ASSIST_UNIT_TYPES), "month": period},
        )
    ).one()
    # `Decimal(str(...))` — never `Decimal(float)` — on the way out of NUMERIC, the same
    # discipline `billing/terms.py::_money` keeps.
    used = Decimal(str(row[0] or 0))
    requests = int(row[1] or 0)

    tier = await plan_tier_of(session, tenant_id)
    # The wallet row IS the acceptance record (module docstring), so this read answers
    # "has a person agreed to spend money on this month" with no second state.
    purchased = await find_entry_by_ref(
        session, tenant_id=tenant_id, reason="usage", ref=overage_ref(period)
    )
    # `delta` is signed and a debit is negative; the block is reported as a positive
    # amount because that is what the client bought.
    extra = -purchased.amount_inr if purchased is not None else Decimal("0")

    return AiQuota(
        month=period,
        plan_tier=tier,
        included_inr=AI_QUOTA_INR.get(tier, AI_QUOTA_INR["trial"]),
        used_inr=used,
        requests_used=requests,
        extra_purchased_inr=extra,
        platform_paused=await platform_brake_tripped(session, month=period),
    )


# --- the platform's own brake ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlatformAiSpend:
    month: str
    spend_inr: Decimal
    requests: int

    @property
    def tripped(self) -> bool:
        return self.spend_inr >= PLATFORM_AI_BRAKE_INR


async def read_platform_ai_spend(
    session: AsyncSession, *, month: str | None = None
) -> PlatformAiSpend:
    """What the dashboard-AI key has cost us this month, across every tenant.

    Reads `platform_ai_spend`, which carries no `tenant_id` and no policy, so this
    answers the same on a tenant-scoped session as on an untenanted one. That is the
    whole reason the table exists: the equivalent question asked of `usage_events` — sum
    the AI rows for all tenants — is unanswerable under FORCEd RLS without the admin DB
    role, which hard rule 1 forbids in app code.

    A month with no row is ₹0, not an error: nothing has been spent yet.
    """
    period = month or current_billing_month()
    row = (
        await session.execute(
            text("SELECT spend_inr, requests FROM platform_ai_spend WHERE month = :m"),
            {"m": period},
        )
    ).first()
    if row is None:
        return PlatformAiSpend(month=period, spend_inr=Decimal("0"), requests=0)
    return PlatformAiSpend(month=period, spend_inr=Decimal(str(row[0])), requests=int(row[1]))


async def platform_brake_tripped(session: AsyncSession, *, month: str | None = None) -> bool:
    return (await read_platform_ai_spend(session, month=month)).tripped


# The counter moves in ONE statement, so two tenants' assists landing at the same instant
# cannot both read a pre-increment total and both write it back (BACKEND-PATTERNS §5 —
# the guard is IN the write). `platform_ai_spend` is a counter and not a ledger, so an
# UPDATE here is correct and it is deliberately NOT in `APPEND_ONLY_TABLES`: every rupee
# it holds is re-derivable from the per-tenant `usage_events` rows that produced it.
_BUMP_PLATFORM_SQL = """
INSERT INTO platform_ai_spend (month, spend_inr, requests, updated_at)
VALUES (:month, :amount, :requests, now())
ON CONFLICT (month) DO UPDATE
   SET spend_inr = platform_ai_spend.spend_inr + EXCLUDED.spend_inr,
       requests  = platform_ai_spend.requests  + EXCLUDED.requests,
       updated_at = now()
"""


# --- metering an assist -----------------------------------------------------------
#
# THE PREDICATE BELOW IS COPIED FROM MIGRATION e1a7c93d5b02 CHARACTER FOR CHARACTER.
# Postgres infers a PARTIAL unique index only from an `ON CONFLICT` whose own predicate
# implies the index's (postgresql.org/docs/16/sql-insert.html, "unique index inference").
# A predicate that almost matches does not degrade — it raises `there is no unique or
# exclusion constraint matching the ON CONFLICT specification`, which is a 500 on a
# button a client just pressed. `tests/ai_quota_test.py` reads both and fails on drift.
#
# `DO NOTHING`, never `DO UPDATE`: `usage_events` is in `APPEND_ONLY_TABLES` and
# `DO UPDATE` fires `calevate_forbid_mutation`. The silence `b8d3f47c2a19` rejects
# `DO NOTHING` for is the right answer HERE and the wrong one there, and the difference
# is what a duplicate MEANS: on the call path it means two runs interleaved and wrote a
# partial row set, which must abort; here it means the same button was pressed twice,
# which must be a no-op. `RETURNING id` is what tells the two apart at the call site.
INDEX_PREDICATE: Final = "ref IS NOT NULL AND call_id IS NULL"

_INSERT_USAGE = f"""
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          ref, occurred_at, meta, created_at)
VALUES (:id, :tid, NULL, :unit, :qty, :cost, :ref, now(), CAST(:meta AS jsonb), now())
ON CONFLICT (tenant_id, unit_type, ref) WHERE {INDEX_PREDICATE}
DO NOTHING
RETURNING id
"""


@dataclass(frozen=True, slots=True)
class AssistMetered:
    """What `record_ai_assist_usage` did.

    `recorded` is False for a replay — the same `ref` already metered — which is the
    normal outcome of a double-click and not an error. `cost_inr` is what was actually
    added to the ledgers on THIS call, so a replay reports zero and a caller can never
    charge the platform counter twice for one assist.
    """

    recorded: bool
    cost_inr: Decimal


def ktok(tokens: int) -> Decimal:
    """Tokens as thousands, exactly. `Decimal` division by a `Decimal` — never `/ 1000.0`,
    which would put a metering quantity through a binary float."""
    return Decimal(tokens) / TOKENS_PER_KTOK


async def record_ai_assist_usage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    ref: str,
    tokens_in: int,
    tokens_out: int,
    price_in_inr_per_ktok: Decimal,
    price_out_inr_per_ktok: Decimal,
    model: str,
    feature: str,
) -> AssistMetered:
    """Meter one dashboard assist: two `usage_events` rows and the platform counter.

    THE ONLY WRITER of `ai_assist_ktok_*`. It is idempotent on `ref` in the DATABASE
    (`ux_usage_events_tenant_unit_ref`), not in a reader's `if`, because the failure it
    has to survive is a second click — and a check-then-write would let two clicks both
    read "not metered yet". That is the same hole `charge_for_call` takes an advisory
    lock to close; here the unique index closes it with no lock at all, which is what a
    natural key buys.

    The platform counter is bumped ONLY for rows that actually landed, so a replay adds
    nothing to the brake. Both halves commit in the CALLER's transaction: a metered
    assist whose platform total did not move is not a reachable state.

    `model` and `feature` go into `meta` so that "which surface spent this" is a query.
    No prompt, no completion, no transcript and no identifier of a person is written
    here (hard rule 6) — a token COUNT is not content.
    """
    meta = json.dumps({"kind": ASSIST_META_KIND, "model": model, "feature": feature, "ref": ref})
    rows = (
        ("ai_assist_ktok_in", ktok(tokens_in), price_in_inr_per_ktok),
        ("ai_assist_ktok_out", ktok(tokens_out), price_out_inr_per_ktok),
    )
    landed = Decimal("0")
    recorded = False
    for unit, qty, price in rows:
        inserted = (
            await session.execute(
                text(_INSERT_USAGE),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "unit": unit,
                    "qty": qty,
                    "cost": price,
                    "ref": ref,
                    "meta": meta,
                },
            )
        ).first()
        if inserted is not None:
            recorded = True
            landed += qty * price

    if recorded:
        await session.execute(
            text(_BUMP_PLATFORM_SQL),
            {"month": current_billing_month(), "amount": landed, "requests": 1},
        )
        log.info(
            "ai_assist_metered",
            # Ids, a model name and a rupee total. No tenant name, no prompt, no output.
            extra={
                "tenant_id": str(tenant_id),
                "ref": ref,
                "model": model,
                "feature": feature,
                "cost_inr": str(landed),
            },
        )
    return AssistMetered(recorded=recorded, cost_inr=landed)


# --- the gate ----------------------------------------------------------------------


async def require_ai_assist(session: AsyncSession, *, tenant_id: UUID) -> AiQuota:
    """May this tenant run a dashboard assist right now? Returns the quota, or REFUSES.

    THE ONE PLACE that decides, so a second surface cannot answer differently — the same
    doctrine `compliance.service.check_dispatch` keeps for a dial. Every refusal carries
    a `remediation` the client can act on, and the browser switches on `code`:
    `ai_quota_exceeded` is what opens the modal.

    The numbers the modal shows are deliberately NOT stuffed into the problem body. The
    screen re-reads `GET /v1/billing/ai-quota`, which is the same computation this
    function used, so the figure a person is asked to accept can never be a stale copy
    carried in an error. RFC-9457 extensions were the alternative and would have made
    the modal's amount a second source of truth.
    """
    quota = await read_ai_quota(session, tenant_id=tenant_id)

    if quota.platform_paused:
        # `transient`/503 — the ONE status this repo's error ladder lets keep its
        # detailed message, and the honest kind: it clears when an operator raises the
        # brake or the month rolls over. NOT a 500: nothing is broken, we stopped it.
        raise ProblemError(
            kind="transient",
            code="ai_paused_platform_wide",
            title="AI help is paused",
            detail=(
                "AI help is paused across Calevate while we check unusually high usage. "
                "Your calls, campaigns and leads are unaffected."
            ),
            remediation="Try again later, or ask your account manager for an update.",
        )

    if not quota.at_ceiling:
        return quota

    if quota.extra_purchased_inr > 0:
        raise ProblemError.business_rule(
            "ai_quota_exhausted",
            (
                "This account has used all of this month's AI help, including the extra "
                "you added. It resets at the start of next month."
            ),
            remediation=("Talk to your account manager if you need more AI help before then."),
        )

    if quota.plan_tier not in PREPAID_TIERS:
        raise ProblemError.business_rule(
            "ai_quota_exceeded_invoiced",
            (
                "This account has used all of this month's included AI help. It resets "
                "at the start of next month."
            ),
            remediation=("Talk to your account manager to add more AI help to this month's plan."),
        )

    raise ProblemError.business_rule(
        "ai_quota_exceeded",
        (
            "This account has used all of this month's included AI help. You can add "
            "more from the AI assistance screen."
        ),
        remediation=(
            "Open AI assistance to see what more AI help costs and to add it, or wait "
            "for the allowance to reset at the start of next month."
        ),
    )


# --- buying the block (G-5) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtraPurchase:
    """The outcome of an acceptance. `charged` is False on a replay — the same month's
    block was already bought — and the caller audits only a real change, the convention
    `billing/terms.py::TermsWriteResult` and `kb.approve_source` established."""

    charged: bool
    amount_inr: Decimal
    quota: AiQuota


async def purchase_ai_overage(
    session: AsyncSession, *, tenant_id: UUID, accepted_amount_inr: Decimal
) -> ExtraPurchase:
    """Debit the one block this tenant-month may buy — AFTER a person accepted it.

    `accepted_amount_inr` is what the modal SHOWED, echoed back, and it is compared
    against `AI_OVERAGE_BLOCK_INR` before anything moves. That is the client-realm form
    of the `X-Confirm-Action` double-key the admin credit routes use, and it exists for
    the same failure: a screen left open across a price change would otherwise debit a
    figure nobody was shown. A mismatch is refused, never clamped.

    ORDER OF CHECKS IS THE ORDER OF HARM. The lock is taken FIRST — before the read that
    decides whether to write at all — because a dedupe check outside it is the
    check-then-write hole two clicks walk straight through (`lock_tenant_credits`). Then
    the replay check, so a second click returns the first click's block instead of buying
    another; then the tier and the ceiling, which are refusals; then the debit, which is
    the only step that moves money.

    `record_entry(allow_negative=False)`: this is a PURCHASE and not the recording of a
    cost already incurred, so an empty wallet must refuse it rather than overdraw. That
    is the opposite of `charge_for_call`, and the difference is exactly that a call has
    already happened.
    """
    if accepted_amount_inr != AI_OVERAGE_BLOCK_INR:
        raise ProblemError.business_rule(
            "ai_extra_amount_changed",
            "The amount you accepted is not the amount we would charge.",
            remediation="Reload the AI assistance screen and accept the amount shown.",
        )

    await lock_tenant_credits(session, tenant_id)
    quota = await read_ai_quota(session, tenant_id=tenant_id)

    if quota.extra_purchased_inr > 0:
        # A replay, not an error: the block is already on the wallet and nothing moves.
        # Reported as `charged=False` so the caller writes no second audit row.
        return ExtraPurchase(charged=False, amount_inr=quota.extra_purchased_inr, quota=quota)

    reason = quota.extra_unavailable
    if reason == "platform_paused":
        raise ProblemError.business_rule(
            "ai_paused_platform_wide",
            (
                "AI help is paused across Calevate right now, so there is nothing to "
                "add to. Nothing has been charged."
            ),
            remediation="Try again later, or ask your account manager for an update.",
        )
    if reason == "not_prepaid":
        raise ProblemError.business_rule(
            "ai_extra_not_available",
            (
                "Extra AI help is not something this account can buy directly — it is "
                "billed with your plan. Nothing has been charged."
            ),
            remediation="Talk to your account manager to add more AI help this month.",
        )
    if reason == "not_at_ceiling":
        # Refused rather than allowed early: money leaving a wallet for an allowance
        # nobody has run out of is the one outcome G-5 rules out.
        raise ProblemError.business_rule(
            "ai_quota_not_reached",
            (
                "This account still has included AI help left this month, so there is "
                "nothing to add yet. Nothing has been charged."
            ),
            remediation="Use the included allowance first; we will ask again at the limit.",
        )

    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-AI_OVERAGE_BLOCK_INR,
        reason="usage",
        ref=overage_ref(quota.month),
        meta={
            "kind": OVERAGE_META_KIND,
            "month": quota.month,
            # What the person was shown when they accepted, so the row explains itself
            # on a statement a year from now without this module being read.
            "accepted_amount_inr": str(to_paise(AI_OVERAGE_BLOCK_INR)),
            "included_inr": str(to_paise(quota.included_inr)),
            "used_inr_at_acceptance": str(to_paise(quota.used_inr)),
        },
    )
    log.info(
        "ai_overage_purchased",
        extra={
            "tenant_id": str(tenant_id),
            "month": quota.month,
            "amount_inr": str(AI_OVERAGE_BLOCK_INR),
        },
    )
    return ExtraPurchase(
        charged=True,
        amount_inr=AI_OVERAGE_BLOCK_INR,
        # Re-read INSIDE the same transaction, so the response states the world after
        # the debit rather than the world the decision was made in.
        quota=await read_ai_quota(session, tenant_id=tenant_id),
    )


def quota_payload(quota: AiQuota) -> dict[str, Any]:
    """The wire shape, money as exact digit STRINGS (hard rule 7).

    Built here rather than in the route so the response model and the dataclass cannot
    drift into two definitions of the same month — the route validates this dict through
    its own `extra="forbid"` model, which is what fails loudly if they ever do.
    """
    return {
        "month": quota.month,
        "plan_tier": quota.plan_tier,
        "state": quota.state,
        "included_inr": str(to_paise(quota.included_inr)),
        "used_inr": str(to_paise(quota.used_inr)),
        "allowance_inr": str(to_paise(quota.allowance_inr)),
        "remaining_inr": str(to_paise(quota.remaining_inr)),
        "requests_used": quota.requests_used,
        "requests_included": quota.requests_included,
        "requests_remaining": quota.requests_remaining,
        # Null rather than "0.00" when nothing was bought: "they added ₹500" and "they
        # added nothing" are different facts and the screen says different things.
        "extra_purchased_inr": (
            str(to_paise(quota.extra_purchased_inr)) if quota.extra_purchased_inr > 0 else None
        ),
        # ALWAYS published, so the modal quotes the server's figure and never a constant
        # compiled into the browser bundle.
        "extra_block_inr": str(to_paise(AI_OVERAGE_BLOCK_INR)),
        # About how many assists the block is worth, derived HERE for the same reason
        # `requests_included` is: the browser must never divide a rupee amount, and the
        # reference price is not published precisely so nobody is tempted to.
        "extra_block_requests": int(AI_OVERAGE_BLOCK_INR // AI_ASSIST_NOMINAL_INR),
        "extra_available": quota.extra_unavailable is None,
        "extra_unavailable_reason": quota.extra_unavailable,
    }


__all__ = [
    "AI_ASSIST_NOMINAL_INR",
    "AI_OVERAGE_BLOCK_INR",
    "AI_QUOTA_INR",
    "ASSIST_META_KIND",
    "INDEX_PREDICATE",
    "OVERAGE_META_KIND",
    "OVERAGE_REF_PREFIX",
    "PLATFORM_AI_BRAKE_INR",
    "PREPAID_TIERS",
    "AiQuota",
    "AssistMetered",
    "ExtraPurchase",
    "PlatformAiSpend",
    "ktok",
    "overage_ref",
    "platform_brake_tripped",
    "purchase_ai_overage",
    "quota_payload",
    "read_ai_quota",
    "read_platform_ai_spend",
    "record_ai_assist_usage",
    "require_ai_assist",
]
