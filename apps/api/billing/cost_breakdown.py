"""What one client has cost Calevate over a window, split by what the money bought.

Three admin screens report this and they must not disagree: the trial panel ("cost to
Calevate so far", counted from the trial's own start), the Spend screen and the Overview
(both counted over the IST billing month). Before this module each summed `usage_events`
its own way. The trial panel summed every row; the margin read and the Spend header exclude
the AI units by design (D-127 G-3: absorbed AI is not a call cost); the AI line was a
separate reader shown only on Spend. A trial client whose only spend was the assistant
therefore read ₹1.08 on one screen and nothing on the other two.

The split is a partition of `total_inr`:

- calls: non-AI rows with a `call_id`, priced by `billing/service._ROW_COST_SQL`, the same
  expression `margin_for_tenant` uses, so `calls_inr + other_inr` is the margin's cost;
- other: non-AI rows with no call (today only `number_rental`);
- AI: `billing/ai_quota.read_ai_usage_between` with the free and absorbed features
  included, the same reader the allowance and the fleet board use. Its knowledge part
  (`kb_used_inr`) is a component of `ai.used_inr`, never added to it.

AI rows are priced `qty * unit_cost_paid` and never through `_ROW_COST_SQL`: on the AI
ledger a zero `qty` means zero tokens (an embedding's output leg), whereas `_ROW_COST_SQL`
reads a zero-`qty` call row as carrying its whole leg cost (D-370). Pricing an AI row that
way would charge an embedding its per-thousand output price once per request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import AiUsage, read_ai_usage_between
from apps.api.billing.plans import ist_month_window
from apps.api.billing.service import _NOT_AI_UNITS, _ROW_COST_SQL, to_paise

_NON_AI_SQL = (
    f"SELECT COALESCE(SUM({_ROW_COST_SQL}) FILTER (WHERE call_id IS NOT NULL), 0), "
    "COUNT(DISTINCT call_id), "
    f"COALESCE(SUM({_ROW_COST_SQL}) FILTER (WHERE call_id IS NULL), 0) "
    "FROM usage_events "
    # `tenant_id` in the predicate as well as in RLS, for `usage_summary`'s reason: the
    # answer depends on the argument, and RLS still fails the query closed.
    f"WHERE tenant_id = :tid AND occurred_at >= :start AND occurred_at < :end AND {_NOT_AI_UNITS}"
)


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Our supplier cost for one tenant over `[start, end)`. Operator-only figures."""

    calls_inr: Decimal
    calls: int
    other_inr: Decimal
    ai: AiUsage

    @property
    def assistant_inr(self) -> Decimal:
        """AI that is not knowledge preparation: the assistant, its standby, re-summarise,
        script drafting, caller memory and post-call extraction."""
        return self.ai.used_inr - self.ai.kb_used_inr

    @property
    def assistant_requests(self) -> int:
        return self.ai.requests - self.ai.kb_requests

    @property
    def total_inr(self) -> Decimal:
        return self.calls_inr + self.other_inr + self.ai.used_inr


async def read_cost_breakdown(
    session: AsyncSession, *, tenant_id: UUID, start: datetime, end: datetime
) -> CostBreakdown:
    """The one sum of what a tenant cost us over a window, partitioned.

    Must run in the tenant's own `tenant_session`: `usage_events` is FORCE RLS and an
    untenanted session reads zero rows.
    """
    row = (
        await session.execute(text(_NON_AI_SQL), {"tid": tenant_id, "start": start, "end": end})
    ).one()
    ai = await read_ai_usage_between(
        session, tenant_id=tenant_id, start=start, end=end, include_free=True
    )
    return CostBreakdown(
        calls_inr=Decimal(str(row[0] or 0)),
        calls=int(row[1] or 0),
        other_inr=Decimal(str(row[2] or 0)),
        ai=ai,
    )


async def read_month_cost_breakdown(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> CostBreakdown:
    """`read_cost_breakdown` over one IST billing month (`plans.ist_month_window`)."""
    start, end = ist_month_window(month)
    return await read_cost_breakdown(session, tenant_id=tenant_id, start=start, end=end)


class CostBreakdownOut(BaseModel):
    """`CostBreakdown` on the wire, admin realm only: every figure is `unit_cost_paid`.

    Rupees are exact strings through `to_paise`, like every other rupee the admin money
    screens publish. `total_inr` is computed once here so no screen adds strings together.
    """

    model_config = ConfigDict(extra="forbid")

    total_inr: str
    calls_inr: str
    calls: int
    #: Non-AI rows with no call: today only `number_rental`.
    other_inr: str
    #: AI that is not knowledge preparation (the assistant, its standby, re-summarise,
    #: script drafting, caller memory, post-call extraction), and its distinct actions.
    assistant_inr: str
    assistant_requests: int
    #: Preparing what the client added to their knowledge (`KB_INGESTION_FEATURES`).
    knowledge_inr: str
    knowledge_requests: int

    @classmethod
    def of(cls, breakdown: CostBreakdown) -> CostBreakdownOut:
        return cls(
            total_inr=str(to_paise(breakdown.total_inr)),
            calls_inr=str(to_paise(breakdown.calls_inr)),
            calls=breakdown.calls,
            other_inr=str(to_paise(breakdown.other_inr)),
            assistant_inr=str(to_paise(breakdown.assistant_inr)),
            assistant_requests=breakdown.assistant_requests,
            knowledge_inr=str(to_paise(breakdown.ai.kb_used_inr)),
            knowledge_requests=breakdown.ai.kb_requests,
        )


__all__ = [
    "CostBreakdown",
    "CostBreakdownOut",
    "read_cost_breakdown",
    "read_month_cost_breakdown",
]
