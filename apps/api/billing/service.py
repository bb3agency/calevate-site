"""Prepaid credits (D-34/D-39, DATA-MODEL §8).

The ledger ships in M1 and the top-up UI does not, which looks odd until you read D-12:
metering is not retrofittable. A balance reconstructed later from usage rows is a
reconstruction; the first time a client disputes a charge, the difference between a
ledger and a reconstruction is the entire argument.

Two rules the whole module turns on:

- **Append-only** (hard rule 4). A refund is a new entry. `record_entry` is the only
  writer and it never updates.
- **Concurrent writes for one tenant are serialized by an advisory lock.** The obvious
  implementation — `SELECT … ORDER BY occurred_at DESC LIMIT 1 FOR UPDATE` — does NOT
  work, and the test suite proved it: under READ COMMITTED, two charges both block on
  the same newest row, and when the first commits the second re-checks only the row it
  locked, not the query. It never sees the row that was just inserted, so both compute
  from the same starting balance and a ₹100 wallet pays for two ₹80 calls.
  `pg_advisory_xact_lock` on the tenant serializes the whole read-decide-write instead,
  and releases at transaction end. It is scoped to credit writes, so it does not block
  unrelated work on the tenant.

  The lock has to be taken BEFORE any read the write then depends on — including an
  idempotency lookup. `lock_tenant_credits` is that one function, so every writer takes
  the same lock on the same key and nobody re-derives it.

Money is NUMERIC INR throughout (hard rule 7). No floats reach this file, and every
rupee amount is rounded in exactly one function, `to_paise`, with one explicit mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.caps import (
    EFFECTIVE_CAP_MIN_SQL,
    EFFECTIVE_CAP_SPEND_SQL,
    read_spend_counters,
)
from apps.api.billing.plans import (
    month_pricing_instant,
    parse_billing_month,
    plan_in_effect_sql,
    warn_no_plan_in_effect,
)
from apps.api.billing.rates import TtsTier, tier_correction_inr
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

CreditReason = Literal["topup", "usage", "adjustment", "refund"]

# Below this the wallet is "low" — surfaced in the UI, not enforced. Enforcement is
# `balance > 0`; a warning band exists so a client is told before calls start failing.
LOW_BALANCE_INR = Decimal("200.00")

# --- rounding (hard rule 7) ----------------------------------------------------
#
# NUMERIC(12,4) is the storage precision; a rupee amount shown to a human is two
# decimals. That conversion is a ROUNDING DECISION and it is made here, once:
#
# - ROUND_HALF_UP, the convention Indian tax invoices are checked against. Bare
#   `Decimal.quantize()` uses the ambient `decimal` context, whose default is
#   ROUND_HALF_EVEN (banker's rounding) — so ₹18.045 of GST becomes ₹18.04, and a
#   client adding it up by hand gets ₹18.05 and a support ticket.
# - passed EXPLICITLY, never inherited. `decimal.getcontext()` is process-global and
#   mutable by any library in the image; a rupee that changes because someone else
#   changed a global is not an amount we can defend.
PAISE = Decimal("0.01")
ROUNDING = ROUND_HALF_UP


def to_paise(value: Decimal) -> Decimal:
    """The ONE place a rupee amount is rounded. Every money field in every billing
    response goes through it, so no two surfaces can round the same number differently."""
    return value.quantize(PAISE, rounding=ROUNDING)


def rate_to_display(rate: Decimal) -> Decimal:
    """A RATE is not a rupee amount and must not be rounded like one.

    `overage_rate` is NUMERIC(12,4), so a plan may legitimately quote ₹7.1250/min.
    Quantizing that to ₹7.13 for display while billing the unrounded rate makes the
    invoice line fail the only arithmetic a client ever does on it — qty * unit = amount
    — by ₹0.10 on twenty minutes. So: paise when the rate IS a whole number of paise
    (the normal case, and ₹8.00 reads better than ₹8.0000), full precision otherwise.
    """
    paise = to_paise(rate)
    return paise if paise == rate else rate.normalize()


@dataclass(frozen=True, slots=True)
class Balance:
    amount_inr: Decimal
    is_low: bool

    @property
    def is_exhausted(self) -> bool:
        return self.amount_inr <= Decimal("0")


async def lock_tenant_credits(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize every credit write for this tenant for the rest of the transaction.

    Take it BEFORE any read the write depends on — the balance read, and equally the
    idempotency lookup that decides whether to write at all. A dedupe check outside the
    lock is the same check-then-write hole as a stale balance read: two runs both see
    "not charged yet" and both append.

    A row lock on the newest entry is NOT a substitute (module docstring): under READ
    COMMITTED a second writer blocked on it re-checks the row it locked, not the query,
    so it never sees the row that was just inserted. Released at transaction end.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"credit:{tenant_id}"},
    )


async def _newest_balance(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """The newest entry's `balance_after` — one indexed row read, not an aggregate,
    which is exactly why `balance_after` is stored. `get_balance` and `record_entry`
    share it so the definition of "newest" can never drift between the two."""
    amount = (
        await session.execute(
            text(
                "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    return Decimal(amount) if amount is not None else Decimal("0")


async def get_balance(session: AsyncSession, *, tenant_id: UUID) -> Balance:
    """The newest entry's `balance_after`."""
    balance = await _newest_balance(session, tenant_id)
    return Balance(amount_inr=balance, is_low=balance < LOW_BALANCE_INR)


async def record_entry(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    delta: Decimal,
    reason: CreditReason,
    ref: str | None = None,
    meta: dict[str, Any] | None = None,
    allow_negative: bool = False,
) -> Balance:
    """Append one entry and return the new balance.

    `allow_negative=False` refuses a charge that would overdraw. The exception is
    deliberate: usage recorded AFTER a call completes must always land, because the
    call already happened and refusing to record it would hide a real cost. Prevention
    belongs at the pre-dispatch gate, not at the accounting layer.

    The read-decide-write runs under a per-tenant advisory lock (see the module
    docstring for why a row lock on the newest entry is not enough), so two concurrent
    charges cannot both compute from the same starting balance.
    """
    if delta == 0:
        return await get_balance(session, tenant_id=tenant_id)

    await lock_tenant_credits(session, tenant_id)
    current = await _newest_balance(session, tenant_id)
    new_balance = current + delta

    if new_balance < 0 and not allow_negative:
        raise ProblemError.business_rule(
            "insufficient_credits",
            "This account does not have enough credit for that.",
            remediation="Top up the credit balance and try again.",
        )

    # `clock_timestamp()`, NOT `now()`. `now()` is TRANSACTION-start time, so a
    # transaction that did other work first (the post-call pipeline does plenty before
    # it charges) stamps its entry EARLIER than a top-up that started later and
    # committed first — even though the advisory lock correctly serialized them. The
    # ledger then reads back out of write order and `_newest_balance` returns a balance
    # that is missing a real entry. `clock_timestamp()` is the moment of the INSERT,
    # and because the lock is held across read-decide-write it is strictly increasing
    # per tenant.
    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :delta, :reason, :ref, "
            ":balance, clock_timestamp(), CAST(:meta AS jsonb), clock_timestamp())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "delta": delta,
            "reason": reason,
            "ref": ref,
            "balance": new_balance,
            "meta": json.dumps(meta) if meta else None,
        },
    )
    log.info(
        "credit_entry",
        extra={"tenant_id": str(tenant_id), "reason": reason, "balance_after": str(new_balance)},
    )
    return Balance(amount_inr=new_balance, is_low=new_balance < LOW_BALANCE_INR)


class TopUpEntry(NamedTuple):
    """An existing top-up on the ledger. A NamedTuple because both callers of the
    lookup read it differently — one by name, one positionally — and one shape that
    answers both beats a second dataclass that has to be kept in step."""

    entry_id: UUID
    amount_inr: Decimal


async def find_topup(session: AsyncSession, *, tenant_id: UUID, ref: str) -> TopUpEntry | None:
    """Has this payment reference already been credited? THE idempotency lookup for
    every top-up path — the manual UTR route and the Razorpay receiver both call this
    one function, so the two cannot drift apart on the next fix.

    **It takes the lock itself, and that is the point.** Both call sites used to carry
    their own copy of this query and rely on their author remembering to call
    `lock_tenant_credits` first; a check-then-write outside that lock is precisely how
    duplicate pairs got onto this ledger, because two concurrent runs both read "not
    credited yet" and both append. Making the lookup acquire the lock means the
    ordering is not something a future caller can get wrong: there is no way to reach
    this read from outside the critical section. `pg_advisory_xact_lock` is re-entrant
    within a transaction and released at its end, so a caller that also takes the lock
    explicitly (both do, at the top of their transaction, to cover the writes around
    this read as well) costs nothing and deadlocks nothing.

    Scoped to `reason = 'topup'` so a payment reference can never collide with the call
    id a usage row carries in the same column.
    """
    await lock_tenant_credits(session, tenant_id)
    row = (
        await session.execute(
            text(
                "SELECT id, delta FROM credit_ledger WHERE tenant_id = :tid "
                "AND reason = 'topup' AND ref = :ref ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id, "ref": ref},
        )
    ).first()
    if row is None:
        return None
    return TopUpEntry(entry_id=UUID(str(row[0])), amount_inr=Decimal(str(row[1])))


async def charge_for_call(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, amount_inr: Decimal
) -> None:
    """Debit a completed call. Idempotent by `ref` — the post-call pipeline is
    re-runnable, and a ledger that double-charges on a replay is worse than no ledger.

    The dedupe lookup runs UNDER the per-tenant advisory lock, taken before it. A
    re-run is not only a sequential replay: ARQ retries and the reconciliation poller
    can put two runs of one call in flight at the same moment, and a check-then-write
    outside the lock lets both read "not charged yet" and both append. That is the same
    hole the top-up route takes the lock early to close.

    `allow_negative=True`: the call already happened. A cost we refuse to record is a
    cost we later cannot explain.
    """
    if amount_inr <= 0:
        return
    await lock_tenant_credits(session, tenant_id)
    already = (
        await session.execute(
            # `tenant_id` is in the predicate as well as in RLS: it is what makes this
            # an index scan, and it stops a call id ever being read across a scope this
            # session was not supposed to be answering for.
            text(
                "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = :ref "
                "AND reason = 'usage' LIMIT 1"
            ),
            {"tid": tenant_id, "ref": str(call_id)},
        )
    ).first()
    if already:
        return
    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-amount_inr,
        reason="usage",
        ref=str(call_id),
        allow_negative=True,
    )


async def plan_tier_of(session: AsyncSession, tenant_id: UUID) -> str:
    tier = (
        await session.execute(
            text("SELECT plan_tier FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    return str(tier or "managed")


# --- reporting -----------------------------------------------------------------
#
# Two audiences, two panels, one ledger. The CLIENT sees what they used and what it
# will cost them. WE see what it cost us next to that, which is D-12's whole reason
# for putting `unit_cost_paid` on every usage row: margin is a query, not a monthly
# spreadsheet exercise.
#
# The client panel never shows `unit_cost_paid`. Our supplier pricing is commercially
# ours, and a client who can see it is a client negotiating against it.

# Billing months are IST (conventions: UTC in the DB, IST at the edge). A month that
# rolls over at 05:30 IST would put an evening call in the wrong month and make a
# client's invoice disagree with their own diary.
_IST_MONTH = "to_char(occurred_at + interval '5 hours 30 minutes', 'YYYY-MM')"


def current_billing_month() -> str:
    return (datetime.now(UTC) + timedelta(hours=5, minutes=30)).strftime("%Y-%m")


def split_overage(
    *,
    overage_min: Decimal,
    billable_premium: Decimal,
    billable_value: Decimal,
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> tuple[Decimal, Decimal]:
    """Divide the month's overage minutes between the two TTS rungs.

    Returns `(premium_overage, value_overage)`, which ALWAYS add to `overage_min`
    exactly — the second is derived by subtraction rather than computed independently,
    so the two published figures cannot drift by a paisa from the total the client is
    charged on. That matters more than it sounds: the invoice promises that every line
    multiplies out and that the lines sum to the subtotal.

    **A plan with no value rate puts everything on the single rate.** `rate_value is
    None` returns `(overage_min, 0)`, which reproduces the pre-`b1d5c8e73f04` arithmetic
    bit for bit — that is what makes the column safe to add to every existing plan.

    **The included allowance is spent on the DEARER rung first.** A plan with 500
    included minutes and a mix of premium and value calls could allocate the free
    minutes either way, and the allocation decides the bill. Consuming the expensive
    rung first leaves the CHEAPER minutes to be charged for, which is the client's
    favour — the same asymmetry `billing/rates.py` applies when it bills an unprovable
    tier as `value`. It is written as "the dearer rung" rather than "the premium rung"
    so it stays client-favourable even if a founder ever quotes a value rate ABOVE the
    premium one; the rule is about price, not about the label.
    """
    if rate_value is None:
        return overage_min, Decimal("0")

    dearer_is_premium = rate >= rate_value
    dearer = billable_premium if dearer_is_premium else billable_value
    covered = min(included_min, dearer)
    dearer_overage = max(Decimal("0"), dearer - covered)
    # Clamped into [0, overage_min]: the tier sums and the telephony total are two
    # roundings of the same underlying seconds, so they can differ in the last place.
    # The TOTAL is the number that was priced, so it is the one that wins.
    dearer_overage = min(dearer_overage, overage_min)
    cheaper_overage = overage_min - dearer_overage
    if dearer_is_premium:
        return dearer_overage, cheaper_overage
    return cheaper_overage, dearer_overage


async def _tier_totals(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(minutes, our cost) per TTS rung for one billing month, UNQUANTIZED.

    THE one definition of "how many minutes ran on which rung". `tier_usage` presents
    it to two panels and `usage_summary` prices against it; a second query would let the
    panel and the bill disagree about the same month, which is the exact defect
    `billing/rates.py` exists to prevent one layer down.

    The keys are `premium`, `value` and `""` — the third being rows written before tier
    attribution existed, or by a path that could not attribute one. Reporting keeps that
    distinction; pricing folds it into `value`, because a call we cannot prove got the
    premium voice is never charged the premium rate.
    """
    rows = (
        await session.execute(
            # `/ 60.0` is a NUMERIC literal in Postgres, exactly as in `usage_summary`;
            # nothing on this path becomes a float (hard rule 7).
            text(
                "SELECT COALESCE(meta->>'tts_tier', ''), "
                "  COALESCE(SUM(qty) FILTER (WHERE unit_type = 'telephony_s'), 0) / 60.0, "
                "  COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                f"FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH} = :month "
                "GROUP BY 1"
            ),
            {"tid": tenant_id, "month": month},
        )
    ).all()

    minutes = {"premium": Decimal("0"), "value": Decimal("0"), "": Decimal("0")}
    cost = {"premium": Decimal("0"), "value": Decimal("0"), "": Decimal("0")}
    for label, mins, spent in rows:
        # An unrecognised label is treated as unattributed rather than trusted: a tier
        # this module does not know is not a tier it can price.
        key = str(label) if str(label) in ("premium", "value") else ""
        minutes[key] += Decimal(str(mins or 0))
        cost[key] += Decimal(str(spent or 0))
    return minutes, cost


async def usage_summary(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """What the client used this billing month, in their terms.

    Minutes come from `telephony_s`, which is the unit we bill on; the other unit types
    are inputs to OUR cost and are deliberately not shown as separate line items,
    because a client cannot act on "llm_tok_out" and does not buy tokens from us.
    """
    period = month or current_billing_month()
    # WHICH INSTANT THIS MONTH IS PRICED AT, resolved (and the month validated) BEFORE
    # any query runs — a month we cannot parse is a month we cannot pick a plan for, and
    # a 422 up front beats a ₹0.00 statement for `?month=july`.
    priced_at = month_pricing_instant(period)
    row = (
        await session.execute(
            # `tenant_id` is named in the predicate, not left to RLS alone: the plan,
            # the org and the spend state below are all read BY tenant_id, so a session
            # scoped to someone else would otherwise pair this tenant's plan with that
            # tenant's minutes. RLS still fails the query closed; this makes the answer
            # depend on the argument rather than on which session it was handed.
            #
            # `/ 60.0` is a NUMERIC literal in Postgres, so this stays numeric end to
            # end (hard rule 7) — asserted in tests/billing_audit_test.py, because it
            # reads like a float literal and would be a silent disaster as one.
            text(
                "SELECT "
                "  COALESCE(SUM(qty) FILTER (WHERE unit_type = 'telephony_s'), 0) / 60.0, "
                "  COUNT(DISTINCT call_id) "
                f"FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH} = :month"
            ),
            {"tid": tenant_id, "month": period},
        )
    ).first()
    minutes = to_paise(Decimal(str(row[0] if row else 0)))
    calls = int(row[1] or 0) if row else 0

    # WHICH PLAN PRICES THIS MONTH. Not the newest row — the row whose valid-time
    # window contains `priced_at` (`billing/plans.py`). For a closed month that instant
    # is the month's last, so a re-rendered July invoice quotes July's terms however
    # many times a plan has changed since; for the current month it is now, so terms
    # dated to start later this month do not price today.
    plan = (
        await session.execute(
            text(
                # The caps read here are the EFFECTIVE ones — `LEAST(admin, client)`,
                # `billing/caps.py` — so the panel reports the ceiling that actually
                # binds. Reporting the admin's while the client's is stricter would show
                # a client headroom the gate will refuse them.
                plan_in_effect_sql(
                    "monthly_fee, included_min, overage_rate, "
                    f"{EFFECTIVE_CAP_MIN_SQL}, {EFFECTIVE_CAP_SPEND_SQL}, overage_rate_value"
                )
            ),
            {"tid": tenant_id, "at": priced_at},
        )
    ).first()
    if plan is None:
        # Distinguishes "this tenant has no plan" (normal — nothing creates one) from
        # "this tenant HAS plans and none covers the month we are pricing", which is an
        # operator error that would otherwise show up only as a mysteriously free month.
        await warn_no_plan_in_effect(session, tenant_id=tenant_id, at=priced_at)
    included = int(plan[1] or 0) if plan else 0
    overage_rate = Decimal(str(plan[2])) if plan and plan[2] is not None else Decimal("0")
    # NULL is not zero: "this plan quotes no separate value rate" (bill everything at
    # `overage_rate`) and "the value rung is free" are different plans.
    value_rate = Decimal(str(plan[5])) if plan and plan[5] is not None else None
    overage_min = max(Decimal("0"), minutes - included)
    tier_minutes, tier_cost = await _tier_totals(session, tenant_id=tenant_id, month=period)
    overage_premium, overage_value = split_overage(
        overage_min=overage_min,
        billable_premium=tier_minutes["premium"],
        # Unattributed folds in with value: SURFACES §2b's rule is that a call we
        # cannot prove got the premium voice is never charged the premium rate.
        billable_value=tier_minutes["value"] + tier_minutes[""],
        included_min=Decimal(included),
        rate=overage_rate,
        rate_value=value_rate,
    )
    # The UNROUNDED rates are what the client is charged at — they are the plan terms.
    # The rates published beside the cost are `rate_to_display`, which are the same
    # numbers, so the invoice lines' qty * unit reproduce this amount exactly.
    overage_cost = to_paise(
        overage_premium * overage_rate + overage_value * (value_rate or overage_rate)
    )

    # THE LIVE COUNTERS, through the one month-aware reader (`billing/caps.py`) that the
    # compliance gate, the admin directory and the health panel already read. The month
    # is part of the answer, for the same reason it is in `compliance.service
    # .spend_capped`: the flag is only written when a call completes, so a capped
    # tenant's row can sit at last month's cap indefinitely. Reporting that as a live cap
    # would show "capped, 0 minutes left" to a client the gate is now letting dial — the
    # panel contradicting the system.
    #
    # This function used to check the month for `capped` and then read `spend_used` out
    # of the same row WITHOUT it — one predicate, applied to one of the two columns it
    # was written for. That is why the shared reader exists rather than a shared
    # `if`: it returns the counters TOGETHER, so a caller cannot take half the check.
    counters = await read_spend_counters(session, tenant_id=tenant_id)
    # Deliberately the LIVE flag even when an older `?month=` is being viewed: "outgoing
    # calls are paused" is a fact about the account right now, not about the month on
    # screen, and it is what `minutes_left` below has to respect.
    capped = counters.capped

    # Runway framing (teardown adopt #8): "about N minutes left" is what an owner can
    # actually plan around; a rupee balance makes them do the division at the counter.
    # Managed: what remains of the cap. Self-serve: wallet ÷ the list price — priced
    # from the SAME config number the top-up flow uses, so the two can never disagree.
    tier = (
        await session.execute(
            text("SELECT plan_tier FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    minutes_left: int | None = None
    if tier in ("self_serve", "trial"):
        # Credits gate the self-serve motion ONLY, exactly as the compliance gate does
        # (compliance/service.py §2b): a managed client is invoiced against a retainer,
        # so their wallet must not shorten their runway any more than it blocks a dial.
        balance = await get_balance(session, tenant_id=tenant_id)
        rate = get_settings().self_serve_inr_per_min
        if rate > 0 and balance.amount_inr > 0:
            minutes_left = int(balance.amount_inr / rate)
        elif balance.amount_inr <= 0:
            # `Balance.is_exhausted` is `<= 0`, which is the gate's own condition.
            minutes_left = 0
    elif plan and plan[3] is not None:
        minutes_left = max(0, int(Decimal(str(plan[3])) - minutes))

    if capped:
        # `spend_state.capped` is the ONLY cap the gate enforces, and it refuses every
        # outbound call regardless of tier. Offering runway on top of that is a promise
        # the platform will not keep. (Inbound is unaffected by the cap — the gate is
        # outbound-only — but inbound is not something an owner "has minutes left" to
        # spend, so the outbound answer is the honest one for a planning number.)
        minutes_left = 0

    return {
        "month": period,
        "minutes_used": minutes,
        "calls": calls,
        "included_minutes": included,
        "overage_minutes": to_paise(overage_min),
        # The two rungs the overage was actually split across. They add to
        # `overage_minutes` exactly, by construction (`split_overage`), so a client
        # checking the invoice by hand never finds a stray paisa.
        "overage_minutes_premium": to_paise(overage_premium),
        "overage_minutes_value": to_paise(overage_value),
        "overage_cost_inr": overage_cost,
        # The rate the overage was priced at, published so the invoice does not have to
        # re-read `plans` and risk picking a different row than this computation did.
        "overage_rate_inr": rate_to_display(overage_rate),
        # None when this plan quotes no separate value rate — in which case BOTH rungs
        # above were priced at `overage_rate_inr`, and saying None rather than repeating
        # the premium rate is what tells a reader which of those two worlds they are in.
        "overage_rate_value_inr": (rate_to_display(value_rate) if value_rate is not None else None),
        # Quantized to paise like every other money field: NUMERIC(12,4) is the
        # storage precision, two decimals is what a rupee amount means to a reader.
        "monthly_fee_inr": (
            to_paise(Decimal(str(plan[0]))) if plan and plan[0] is not None else None
        ),
        "cap_minutes": int(plan[3]) if plan and plan[3] is not None else None,
        "minutes_left": minutes_left,
        "capped": capped,
        "spend_used_inr": to_paise(_spend_used(period, counters.spend_used, tier_cost)),
    }


def _spend_used(period: str, live: Decimal, tier_cost: dict[str, Decimal]) -> Decimal:
    """What this tenant spent in `period` — from the counter while it is live, from the
    ledger once it is not.

    `spend_state` is ONE row per tenant (PK `tenant_id`), stamped with the month it is
    counting and reset by the meter on rollover. It has no history whatsoever, so it can
    only answer for the current billing month — and `usage_summary` is reachable with
    `?month=2026-07`, where it was reporting the live row's rupees on a closed month's
    statement, beside a `minutes` figure correctly read from `usage_events` for the month
    actually asked about. Two numbers, two months, one panel.

    OPEN month → the live counter, because that is the exact column the cap is enforced
    against (`caps.over_cap_sql` compares it), so the panel and the gate can never tell a
    client two different stories about the same rupees.

    CLOSED month → `_tier_totals`' cost for that month: the ledger, summed by the query
    this function has already run, so there is no second definition of spend and no
    second round trip. The two sources agree by construction — both are the per-call
    `cost.total_inr` the pipeline metered, one accumulated live and one re-summed from
    the `usage_events` rows written in the same transaction. The known exception is the
    ledger's own arithmetic: a leg whose `qty` is zero is priced whole (`_unit_price`)
    and contributes nothing to `qty * unit_cost_paid`, so a zero-duration call reads a
    few paise lighter here. That is the same arithmetic the invoice and the margin panel
    are built on, which is the right thing for a closed month to agree with.
    """
    if period == current_billing_month():
        return live
    return sum(tier_cost.values(), Decimal("0"))


# --- the TTS tier ladder (SURFACES §2b, D-36) ----------------------------------
#
# `usage_events.meta.tts_tier` is written by the post-call pipeline from the voice the
# agent was CONFIGURED with — the engine reports no synthesizer model, so it is an
# assumption carrying its own provenance (`billing/rates.py` has the vendor question in
# full). Everything below reads that one field, so the client panel and the margin panel
# cannot end up telling two different stories about the same call.


async def tier_usage(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Minutes and OUR cost, split by the TTS rung each call was metered on.

    Three buckets, not two, and the third is the honest one: rows written before tier
    attribution existed — or by a path that could not attribute one — carry no tier at
    all. They are reported as `unattributed` rather than folded silently into a rung,
    because "we know this ran on v2" and "we never knew" are different facts.

    For BILLING they are not different: `minutes_billable_value` folds unattributed in
    with value, because SURFACES §2b's rule is that a call we cannot prove got the
    premium voice is never charged the premium rate. Reporting keeps the distinction;
    pricing resolves it in the client's favour.

    Minutes come from `telephony_s` — the same unit `usage_summary` bills on — so the
    three buckets always add up to that panel's `minutes_used` for the same month.
    """
    period = month or current_billing_month()
    # Validated for the same reason `usage_summary` validates it, and by the same
    # function: two panels reading one ledger must not disagree about what a month is.
    parse_billing_month(period)
    minutes, cost = await _tier_totals(session, tenant_id=tenant_id, month=period)

    return {
        "month": period,
        "minutes_premium": to_paise(minutes["premium"]),
        "minutes_value": to_paise(minutes["value"]),
        "minutes_unattributed": to_paise(minutes[""]),
        # What a bill may charge at each rung: unproven never reaches the premium side.
        "minutes_billable_premium": to_paise(minutes["premium"]),
        "minutes_billable_value": to_paise(minutes["value"] + minutes[""]),
        "cost_premium_inr": to_paise(cost["premium"]),
        "cost_value_inr": to_paise(cost["value"]),
        "cost_unattributed_inr": to_paise(cost[""]),
    }


async def record_tier_correction(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    chars: int,
    billed_tier: TtsTier,
    actual_tier: TtsTier,
    ref: str,
    note: str | None = None,
) -> Decimal | None:
    """Correct a call metered on the wrong TTS rung — by APPENDING, never by editing.

    `usage_events` is INSERT-only (hard rule 4), so the wrong row stays exactly where it
    is and a new row carries the difference. `margin_for_tenant` sums
    `qty * unit_cost_paid`, so a `qty` of 1 priced at the delta corrects the month by
    construction, with no reader needing to know a correction happened.

    It is stamped at the ORIGINAL call's `occurred_at`, not at now(): a July call that
    was billed at the wrong rate was wrong in July, and dropping the fix into August
    would leave both months lying. The moment the correction was issued is recorded in
    `meta.issued_at` instead, which is the audit question a date on the row cannot
    answer anyway.

    A CHARACTER COUNT IS REQUIRED — `rates.tts_cost_inr` refuses to invent one, so a
    correction can only be made by someone who actually knows how much speech was
    synthesized (today: from the model vendor's own usage export).

    Returns the delta written, or None when there was nothing to correct — the tiers
    agreed, or this `ref` has already been applied. Idempotent under a per-tenant
    advisory lock, because a replayed ops script must not credit twice.
    """
    delta = tier_correction_inr(chars=chars, billed_tier=billed_tier, actual_tier=actual_tier)
    if delta == 0:
        return None

    # Same lock the credit ledger uses, so the usage correction and the wallet
    # adjustment below are decided inside ONE critical section per tenant.
    await lock_tenant_credits(session, tenant_id)
    already = (
        await session.execute(
            text(
                "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                "AND meta->>'correction_ref' = :ref LIMIT 1"
            ),
            {"tid": tenant_id, "cid": call_id, "ref": ref},
        )
    ).first()
    if already:
        return None

    occurred_at = (
        await session.execute(
            text(
                "SELECT MIN(occurred_at) FROM usage_events "
                "WHERE tenant_id = :tid AND call_id = :cid"
            ),
            {"tid": tenant_id, "cid": call_id},
        )
    ).scalar()

    meta = {
        "kind": "tts_tier_correction",
        "correction_ref": ref,
        "billed_tier": billed_tier,
        "actual_tier": actual_tier,
        # The row asserts the tier that RAN, so `tier_usage` counts its money on the
        # rung the call actually used rather than the one it was mis-billed on.
        "tts_tier": actual_tier,
        "tts_tier_source": "correction",
        "chars": chars,
        "issued_at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :cid, 'other', 1, :cost, "
            "COALESCE(:at, now()), CAST(:meta AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call_id,
            "cost": delta,
            "at": occurred_at,
            "meta": json.dumps(meta),
        },
    )

    # For a self-serve client the wallet IS the bill (D-39): the call was debited at
    # metered cost, so a corrected cost has to move the balance too — as a new entry.
    # Managed clients are invoiced against a retainer and their wallet is not part of
    # the charge, so nothing is written for them.
    if await plan_tier_of(session, tenant_id) in ("self_serve", "trial"):
        wallet_ref = f"tier-correction:{ref}"
        seen = (
            await session.execute(
                text(
                    "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = :ref "
                    "AND reason = 'adjustment' LIMIT 1"
                ),
                {"tid": tenant_id, "ref": wallet_ref},
            )
        ).first()
        if not seen:
            await record_entry(
                session,
                tenant_id=tenant_id,
                # The ledger's sign convention is the wallet's, not the cost ledger's:
                # a NEGATIVE cost correction (we overbilled) is a POSITIVE credit back.
                delta=-delta,
                reason="adjustment",
                ref=wallet_ref,
                meta={"call_id": str(call_id), "billed_tier": billed_tier, "actual": actual_tier},
                # The call already happened; a correction that refuses to record is a
                # correction that leaves the client overcharged.
                allow_negative=True,
            )

    log.info(
        "tts_tier_correction",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "billed_tier": billed_tier,
            "actual_tier": actual_tier,
        },
    )
    return delta


async def margin_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Admin-only: revenue vs OUR cost for one client (D-12).

    Revenue is the plan's monthly fee plus overage — the invoice, not an estimate. Cost
    is the sum of `unit_cost_paid`, which the pipeline stamps per usage row at capture
    time with the fx rate it used, so a later rate move cannot rewrite history.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    cost = (
        await session.execute(
            # NUMERIC * NUMERIC summed as NUMERIC — no float anywhere on the path from
            # `unit_cost_paid` to the rupee figure an operator reads (hard rule 7).
            text(
                "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                f"FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH} = :month"
            ),
            {"tid": tenant_id, "month": usage["month"]},
        )
    ).scalar()
    cost_inr = to_paise(Decimal(str(cost or 0)))
    # Revenue is `usage_summary`'s numbers, not a second derivation: the invoice's
    # subtotal is those same two fields added, so margin and the invoice cannot drift.
    revenue = (usage["monthly_fee_inr"] or Decimal("0")) + usage["overage_cost_inr"]
    margin = to_paise(revenue - cost_inr)
    # Percent is reported as None rather than 0 when there is no revenue: "0% margin"
    # and "nothing billed yet" are different facts and an operator acts differently.
    pct = (
        (margin / revenue * 100).quantize(Decimal("0.1"), rounding=ROUNDING)
        if revenue > 0
        else None
    )
    return {
        "month": usage["month"],
        "minutes_used": usage["minutes_used"],
        "calls": usage["calls"],
        "revenue_inr": to_paise(revenue),
        "cost_inr": cost_inr,
        "margin_inr": margin,
        "margin_pct": pct,
    }


__all__ = [
    "LOW_BALANCE_INR",
    "PAISE",
    "ROUNDING",
    "Balance",
    "CreditReason",
    "TopUpEntry",
    "charge_for_call",
    "current_billing_month",
    "find_topup",
    "get_balance",
    "lock_tenant_credits",
    "margin_for_tenant",
    "plan_tier_of",
    "rate_to_display",
    "record_entry",
    "record_tier_correction",
    "split_overage",
    "tier_usage",
    "to_paise",
    "usage_summary",
]
