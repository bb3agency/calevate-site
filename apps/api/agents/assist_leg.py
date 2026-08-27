"""Which model an ACCOUNT runs, read once, for the dashboard-assist selector.

WHY THIS IS ITS OWN FILE, in one paragraph. `workers/extraction.assist_capability` needs
the tenant's chosen model as a VALUE (it is a pure function of its arguments and must stay
one), and `agents/llm_models` turns a model into a `TenantModelLeg` but reads no database —
that is a stated invariant of both modules, and both are load-bearing. Something has to run
the one-row query in between. Spelling it at each of the three assist surfaces would be the
same SELECT in three places, which is the D-103 defect on the smallest possible scale; this
is the one place the column name is written.

RLS DOES THE SCOPING, exactly as `agents/llm_routes._read_defaults` argues at length: the
`organizations` policy matches on `id`, so this reads the account the session is scoped to
and a wrong id is zero rows rather than a neighbour's. No `WHERE` on the tenant is wanted —
one would be a second, weaker expression of the isolation the policy already enforces.
`deleted_at IS NULL` is not scoping and is not redundant with it; it is the same predicate
every other reader of this row carries.

**IT ANSWERS AT THE ACCOUNT LEVEL, NOT THE AGENT LEVEL, AND THAT IS DELIBERATE.** An agent
may name its own model (`resolve_llm_model`'s first rung), but the assist surfaces this
serves are not per-agent: the copilot is a floating panel over whatever screen is open, and
the re-summarise route acts on a call whose agent may since have been re-pointed. The
question the selector actually asks is "may Calevate run the assistant on the provider this
CLIENT is on", which the account's own choice answers and an agent's override only
narrows. Passing an agent model would make one client's assistant leg change depending on
which call they opened, with no sentence anywhere explaining why.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import resolve_llm_model, tenant_dashboard_leg
from apps.workers.extraction import TenantModelLeg

#: The account's own choice. `id` is not needed — nothing here quotes a plan or a price.
_ORG_MODEL = "SELECT default_llm_model FROM organizations WHERE deleted_at IS NULL"


async def account_assist_leg(session: AsyncSession) -> TenantModelLeg:
    """The model this session's account runs, and whether the assistant may run on it.

    NO `None` RETURN AND NO REFUSAL FOR A MISSING ROW. `resolve_llm_model`'s third rung is
    the platform's own model and is always there, so "this account has not chosen one" and
    "this account row is not visible" both resolve to the platform model — which is exactly
    what the assistant would have run before this seam existed. A refusal here would turn a
    closed account's stale browser tab into a 404 on the assistant instead of the ordinary
    refusal the surface behind it already produces.
    """
    row = (await session.execute(text(_ORG_MODEL))).first()
    chosen: str | None = row[0] if row is not None else None
    resolved = resolve_llm_model(agent_model=None, organization_model=chosen)
    return tenant_dashboard_leg(model=resolved.model)


__all__ = ["account_assist_leg"]
