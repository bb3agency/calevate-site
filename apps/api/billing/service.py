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

Money is NUMERIC INR throughout (hard rule 7). No floats reach this file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

CreditReason = Literal["topup", "usage", "adjustment", "refund"]

# Below this the wallet is "low" — surfaced in the UI, not enforced. Enforcement is
# `balance > 0`; a warning band exists so a client is told before calls start failing.
LOW_BALANCE_INR = Decimal("200.00")


@dataclass(frozen=True, slots=True)
class Balance:
    amount_inr: Decimal
    is_low: bool

    @property
    def is_exhausted(self) -> bool:
        return self.amount_inr <= Decimal("0")


async def get_balance(session: AsyncSession, *, tenant_id: UUID) -> Balance:
    """The newest entry's `balance_after`. One indexed row read, not an aggregate —
    which is exactly why `balance_after` is stored."""
    amount = (
        await session.execute(
            text(
                "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    balance = Decimal(amount) if amount is not None else Decimal("0")
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

    # Serialize every credit write for this tenant for the rest of the transaction.
    # A row lock on the newest entry is NOT sufficient (see the module docstring):
    # READ COMMITTED re-checks the locked row, not the query, so a second writer
    # blocked on it still computes from the pre-insert balance.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"credit:{tenant_id}"},
    )
    previous = (
        await session.execute(
            text(
                "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    current = Decimal(previous) if previous is not None else Decimal("0")
    new_balance = current + delta

    if new_balance < 0 and not allow_negative:
        raise ProblemError.business_rule(
            "insufficient_credits",
            "This account does not have enough credit for that.",
            remediation="Top up the credit balance and try again.",
        )

    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :delta, :reason, :ref, "
            ":balance, now(), CAST(:meta AS jsonb), now())"
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


async def charge_for_call(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, amount_inr: Decimal
) -> None:
    """Debit a completed call. Idempotent by `ref` — the post-call pipeline is
    re-runnable, and a ledger that double-charges on a replay is worse than no ledger.

    `allow_negative=True`: the call already happened. A cost we refuse to record is a
    cost we later cannot explain.
    """
    if amount_inr <= 0:
        return
    already = (
        await session.execute(
            text("SELECT 1 FROM credit_ledger WHERE ref = :ref AND reason = 'usage' LIMIT 1"),
            {"ref": str(call_id)},
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


async def usage_summary(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """What the client used this billing month, in their terms.

    Minutes come from `telephony_s`, which is the unit we bill on; the other unit types
    are inputs to OUR cost and are deliberately not shown as separate line items,
    because a client cannot act on "llm_tok_out" and does not buy tokens from us.
    """
    period = month or current_billing_month()
    row = (
        await session.execute(
            text(
                "SELECT "
                "  COALESCE(SUM(qty) FILTER (WHERE unit_type = 'telephony_s'), 0) / 60.0, "
                "  COUNT(DISTINCT call_id) "
                f"FROM usage_events WHERE {_IST_MONTH} = :month"
            ),
            {"month": period},
        )
    ).first()
    minutes = Decimal(str(row[0] if row else 0)).quantize(Decimal("0.01"))
    calls = int(row[1] or 0) if row else 0

    plan = (
        await session.execute(
            text(
                "SELECT monthly_fee, included_min, overage_rate, hard_cap_min, hard_cap_spend "
                "FROM plans WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).first()
    included = int(plan[1] or 0) if plan else 0
    overage_rate = Decimal(str(plan[2])) if plan and plan[2] is not None else Decimal("0")
    overage_min = max(Decimal("0"), minutes - included)
    # NUMERIC throughout, never float (hard rule 7). Quantize at the boundary only.
    overage_cost = (overage_min * overage_rate).quantize(Decimal("0.01"))

    spend = (
        await session.execute(
            text("SELECT minutes_used, spend_used, capped FROM spend_state WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).first()

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
        balance = await get_balance(session, tenant_id=tenant_id)
        rate = get_settings().self_serve_inr_per_min
        if rate > 0 and balance.amount_inr > 0:
            minutes_left = int(balance.amount_inr / rate)
        elif balance.amount_inr <= 0:
            minutes_left = 0
    elif plan and plan[3] is not None:
        minutes_left = max(0, int(Decimal(str(plan[3])) - minutes))

    return {
        "month": period,
        "minutes_used": minutes,
        "calls": calls,
        "included_minutes": included,
        "overage_minutes": overage_min.quantize(Decimal("0.01")),
        "overage_cost_inr": overage_cost,
        # Quantized to paise like every other money field: NUMERIC(12,4) is the
        # storage precision, two decimals is what a rupee amount means to a reader.
        "monthly_fee_inr": (
            Decimal(str(plan[0])).quantize(Decimal("0.01"))
            if plan and plan[0] is not None
            else None
        ),
        "cap_minutes": int(plan[3]) if plan and plan[3] is not None else None,
        "minutes_left": minutes_left,
        "capped": bool(spend[2]) if spend else False,
        "spend_used_inr": (
            Decimal(str(spend[1])).quantize(Decimal("0.01")) if spend else Decimal("0.00")
        ),
    }


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
            text(
                "SELECT COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                f"FROM usage_events WHERE {_IST_MONTH} = :month"
            ),
            {"month": usage["month"]},
        )
    ).scalar()
    cost_inr = Decimal(str(cost or 0)).quantize(Decimal("0.01"))
    revenue = (usage["monthly_fee_inr"] or Decimal("0")) + usage["overage_cost_inr"]
    margin = (revenue - cost_inr).quantize(Decimal("0.01"))
    # Percent is reported as None rather than 0 when there is no revenue: "0% margin"
    # and "nothing billed yet" are different facts and an operator acts differently.
    pct = (margin / revenue * 100).quantize(Decimal("0.1")) if revenue > 0 else None
    return {
        "month": usage["month"],
        "minutes_used": usage["minutes_used"],
        "calls": usage["calls"],
        "revenue_inr": revenue.quantize(Decimal("0.01")),
        "cost_inr": cost_inr,
        "margin_inr": margin,
        "margin_pct": pct,
    }


__all__ = [
    "LOW_BALANCE_INR",
    "Balance",
    "CreditReason",
    "charge_for_call",
    "current_billing_month",
    "get_balance",
    "margin_for_tenant",
    "plan_tier_of",
    "record_entry",
    "usage_summary",
]
