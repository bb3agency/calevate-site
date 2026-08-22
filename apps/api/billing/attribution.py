"""Both sides of the money, per CALL and per AGENT, for one tenant-month (D-12).

`billing/service.py` answers "what did this month cost us" and "what does this month
cost the client" as two whole-month totals. This module answers the same two questions
one call at a time, and rolls them up per agent — the founder's requirement in one
sentence: *every rupee traceable, both directions*.

THE ONE DISTINCTION THIS FILE EXISTS TO KEEP
--------------------------------------------
`unit_cost_paid` is **our supplier cost**. The client sees what they are CHARGED. Both
figures are computed here, once, and the split is enforced where it can be enforced by a
type rather than by a reviewer's memory: `spend_routes.py` declares two `extra="forbid"`
response models over this one dataclass, and only the admin one names a cost field. That
is deliberately not a `if realm == "admin"` inside a shared serializer — a whitelist that
is a data structure cannot be widened by accident, and `tests/spend_attribution_test.py`
asserts the client model has no cost-shaped field at all.

NO NEW COLUMN, AND THE JOIN IS WHY
-----------------------------------
`usage_events` carries `call_id` and no `agent_id`, and it stays that way. `calls.agent_id`
is NOT NULL and indexed, so "which agent" is one join through a key the ledger already
holds — and adding an `agent_id` to an INSERT-only ledger (hard rule 4) would create a
second, un-fixable copy of a fact that already has an owner: a call whose agent was
recorded wrongly could never be corrected on the usage row, only compensated. Reading
`calls` from `billing/` is the same seam `billing/invoice.py` already uses for
`organizations` and `kyc_records`.

WHAT IS EXACT AND WHAT IS AN ALLOCATION — READ THIS BEFORE PUBLISHING A FIGURE
------------------------------------------------------------------------------
* **Our COST per call is a fact.** Every `usage_events` row carries `call_id`, so a call's
  cost is a sum, not a share. (It rests on the vendor CURRENCY assumption that OPERATIONS
  §2 gate 7 still scores — see `cost_currency_stated` below. The client-facing charge does
  not: it is priced off MINUTES at the client's own rate and is untouched by gate 7.)
* **A PREPAID client's charge per call is a fact.** `charge_for_call` debits the wallet
  once per call, keyed by `call_id`, so `credit_ledger` holds the rupees that actually
  left their balance. `charge_basis` is `wallet_debit`.
* **A MANAGED client's charge per call is an ALLOCATION and is labelled as one.** Their
  bill is a retainer plus a month's overage priced by `priced_overage`, which spends the
  included allowance on the DEARER rung first — a month-level rule with no per-call
  answer inside it. So the month's calling charge is divided across its calls by
  relative sales value (the standard joint-cost apportionment): each call's weight is its
  own minutes at its own rung's rate, `allocate_paise` distributes the paise, and the
  parts therefore sum to the published month total EXACTLY. `charge_basis` is `allocated`.
  Where a plan quotes ONE rate — which is every plan in the database today, because
  `plans.overage_rate_value` is an open founder decision — this reduces to plain minutes.

  Rejected: charging each call its own MARGINAL contribution (`month_increment`, which the
  meter uses for the live counter). It telescopes to the month total only in the order the
  calls metered in, so two identical calls get different rupees and re-rendering last
  month's page after a late-settling call changes figures a client already read.

WHAT THE PARTS ADD UP TO, BY CONSTRUCTION
------------------------------------------
Every published breakdown is a partition of a figure PUBLISHED BESIDE IT ON THIS PAGE,
and `allocate_paise` (largest remainder) is what makes it true rather than nearly true —
the D-371 fix, applied to three more columns:

    sum(by_call.minutes)      == minutes            (+ `unattributed`, below)
    sum(by_call.cost_inr)     == cost_inr           (+ `unattributed`, below)
    sum(by_agent.<anything>)  == sum(by_call.<the same>)      (agents are calls, grouped)
    sum(by_unit.cost_inr)     == cost_inr
    retainer + period_charge  == margin_for_tenant.revenue_inr
    itemised + residual       == period_charge (= calling_revenue_inr for the month)

**BESIDE IT, not "on some other panel", and the distinction cost a 500.** The four
row-derived figures used to be anchored on `usage_summary.minutes_used` and
`margin_for_tenant.cost_inr` — read by SEPARATE statements at separate instants. Under
READ COMMITTED that is a different snapshot of an append-only table that
`pipeline._meter` writes to throughout an open month, so one completing call between two
of the reads handed `allocate_paise` parts that did not add to their total and it raised,
as it is supposed to. `_CALL_ROWS_SQL` now reduces one scan into all of them, so the
identities hold under concurrent metering instead of only when nothing is moving. They
still equal the other panels' figures to the paisa — same rows, same expressions, same
construction — for any month those panels are reading at the same instant, which is every
closed month and an open one nobody is dialling in.

`itemisation_residual_inr` is the honest half of the last one. It is exactly ₹0.00 on the
allocated basis; on the wallet basis it absorbs (a) per-call display rounding, since a
wallet debit is stored at NUMERIC(12,4) and published at paise, and (b) the measured,
already-documented gap between the sum of per-call debits and the panel's own closed-month
figure — `calling_revenue_inr` sets that out in full and names it a founder decision
(`docs/evidence/deepdive-money.md` N-2). Publishing the gap is the only option that does
not require picking one of the two as the lie.

Money is `Decimal` end to end and never a float (hard rule 7): NUMERIC out of the ledger,
`Decimal` through every expression here, and `str()` at the route boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import PREPAID_TIERS

# IMPORTED, PRIVATE NAMES AND ALL, exactly as `billing/cost_unit.py` imports `_ROW_COST_SQL`
# and argues why. Each of these is the ONE definition of a fact this module has to agree
# with to the paisa, and a second spelling of any of them would let this page and the panel
# beside it describe the same month differently:
#
#   _ROW_COST_SQL       what one usage row contributes to our cost (D-370: a zero-`qty`
#                       row carries its WHOLE leg cost)
#   _CORRECTED_TIER_SQL which rung a call's money counts on after a correction (D-372)
#   _SURCHARGED_MODEL_SQL which model surcharge a row's minutes carry, if any (D-455)
#   _NOT_AI_UNITS       "...and it is a CALL row" — dashboard-assist rows are ours (D-127 G-3)
#   _IST_MONTH_WINDOW   the half-open IST month, as a range an index can drive
#   _month_bounds       the two binds that window reads, so a caller cannot supply half of it
#   _SECONDS_PER_MINUTE the divisor, as a Decimal, in one place
from apps.api.billing.service import (
    _CORRECTED_TIER_SQL,
    _IST_MONTH_WINDOW,
    _NOT_AI_UNITS,
    _ROW_COST_SQL,
    _SECONDS_PER_MINUTE,
    _SURCHARGED_MODEL_SQL,
    _month_bounds,
    allocate_paise,
    calling_revenue_inr,
    plan_tier_of,
    to_paise,
    usage_summary,
)
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: How long the per-call fold may take before it is a problem in its own right.
#:
#: THE WHOLE MONTH IS MATERIALISED AND THAT IS NOT NEGOTIABLE: an allocation needs its own
#: denominator, so the top-N calls cannot be priced without the calls they are the top of.
#: What IS negotiable is staying silent about it, and this repo already answered that
#: question once — `admin/health.py::WALK_BUDGET_S` logs and names a remedy rather than
#: truncating, because a money page that quietly dropped the tail would be a partition
#: that does not partition. Two seconds is the point at which a panel stops feeling
#: loaded; the database does the reduction (one row per call-and-rung out of ~5 usage
#: rows per call), so what is folded here is calls, not ledger rows.
ATTRIBUTION_BUDGET_S: Final = 2.0

#: `charge_basis`. WHICH KIND OF NUMBER the per-call charge is, published beside it because
#: a fact and a share are not the same claim and a reader is entitled to know which they
#: are looking at.
ChargeBasis = Literal["wallet_debit", "allocated"]

#: `residual_reason`. A closed vocabulary rather than prose: the screen owns the wording,
#: the server owns the fact (`admin/health.py` draws the same line).
ResidualReason = Literal["prepaid_wallet_vs_panel", "no_billable_minutes"]

# ONE SCAN, ONE REDUCTION, ONE SNAPSHOT. The month's rows are read once through
# `ix_usage_events_tenant_occurred` (migration c9e2a7b41d63 measured that range at 2.1 ms /
# 74 buffers against 33.8 ms / 3822 for the tenant-only path), aggregated IN THE DATABASE,
# and only then joined to `calls` and `agents` by primary key — so the join is one index
# probe per CALL rather than one per ledger row.
#
# GROUPED BY RUNG AS WELL AS BY CALL, and it is not decoration: the managed allocation
# weights a call's minutes by its rung's RATE, and a call whose rows disagree about the
# rung (one metered before tier attribution existed, then corrected) would otherwise need
# a tie-break nobody could defend. Summing the sub-buckets needs none — the weight is
# `SUM(rung seconds x that rung's rate)` and the cost is `SUM(cost)`, both exact.
#
# **THE UNIT BREAKDOWN AND THE MONTH'S CURRENCY COME OUT OF THIS SAME STATEMENT, THROUGH
# `GROUPING SETS`, AND THAT IS A CONCURRENCY FIX RATHER THAN A TIDY-UP.** They used to be
# two more `SELECT`s over the same rows. `usage_events` is append-only and the month on
# screen is usually the OPEN one, which `pipeline._meter` is writing to continuously — so
# under READ COMMITTED (every statement takes a fresh snapshot, even inside one
# transaction) a call completing between two of those reads gave this function a
# breakdown from one instant and a total from another. `allocate_paise` refuses to
# publish parts that do not add to their total, correctly, by raising — which surfaced as
# an unhandled 500 on a client's own money page, reproducible by inserting one
# `telephony_s` row between the reads. Two grouping sets over ONE `priced` CTE cannot
# straddle a commit: the per-call rows and the per-unit rows are two reductions of the
# same scan of the same snapshot, so `sum(by_unit.cost_inr) == cost_inr` holds by
# construction rather than by nothing having moved.
#
# `GROUPING(unit_type)` is the discriminator, not `call_id IS NULL`: a per-CALL row with
# no call is real (`number_rental` — OPERATIONS §2 gate 26 turns its writer on) and would
# be indistinguishable from a per-UNIT row otherwise.
#
# `LEFT JOIN`, twice: the callless bucket must not be dropped out of a cost total that
# claims to be a partition, and the per-unit rows carry no `call_id` at all. `calls
# .agent_id` is NOT NULL, so the second LEFT JOIN can only miss if the first did.
_CALL_ROWS_SQL: Final = f"""
WITH priced AS (
  SELECT call_id,
         unit_type,
         {_CORRECTED_TIER_SQL} AS tier,
         {_SURCHARGED_MODEL_SQL} AS llm_model,
         qty,
         CASE WHEN unit_type = 'telephony_s' THEN qty ELSE 0 END AS secs,
         {_ROW_COST_SQL} AS cost,
         meta ->> 'source_currency' AS source_currency,
         meta ->> 'currency_stated' AS currency_stated
    FROM usage_events
   WHERE tenant_id = :tid AND {_IST_MONTH_WINDOW} AND {_NOT_AI_UNITS}
),
folded AS (
  SELECT GROUPING(unit_type) AS per_call,
         call_id, tier, llm_model, unit_type,
         COALESCE(SUM(secs), 0) AS secs,
         COALESCE(SUM(qty), 0) AS qty,
         COALESCE(SUM(cost), 0) AS cost,
         -- OUR ASSUMPTION OR THEIRS (gate 7). `= 'false'` rather than `<> 'true'`: only a
         -- row that RECORDED the fallback asserts it, so a correction row -- which carries
         -- no `currency_stated` at all -- cannot manufacture the flag.
         bool_or(currency_stated = 'false') AS currency_assumed,
         min(source_currency) AS currency_lo,
         max(source_currency) AS currency_hi
    FROM priced GROUP BY GROUPING SETS ((call_id, tier, llm_model), (unit_type))
)
SELECT f.per_call, f.call_id, f.unit_type, f.tier, f.llm_model, f.secs, f.qty, f.cost,
       f.currency_assumed, f.currency_lo, f.currency_hi,
       c.agent_id, c.started_at, c.direction, a.name
  FROM folded f
  LEFT JOIN calls c ON c.id = f.call_id
  LEFT JOIN agents a ON a.id = c.agent_id
 ORDER BY f.per_call DESC, f.call_id, f.unit_type
"""

# WHAT ACTUALLY LEFT A PREPAID WALLET, per call. `reason = 'usage'` only, and that is the
# whole namespace `charge_for_call` writes: a refund or an operator adjustment carries its
# own `ref` vocabulary (`adjustment_ref`, `restatement_ref`) and is a credit against the
# ACCOUNT, not a re-pricing of a call — folding one in here would show a client a call
# that cost less than it did.
#
# Keyed by the month's own call ids rather than by the ledger entry's `occurred_at`: a
# call that settles late is debited in the month AFTER the one its minutes belong to, and
# the charge belongs with the call.
_WALLET_DEBITS_SQL: Final = (
    "SELECT ref, SUM(-delta) FROM credit_ledger "
    " WHERE tenant_id = :tid AND reason = 'usage' AND ref = ANY(:refs) GROUP BY ref"
)


@dataclass(frozen=True, slots=True)
class CallAttribution:
    """One call, both directions of the money."""

    call_id: UUID
    #: NULL only for a call row this tenant's session cannot see, which RLS makes
    #: impossible for a `usage_events` row it CAN see — they are the same tenant.
    agent_id: UUID | None
    agent_name: str | None
    started_at: datetime | None
    direction: str | None
    #: Paise-exact, and the month's calls sum to `usage_summary.minutes_used` exactly.
    minutes: Decimal
    #: OURS. Never leaves the admin realm.
    cost_inr: Decimal
    #: THE CLIENT'S. `PeriodAttribution.charge_basis` says whether it is a fact or a share.
    charged_inr: Decimal
    #: Our cost for this call was read in a currency the vendor's payload did not state
    #: (OPERATIONS §2 gate 7). Admin-only, because it qualifies OUR figure and nothing
    #: about what the client was charged.
    cost_currency_assumed: bool


@dataclass(frozen=True, slots=True)
class AgentAttribution:
    """One agent's share of a month, summed from its calls — never queried separately.

    Summing the published per-call figures rather than running a second GROUP BY is what
    makes the two screens agree by construction: a rollup computed independently would be
    a second reading of one month, which is the D-103 shape this module's neighbours have
    each paid for once.
    """

    agent_id: UUID | None
    agent_name: str | None
    calls: int
    minutes: Decimal
    cost_inr: Decimal
    charged_inr: Decimal
    cost_currency_assumed: bool


@dataclass(frozen=True, slots=True)
class UnitAttribution:
    """What one metered unit type contributed to OUR cost. Admin-only, all of it.

    `qty` is not money and is not rounded like it: seconds, minutes and character counts
    are what they are, and quantizing them to paise would be a category error.
    """

    unit_type: str
    qty: Decimal
    cost_inr: Decimal


@dataclass(frozen=True, slots=True)
class UnattributedCost:
    """Cost this month that belongs to no call.

    `number_rental` is the whole of it and nothing writes one yet (OPERATIONS §2 gate 26
    is what turns that writer on), so this is `None` on every real month today. It exists
    rather than being assumed away because the alternative is a `cost_inr` that silently
    stops being the sum of its parts on the day a number is first billed.
    """

    minutes: Decimal
    cost_inr: Decimal


@dataclass(frozen=True, slots=True)
class PeriodAttribution:
    """One tenant-month, attributed. The ONE computation both realms are served from."""

    month: str
    plan_tier: str
    charge_basis: ChargeBasis
    calls: int
    minutes: Decimal
    #: The retainer, published on its own and deliberately NOT allocated across calls: it
    #: buys the account, not any particular minute, and `calling_revenue_inr` keeps it out
    #: of the calling figure for the same reason.
    retainer_inr: Decimal | None
    #: The month's calling charge at the client's own rate — `overage_cost_inr` for a
    #: managed plan (the very figure the invoice prints) and the list-priced minutes for a
    #: prepaid one. `calling_revenue_inr` is the one definition, shared with the margin
    #: card's revenue. The RETAINER is not in it; it is published beside it.
    period_charge_inr: Decimal
    #: The sum of the per-call figures below, exactly as published.
    itemised_charge_inr: Decimal
    #: `period_charge_inr - itemised_charge_inr`. Signed, and ₹0.00 on the allocated basis.
    itemisation_residual_inr: Decimal
    residual_reason: ResidualReason | None
    #: OURS, and equal to `margin_for_tenant.cost_inr` for the same month to the paisa.
    cost_inr: Decimal
    unattributed: UnattributedCost | None
    #: The one currency our cost rows were read in, or None when the month has none or
    #: more than one. Admin-only.
    cost_currency: str | None
    #: True only if EVERY costed row recorded that the vendor stated its currency. False
    #: is the state of the world today (`AgentExecution` declares no `currency` property),
    #: which is what gate 7 is open on and what `runbooks/vendor-cost-unit.md` triages.
    cost_currency_stated: bool
    by_agent: tuple[AgentAttribution, ...]
    by_unit: tuple[UnitAttribution, ...]
    by_call: tuple[CallAttribution, ...]


@dataclass(frozen=True, slots=True)
class _Bucket:
    """One call's raw, unrounded state while it is being folded. Never published."""

    call_id: UUID | None
    agent_id: UUID | None
    agent_name: str | None
    started_at: datetime | None
    direction: str | None
    seconds: Decimal
    cost_inr: Decimal
    #: Minutes at this call's own rung rate — the managed allocation's weight. Summed
    #: across the call's rung sub-buckets, so a corrected call weighs what it ran as.
    weight: Decimal
    currency_assumed: bool


@dataclass(frozen=True, slots=True)
class _UnitRow:
    """One metered unit type's raw, unrounded month. Never published."""

    unit_type: str
    qty: Decimal
    cost_inr: Decimal


@dataclass(frozen=True, slots=True)
class _MonthRead:
    """Everything one scan of the month's ledger says. THE snapshot the rest divides up.

    Three facts out of one statement rather than three statements, because two of them are
    a TOTAL and its PARTS: see `_CALL_ROWS_SQL` for the 500 that reading them separately
    produced on an open month.
    """

    buckets: list[_Bucket]
    units: list[_UnitRow]
    #: The one currency this month's cost was read in, or None when the rows do not agree
    #: or carry no currency at all. Both are states an operator has to see rather than
    #: have averaged away — None is never "we did not look".
    currency: str | None


def _rung_rate(
    tier: str, *, rate: Decimal, rate_value: Decimal | None, surcharge: Decimal | None
) -> Decimal:
    """What a minute on this rung, on this model, is quoted at.

    `surcharge` is the plan's model surcharge when THESE minutes carry it and `None`
    otherwise — the caller decides from the bucket the ledger put them in, so this
    function never sees a model identifier and cannot invent an opinion about one.

    Unattributed (`''`) is priced with `value`, never `premium` — SURFACES §2b's rule that
    a call we cannot PROVE got the premium voice is never charged the premium rate, and
    `tier_usage` states the same thing about the same bucket. A plan quoting no separate
    value rate bills both rungs at `rate`, which is what `NULL` means on that column and
    not "the value rung is free".
    """
    base = rate if tier == "premium" or rate_value is None else rate_value
    return base if surcharge is None else base + surcharge


async def _read_month(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    month: str,
    rate: Decimal,
    rate_value: Decimal | None,
    surcharge: Decimal | None,
) -> _MonthRead:
    """The month's ledger, in ONE statement: per call, per unit type, and its currency.

    RLS is what makes another tenant's rows unreachable; `tenant_id` is named in the
    predicate as well because that is what makes this an index scan and what makes the
    answer depend on the argument rather than on which session it was handed
    (`usage_summary` argues the same pairing).

    The per-unit rows PARTITION the same scan the per-call buckets do, so the month's
    currency is `min`/`max` folded over them rather than a fourth query: a `min` of the
    partitions' `min`s IS the whole month's `min`, and `min`/`max` ignore NULLs, so "no
    row carries a currency" arrives as None exactly as a dedicated `IS NOT NULL` filter
    would have made it.
    """
    rows = (
        await session.execute(text(_CALL_ROWS_SQL), {"tid": tenant_id, **_month_bounds(month)})
    ).all()

    folded: dict[UUID | None, _Bucket] = {}
    units: list[_UnitRow] = []
    lows: list[str] = []
    highs: list[str] = []
    for (
        per_call,
        call_id,
        unit_type,
        tier,
        llm_model,
        secs,
        qty,
        cost,
        assumed,
        low,
        high,
        agent_id,
        started_at,
        direction,
        name,
    ) in rows:
        if not per_call:
            units.append(
                _UnitRow(
                    unit_type=str(unit_type),
                    qty=Decimal(str(qty or 0)),
                    cost_inr=Decimal(str(cost or 0)),
                )
            )
            if low is not None:
                lows.append(str(low))
            if high is not None:
                highs.append(str(high))
            continue
        key = UUID(str(call_id)) if call_id is not None else None
        seconds = Decimal(str(secs or 0))
        prior = folded.get(key)
        folded[key] = _Bucket(
            call_id=key,
            agent_id=UUID(str(agent_id)) if agent_id is not None else None,
            agent_name=str(name) if name is not None else None,
            started_at=started_at,
            direction=str(direction) if direction is not None else None,
            seconds=(prior.seconds if prior else Decimal("0")) + seconds,
            cost_inr=(prior.cost_inr if prior else Decimal("0")) + Decimal(str(cost or 0)),
            weight=(prior.weight if prior else Decimal("0"))
            + seconds
            / _SECONDS_PER_MINUTE
            * _rung_rate(
                str(tier or ""),
                rate=rate,
                rate_value=rate_value,
                # The MODEL SURCHARGE is part of what this call is worth to the month's
                # bill (D-455), so it belongs in the WEIGHT and not only in the total.
                # Without it, `period_charge` would grow by the surcharge and then be
                # spread evenly over calls that did not incur it — a page whose whole job
                # is "which agent drove this spend" pointing at the wrong agent on exactly
                # the month a client moved one agent onto the dearer model.
                surcharge=surcharge if str(llm_model or "") else None,
            ),
            currency_assumed=(prior.currency_assumed if prior else False) or bool(assumed),
        )
    currency = min(lows) if lows and min(lows) == max(highs) else None
    return _MonthRead(buckets=list(folded.values()), units=units, currency=currency)


async def period_attribution(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> PeriodAttribution:
    """Attribute one tenant-month, both directions. THE computation; the routes only render.

    `tenant_id` is taken and also carried on the session: the argument is what the
    predicate binds (so the answer depends on the argument rather than on which session it
    was handed) and RLS is what makes another tenant's rows unreachable even if it did not.
    """
    started = perf_counter()
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    period = str(usage["month"])
    tier = await plan_tier_of(session, tenant_id)

    rate = Decimal(str(usage["overage_rate_inr"]))
    rate_value = (
        Decimal(str(usage["overage_rate_value_inr"]))
        if usage["overage_rate_value_inr"] is not None
        else None
    )
    # The plan's model surcharge, from the SAME `usage_summary` read that priced it —
    # never a second look at `plans`, which could land on a different row.
    surcharge = (
        Decimal(str(usage["llm_surcharge_rate_inr"]))
        if usage["llm_surcharge_rate_inr"] is not None
        else None
    )
    read = await _read_month(
        session,
        tenant_id=tenant_id,
        month=period,
        rate=rate,
        rate_value=rate_value,
        surcharge=surcharge,
    )
    buckets = read.buckets
    # Deterministic before anything is allocated: `allocate_paise` hands its spare paise
    # out by discarded fraction and breaks ties BY POSITION, so an unstable input order
    # would move a paisa between two calls between two renders of one closed month.
    buckets.sort(key=lambda b: (b.call_id is None, str(b.call_id)))

    # EVERY TOTAL BELOW IS SUMMED FROM THE PARTS THIS PAGE PUBLISHES, never taken from a
    # second read. `usage_summary` above is a different statement at a different instant,
    # and pairing its `minutes_used` with buckets read afterwards is what made an ordinary
    # concurrent `pipeline._meter` write turn this page into a 500 (`_CALL_ROWS_SQL`).
    # The construction is `rung_minutes`' own — divide the month's exact seconds once,
    # then let `allocate_paise` place the remainder — so on a month nobody is writing to
    # this is bit-for-bit `usage_summary.minutes_used`, which is the identity
    # `tests/spend_attribution_test.py` pins.
    minutes_total = to_paise(sum((b.seconds for b in buckets), Decimal("0")) / _SECONDS_PER_MINUTE)
    minutes = _allocate_minutes(buckets, total=minutes_total)
    cost_total = to_paise(sum((b.cost_inr for b in buckets), Decimal("0")))
    costs = allocate_paise([b.cost_inr for b in buckets], cost_total)
    # WHAT THE CLIENT IS CHARGED FOR THIS MONTH'S CALLING, from the ONE function that
    # already answers that for both motions — the same one `margin_for_tenant` takes its
    # revenue from, so this page's items and that card's revenue divide the same rupees.
    #
    # **NOT `usage_summary.spend_used_inr`, and the difference is not cosmetic.** That
    # field is a CAP instrument: while a month is open it reads `spend_state.billed_inr`,
    # the counter `over_cap_sql` compares against, which moves only when the METER runs.
    # Anchoring an itemisation on it makes the whole page read 0.00 for a month whose
    # counter has not been touched — measured on this tree at `overage_cost_inr` of
    # 100.00 against a `spend_used_inr` of 0.00 — and it would make the client's bill
    # depend on a counter rather than on their plan. The INVOICE is what a client is
    # charged, and `calling_revenue_inr` is its calling half.
    period_charge = to_paise(
        calling_revenue_inr(
            plan_tier=tier,
            minutes=Decimal(str(usage["minutes_used"])),
            overage_cost_inr=Decimal(str(usage["overage_cost_inr"])),
            llm_surcharge_inr=Decimal(str(usage["llm_surcharge_inr"])),
        )
    )
    charges, basis, residual_reason = await _allocate_charges(
        session, buckets, tenant_id=tenant_id, plan_tier=tier, period_charge=period_charge
    )

    by_call = tuple(
        CallAttribution(
            call_id=bucket.call_id,
            agent_id=bucket.agent_id,
            agent_name=bucket.agent_name,
            started_at=bucket.started_at,
            direction=bucket.direction,
            minutes=minute,
            cost_inr=cost,
            charged_inr=charge,
            cost_currency_assumed=bucket.currency_assumed,
        )
        for bucket, minute, cost, charge in zip(buckets, minutes, costs, charges, strict=True)
        if bucket.call_id is not None
    )
    unattributed = next(
        (
            UnattributedCost(minutes=minute, cost_inr=cost)
            for bucket, minute, cost in zip(buckets, minutes, costs, strict=True)
            if bucket.call_id is None
        ),
        None,
    )

    itemised = sum((row.charged_inr for row in by_call), Decimal("0.00"))
    residual = period_charge - itemised

    elapsed = perf_counter() - started
    if elapsed > ATTRIBUTION_BUDGET_S:
        # Ids and counts only (hard rule 6), and the remedy on the line rather than in
        # this module — the same discipline `client_health_walk_over_budget` keeps.
        log.warning(
            "spend_attribution_over_budget",
            extra={
                "tenant_id": str(tenant_id),
                "month": period,
                "calls": len(by_call),
                "elapsed_s": round(elapsed, 2),
                "budget_s": ATTRIBUTION_BUDGET_S,
                "remedy": "a month has outgrown the per-call fold — materialize the "
                "per-call rollup (billing/attribution.py)",
            },
        )

    return PeriodAttribution(
        month=period,
        plan_tier=tier,
        charge_basis=basis,
        calls=len(by_call),
        minutes=minutes_total,
        retainer_inr=usage["monthly_fee_inr"],
        period_charge_inr=period_charge,
        itemised_charge_inr=itemised,
        itemisation_residual_inr=residual,
        # A reason is published only when there is something to explain: ₹0.00 needs none,
        # and a reason beside a zero would train a reader to ignore the field.
        residual_reason=residual_reason if residual != 0 else None,
        cost_inr=cost_total,
        unattributed=unattributed,
        cost_currency=read.currency,
        cost_currency_stated=not any(b.currency_assumed for b in buckets),
        by_agent=_roll_up_agents(by_call),
        by_unit=_unit_costs(read.units, total=cost_total),
        by_call=by_call,
    )


def _allocate_minutes(buckets: list[_Bucket], *, total: Decimal) -> tuple[Decimal, ...]:
    """Per-call minutes that sum to this page's own `minutes` figure exactly.

    The same construction `rung_minutes` uses one grouping up — divide the exact seconds,
    then let `allocate_paise` place the remainder — so the two breakdowns of one month
    (by rung and by call) add to the same figure rather than to two figures a paisa apart.

    Every bucket is in the allocation, including one with no call. That bucket holds no
    seconds in any ledger this code has seen (`telephony_s` is written only by
    `pipeline._meter`, which always supplies a `call_id`), but pairing a total with parts
    that had been filtered differently is how `allocate_paise` is made to raise on a money
    page, and the filter buys nothing.
    """
    return allocate_paise([b.seconds / _SECONDS_PER_MINUTE for b in buckets], total)


async def _allocate_charges(
    session: AsyncSession,
    buckets: list[_Bucket],
    *,
    tenant_id: UUID,
    plan_tier: str,
    period_charge: Decimal,
) -> tuple[tuple[Decimal, ...], ChargeBasis, ResidualReason]:
    """What each call cost the CLIENT, and which kind of number that is.

    Returns the per-bucket figures in the caller's own order, the basis to publish beside
    them, and the reason that explains a non-zero residual on that basis. The caller
    suppresses the reason when the residual is ₹0.00 — the reason is an explanation, and
    there is nothing to explain when the parts already add up.
    """
    if plan_tier in PREPAID_TIERS:
        debits = await _wallet_debits(session, buckets, tenant_id=tenant_id)
        # `to_paise` per call rather than an allocation: these are FACTS about individual
        # calls, and bending one by a paisa to make a column add up would make the figure
        # disagree with the client's own wallet history — which is the one document a
        # prepaid client can check this against.
        return (
            # Keyed by the ledger's own `ref`, which is TEXT -- so the bucket that has no
            # call looks up a key no `ref` can be and gets 0.00 without a branch that
            # nothing in this ledger can reach. `charge_for_call` writes one `usage` entry
            # per CALL; a callless cost row never took anything off a wallet.
            tuple(to_paise(debits.get(str(b.call_id), Decimal("0"))) for b in buckets),
            "wallet_debit",
            "prepaid_wallet_vs_panel",
        )
    return _allocate_managed(buckets, charge=period_charge), "allocated", "no_billable_minutes"


def _allocate_managed(buckets: list[_Bucket], *, charge: Decimal) -> tuple[Decimal, ...]:
    """Divide the month's calling charge by relative sales value. See the module docstring.

    Two rungs, because dividing by a zero weight is not a number and a month with no
    weight at all is a real state:

    1. weights — minutes at each call's own rung rate. The rule.
    2. nothing — no weight to divide by, so nothing can carry a share and the whole charge
       is published as the residual with `no_billable_minutes` beside it. Two ways in, and
       both are ordinary: a call the engine reported as zero-length (which still costs us
       — D-370 keeps its whole leg cost on the row — but has no minutes to be a share OF),
       and a tenant whose plan quotes no rate at all, which is every tenant mid-onboarding.

    THERE WAS A THIRD RUNG AND IT WAS DEAD, which is worth recording because it read as
    prudence. It fell back to weighting by raw SECONDS "when every rate quoted is zero, so
    the weights carry no information but the durations still do" — and there is no such
    month. A weight is `minutes x that rung's rate`, so the weights sum to zero exactly
    when every rate in force is zero, and `priced_overage` then prices the month at 0.00:
    the fallback could only ever divide ZERO across those seconds and hand back the same
    tuple of 0.00 the rung below it hands back. Sabotaging it changed no test because it
    could change no answer.

    A bucket with no CALL is in the basis like any other and weighs ZERO in practice,
    because the only unit priced per second is `telephony_s` and its one writer
    (`pipeline._meter`) always supplies a `call_id`; `number_rental` — the callless row
    OPERATIONS §2 gate 26 turns on — is one unit of a standing charge with no duration.
    It is NOT special-cased out of the basis, and the reason is what happens if that ever
    stops being true: a callless bucket that DID carry seconds would take its proportional
    share, that share would be absent from `by_call`, and it would therefore surface in
    `itemisation_residual_inr` — a published number an operator can see. Excluding it
    instead would move those rupees onto real calls, which is the same money reported as
    something it is not, on the rows a client checks.
    """
    weights = [b.weight for b in buckets]
    denominator = sum(weights, Decimal("0"))
    if denominator <= 0:
        return tuple(Decimal("0.00") for _ in buckets)
    # Multiplied BEFORE dividing so no intermediate ratio is materialised — the same order
    # and the same reason as `cost_unit.restatement_delta`.
    return allocate_paise([charge * w / denominator for w in weights], charge)


async def _wallet_debits(
    session: AsyncSession, buckets: list[_Bucket], *, tenant_id: UUID
) -> dict[str, Decimal]:
    """The rupees each of this month's calls actually took off the prepaid wallet.

    Keyed by `credit_ledger.ref` as it is stored -- a string -- rather than parsed back to
    a UUID: `ref` is two namespaces in one column (a call id on a `usage` row, whatever
    the bank printed on a `topup` one), so a cast to UUID would be an assertion about data
    this query is deliberately not the owner of.
    """
    refs = [str(b.call_id) for b in buckets if b.call_id is not None]
    if not refs:
        return {}
    rows = (await session.execute(text(_WALLET_DEBITS_SQL), {"tid": tenant_id, "refs": refs})).all()
    return {str(ref): Decimal(str(amount or 0)) for ref, amount in rows}


def _roll_up_agents(calls: tuple[CallAttribution, ...]) -> tuple[AgentAttribution, ...]:
    """Agents are calls, grouped — never a second query. Ordered by what they cost us."""
    rolled: dict[UUID | None, AgentAttribution] = {}
    for call in calls:
        prior = rolled.get(call.agent_id)
        rolled[call.agent_id] = AgentAttribution(
            agent_id=call.agent_id,
            agent_name=call.agent_name,
            calls=(prior.calls if prior else 0) + 1,
            minutes=(prior.minutes if prior else Decimal("0.00")) + call.minutes,
            cost_inr=(prior.cost_inr if prior else Decimal("0.00")) + call.cost_inr,
            charged_inr=(prior.charged_inr if prior else Decimal("0.00")) + call.charged_inr,
            cost_currency_assumed=(prior.cost_currency_assumed if prior else False)
            or call.cost_currency_assumed,
        )
    return tuple(
        sorted(rolled.values(), key=lambda a: (-a.cost_inr, -a.charged_inr, str(a.agent_id)))
    )


def _unit_costs(units: list[_UnitRow], *, total: Decimal) -> tuple[UnitAttribution, ...]:
    """OUR cost, partitioned by metered unit type — a partition, not a parallel estimate.

    Folded from the SAME scan `total` was summed out of (`_read_month`), so the parts and
    the whole cannot come from two snapshots of an append-only table.

    `allocate_paise` against `cost_inr`'s own figure for the same reason `tier_usage`
    allocates its three rungs (D-371): `unit_cost_paid` is NUMERIC(12,4) and `qty` is
    NUMERIC(14,4), so a bucket's sum of products routinely carries four decimals and
    `to_paise` on each one publishes lines that do not add up to the total above them.
    """
    if not units:
        return ()
    ordered = sorted(units, key=lambda u: u.unit_type)
    costs = allocate_paise([u.cost_inr for u in ordered], total)
    return tuple(
        UnitAttribution(unit_type=unit.unit_type, qty=unit.qty, cost_inr=cost)
        for unit, cost in zip(ordered, costs, strict=True)
    )


__all__ = [
    "ATTRIBUTION_BUDGET_S",
    "AgentAttribution",
    "CallAttribution",
    "ChargeBasis",
    "PeriodAttribution",
    "ResidualReason",
    "UnattributedCost",
    "UnitAttribution",
    "period_attribution",
]
