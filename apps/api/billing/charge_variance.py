"""What the voice platform charged for a client's calls against what we metered (D-840).

The hourly reconciler (`apps/workers/engine_charges.py`) records each settled call's charge on
`calls.engine_charged_inr` and alarms on a mismatch, but it never corrects the ledger: the only
compensating rows it writes are the fee restatement and the fee correction, and a rate
variance is not one of them (`unit_cost_paid` stays the attested rate, hard rule 7). So the
variance is SHOWN, per call and per month, on the admin money board, where an operator can see
which attested rate no longer matches the invoice.

A call's vendor cost is its charge times one plus the wallet top-up fee in force when it was
metered; our metered cost is its minute rows (`engine_minutes.minute_cost_rows`). A call with
an unpriced minute row is left out: there is nothing metered to compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.cost_attestations import WALLET_TOPUP_FEE_SUBJECTS
from apps.api.billing.engine_minutes import minute_cost_rows
from apps.api.billing.plans import ist_month_window
from apps.api.billing.rates import MONEY_Q, ROUNDING

#: How many calls the board names, largest variance first. Bounded so the response does not
#: grow with a client's call count.
MAX_VARIANCE_CALLS: Final = 10

_PER_CALL_SQL = (
    "SELECT c.id, c.engine_charged_inr, sum(u.qty * u.unit_cost_paid), "
    "bool_or(u.unit_cost_paid IS NULL), "
    "COALESCE((SELECT a.value FROM platform_cost_attestations a WHERE a.subject = :subject "
    "AND a.effective_from <= min(u.occurred_at) ORDER BY a.effective_from DESC LIMIT 1), 0), "
    # What a person recognises a call by: when, which agent, how long. Grouped by the key,
    # so the call's own columns are single-valued.
    "COALESCE(c.started_at, c.created_at), c.duration_s, "
    "(SELECT ag.name FROM agents ag WHERE ag.id = c.agent_id) "
    "FROM calls c JOIN usage_events u ON u.call_id = c.id AND u.tenant_id = c.tenant_id "
    f"AND {minute_cost_rows('u.')} "
    "WHERE c.tenant_id = :tid AND c.engine_charged_inr IS NOT NULL "
    "AND c.created_at >= :month_from AND c.created_at < :month_to GROUP BY c.id"
)


@dataclass(frozen=True, slots=True)
class CallVariance:
    call_id: UUID
    at: datetime
    duration_s: int | None
    agent_name: str | None
    #: The charge with the wallet fee, what the call cost us at the platform's own figure.
    vendor_inr: Decimal
    metered_inr: Decimal

    @property
    def variance_inr(self) -> Decimal:
        """Metered minus the platform's figure: positive when we metered more."""
        return self.metered_inr - self.vendor_inr


@dataclass(frozen=True, slots=True)
class ChargeVariance:
    calls: int
    vendor_inr: Decimal
    metered_inr: Decimal
    #: The calls with the largest variance either way, at most `MAX_VARIANCE_CALLS`.
    largest: tuple[CallVariance, ...]

    @property
    def variance_inr(self) -> Decimal:
        return self.metered_inr - self.vendor_inr


async def month_charge_variance(
    session: AsyncSession, *, tenant_id: UUID, month: str, engine: str
) -> ChargeVariance | None:
    """The month's reconciled calls for one client; None when none has a recorded charge.
    Run inside the client's own `tenant_session`."""
    start, end = ist_month_window(month)
    subject = WALLET_TOPUP_FEE_SUBJECTS.get(engine, "")
    rows = (
        await session.execute(
            text(_PER_CALL_SQL),
            {"tid": tenant_id, "subject": subject, "month_from": start, "month_to": end},
        )
    ).all()
    calls: list[CallVariance] = []
    for call_id, charged, metered, unpriced, fee, at, duration_s, agent_name in rows:
        if unpriced or metered is None:
            continue
        vendor = (Decimal(str(charged)) * (Decimal(1) + Decimal(str(fee)))).quantize(
            MONEY_Q, rounding=ROUNDING
        )
        calls.append(
            CallVariance(
                call_id=UUID(str(call_id)),
                at=at,
                duration_s=duration_s,
                agent_name=agent_name,
                vendor_inr=vendor,
                metered_inr=Decimal(str(metered)).quantize(MONEY_Q, rounding=ROUNDING),
            )
        )
    if not calls:
        return None
    largest = sorted(calls, key=lambda c: abs(c.variance_inr), reverse=True)
    return ChargeVariance(
        calls=len(calls),
        vendor_inr=sum((c.vendor_inr for c in calls), Decimal(0)),
        metered_inr=sum((c.metered_inr for c in calls), Decimal(0)),
        largest=tuple(largest[:MAX_VARIANCE_CALLS]),
    )


__all__ = ["MAX_VARIANCE_CALLS", "CallVariance", "ChargeVariance", "month_charge_variance"]
