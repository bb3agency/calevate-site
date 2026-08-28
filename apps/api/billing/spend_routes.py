"""Where every rupee went, in BOTH realms — three routes over ONE computation.

`billing/attribution.py` attributes a tenant-month to its calls and its agents, both
directions of the money, once. This file renders it, and the ONLY thing it decides is
WHO SEES WHICH HALF:

    GET /v1/billing/spend                     client  — what THEY were charged, itemised
    GET /v1/admin/tenants/{tenant_id}/spend   admin   — the same, plus what WE paid
    GET /v1/admin/spend                       admin   — one row per live client

**THE SPLIT IS TWO SEPARATE MODELS, NOT ONE MODEL AND A FLAG.** `unit_cost_paid` is our
supplier pricing (`admin/routes.py::tenant_margin` and `crm/schemas.UsagePanelOut` both
say so already), and a client who can see it is a client negotiating against it. The
client models below declare no cost-shaped field at all and are `extra="forbid"`, so the
exclusion is a property of the type rather than of a branch somebody could invert — and
`tests/spend_attribution_test.py` reads the model's own field list to prove it, so a
later widening fails a test rather than reaching a browser.

Deliberately NOT achieved by subclassing the client model: a shared base is a place to
add a field, and the one field that must never be added is the whole point of the file.

Money is a STRING on every one of these, like every other billing response: the values
are `Decimal` (hard rule 7) and `Number()` on INR is how ₹10,159.00 becomes
₹10,158.999999999998.

These routers are NOT mounted here — the integrator mounts them (`main.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.billing import service as billing
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.attribution import (
    AgentAttribution,
    CallAttribution,
    PeriodAttribution,
    period_attribution,
)
from apps.api.billing.service import to_paise
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])
client_router = APIRouter(prefix="/v1/billing/spend", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this is `spend_routes.py`, which is exactly how `cap_routes.py`,
# `credit_routes.py` and `ai_quota_routes.py` already declare theirs.
#
# The CLIENT reader is realm `any` (the default), like `GET /v1/usage` and
# `GET /v1/billing/invoice` beside it: `billing:read` is not in `MUTATING_PERMISSIONS`, so
# a support person inside a read-only view-as session (D-22) sees exactly the page the
# client is looking at — which is the property `tests/impersonation_reads_test.py` exists
# to keep.
SpendReader = Annotated[Principal, Depends(requires("billing:read"))]
AdminSpendReader = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]

#: How many calls one response may itemise. The rollups above it are always the WHOLE
#: month — an allocation has to see its own denominator — so this bounds the payload and
#: never the arithmetic, and `truncated` says plainly when a month has more.
DEFAULT_CALLS = 50
MAX_CALLS = 500

#: The fleet roll-up's walk budget, and the same trade `admin/health.py::WALK_BUDGET_S`
#: makes: a money board that silently dropped the client at the bottom would be worse
#: than a slow one, so nothing here truncates — it logs and names the remedy.
FLEET_BUDGET_S = 10.0

#: Live clients only, exactly as the health board scopes its walk: an archive of churned
#: tenants must not become a per-open cost on a page an operator refreshes.
_ENDED_STATUSES = ("churned", "suspended")
_DIRECTORY = (
    "SELECT id, name, slug, plan_tier FROM organizations "
    " WHERE deleted_at IS NULL AND status <> ALL(:ended) ORDER BY name"
)


class Strict(BaseModel):
    """`extra="forbid"` — the response model IS the output whitelist (BACKEND-PATTERNS §3)."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- the CLIENT's half


class AgentChargeOut(Strict):
    """What one agent added to this month's bill. No cost field, and there never is one."""

    #: Null only for calls whose agent row is unreadable, which RLS makes unreachable for
    #: a usage row in the same tenant — it is typed nullable because the join is a LEFT
    #: JOIN and a schema that cannot express a missing row invites a 500 instead of a gap.
    agent_id: str | None
    agent_name: str | None
    calls: int
    minutes: str
    charged_inr: str


class CallChargeOut(Strict):
    """One call, and what it added to this month's bill."""

    call_id: str
    agent_id: str | None
    agent_name: str | None
    #: ISO-8601, or null for a call that never started.
    started_at: str | None
    direction: str | None
    minutes: str
    charged_inr: str


class SpendOut(Strict):
    """GET /v1/billing/spend — this month's bill, itemised by agent and by call."""

    month: str
    #: `wallet_debit` = the rupees this call actually took off your balance.
    #: `allocated` = this call's share of the month's calling charge, by its minutes at
    #: its own voice rung's rate. The screen must say which; they are different claims.
    charge_basis: Literal["wallet_debit", "allocated"]
    calls: int
    minutes_used: str
    #: The monthly fee, published on its own and deliberately not divided across calls: it
    #: buys the account rather than any particular minute.
    retainer_inr: str | None
    #: The month's calling charge at this account's own rate — the SAME figure
    #: `GET /v1/usage` publishes as `overage_cost_inr` on a managed plan, and the list
    #: price times the month's minutes on a prepaid one. The retainer above is not in it.
    period_charge_inr: str
    #: What the rows below add up to, exactly as published.
    itemised_charge_inr: str
    #: `period_charge_inr - itemised_charge_inr`. ₹0.00 on the `allocated` basis; on the
    #: wallet basis it is per-call display rounding plus the documented gap between the
    #: sum of wallet debits and the panel's own month figure.
    itemisation_residual_inr: str
    #: Why the residual is not zero, from a closed vocabulary. Null when it IS zero.
    residual_reason: str | None
    by_agent: list[AgentChargeOut]
    #: The costliest calls first, capped at `limit`.
    top_calls: list[CallChargeOut]
    top_calls_truncated: bool


# ------------------------------------------------------------------ the ADMIN's half


class AgentSpendOut(Strict):
    """One agent: what the client paid, what we paid, and the difference."""

    agent_id: str | None
    agent_name: str | None
    calls: int
    minutes: str
    charged_inr: str
    #: OUR supplier cost. Admin realm only.
    cost_inr: str
    #: `charged_inr - cost_inr` — the CALLING margin. The retainer is not in it (it is
    #: published once, at the top, un-allocated), so this is not the margin card's figure
    #: for a managed client and must not be labelled as if it were.
    margin_inr: str
    #: At least one of this agent's cost rows was priced in a currency the vendor's
    #: payload did not state (OPERATIONS §2 gate 7).
    cost_currency_assumed: bool


class CallSpendOut(Strict):
    """One call, both directions."""

    call_id: str
    agent_id: str | None
    agent_name: str | None
    started_at: str | None
    direction: str | None
    minutes: str
    charged_inr: str
    cost_inr: str
    margin_inr: str
    cost_currency_assumed: bool


class UnitSpendOut(Strict):
    """What one metered unit type contributed to OUR cost.

    `qty` is not money and is not rounded like it — seconds, minutes and character counts
    are published as the ledger holds them.
    """

    unit_type: str
    qty: str
    cost_inr: str


class UnattributedSpendOut(Strict):
    """Cost this month that belongs to no call.

    `number_rental` is the only unit that can land here and nothing writes one: under
    Model B a client rents their number from their own operator, not from us
    (`campaigns/provisioning.py`). Kept because a total that claims to be a partition
    must not silently stop being one if a callless unit is ever metered.
    """

    minutes: str
    cost_inr: str


class AbsorbedAiSpendOut(Strict):
    """The dashboard-AI cost Calevate ABSORBED for this client this month (D-127 G-3).

    Admin realm only, and deliberately SEPARATE from the four margin figures above it. Our
    dashboard-AI cost (the re-summarise, the script draft and the in-app copilot) is metered
    per tenant under `ai_assist_ktok_*` and is NOT billed to the client — so it is not
    revenue, it is not a call cost, and it is not in `cost_inr`/`margin_inr`. Folding it
    into the call margin would add cost with no matching revenue and break the
    `sum(by_unit.cost_inr) == cost_inr` partition the whole page rests on (the exact reason
    `attribution._CALL_ROWS_SQL` filters `_NOT_AI_UNITS`).

    But an operator reading "which client is costing us money" has to be able to see it: a
    client with zero calls and a busy copilot costs us real rupees this money board would
    otherwise report as ₹0.00. So it is published here as its own line, sourced from
    `billing/ai_quota.py::read_ai_quota` — the ONE reader of the AI ledger, not a second
    spelling of its SQL — which is the same computation the client's AI assistance screen
    and the per-tenant ceiling already use.
    """

    #: OUR absorbed cost, exact paise. `read_ai_quota.used_inr` summed from `usage_events`
    #: at the price each assist actually ran at (`record_ai_assist_usage`), so a month during
    #: which `azure_openai_model` was flipped holds both models' rows at their own prices.
    used_inr: str
    #: Distinct AI-assist actions this month — `COUNT(DISTINCT ref)`, one per user action
    #: across every assist surface (copilot, re-summarise, script draft), never per model
    #: turn. The number an operator counts, beside the rupees that actually protect us.
    requests: int


class TenantSpendOut(Strict):
    """GET /v1/admin/tenants/{tenant_id}/spend — one client's month, both directions.

    The four header figures are D-12's margin, in D-12's OWN definitions — the retainer
    plus `calling_revenue_inr` against the sum of `_ROW_COST_SQL`, with `margin_pct` the
    one shared function `margin_for_tenant` and the fleet board both call. They are folded
    out of `period_attribution`'s single scan rather than read from a second
    `margin_for_tenant` call, and that is a partition fix rather than a shortcut: a second
    call is a second statement at a second instant over an append-only table the meter
    writes to all month, so on an open month the header's `cost_inr` could exceed the
    `by_unit` lines beneath it by one completing call — the parts silently not adding up,
    on the page whose whole promise is that they do. Same rows, same expressions, so on a
    month nobody is dialling in this is `margin_for_tenant` to the paisa, which is the
    identity `tests/spend_attribution_test.py` pins.
    """

    month: str
    plan_tier: str
    charge_basis: Literal["wallet_debit", "allocated"]
    calls: int
    minutes_used: str
    retainer_inr: str | None
    #: The retainer plus this month's calling charge — `margin_for_tenant`'s own two
    #: halves, which is why `retainer_inr + period_charge_inr == revenue_inr` exactly.
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    #: Null rather than "0.0" when nothing has been billed: "0% margin" and "nothing
    #: billed yet" are different facts.
    margin_pct: str | None
    #: The client's own itemisation anchor, so an operator reading this page and a client
    #: reading theirs are looking at the same rupees.
    period_charge_inr: str
    itemised_charge_inr: str
    itemisation_residual_inr: str
    residual_reason: str | None
    #: THE HONESTY ABOUT OUR COST (OPERATIONS §2 gate 7). `cost_currency_stated` is False
    #: whenever any row recorded that WE chose the currency rather than the vendor naming
    #: it — which is every row today, because the vendor's execution object declares no
    #: currency at all. Every cost figure on this page is scaled by that assumption; no
    #: client-facing figure is, because a client is priced off minutes at their own rate.
    cost_currency: str | None
    cost_currency_stated: bool
    #: Absent on every month that has no callless cost row.
    unattributed: UnattributedSpendOut | None
    #: OUR absorbed dashboard-AI cost (D-127 G-3), published on its own and NOT in the
    #: margin above. Null when this client generated no AI-assist usage this month — "they
    #: ran the copilot and it cost us ₹X" and "they never opened it" are different facts an
    #: operator acts on differently. See `AbsorbedAiSpendOut`.
    ai_assist: AbsorbedAiSpendOut | None
    by_unit: list[UnitSpendOut]
    by_agent: list[AgentSpendOut]
    top_calls: list[CallSpendOut]
    top_calls_truncated: bool


class FleetTenantOut(Strict):
    """One client on the fleet board."""

    tenant_id: str
    name: str
    slug: str
    plan_tier: str
    minutes_used: str
    calls: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    margin_pct: str | None


class FleetSpendOut(Strict):
    """GET /v1/admin/spend — every live client's month, worst margin first.

    The totals are sums of the rows, computed here rather than queried: `usage_events` is
    FORCE RLS'd and an untenanted session sees zero rows by design, so a cross-tenant
    `SUM` is unaskable in app code and reaching for the admin DB role to get one would
    break hard rule 1. `billing/models.PlatformAiSpend` records the same constraint and
    the same answer one ledger over. Each client's numbers are read INSIDE that client's
    own `tenant_session`, so no query here sees two tenants at once.
    """

    month: str
    clients: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    margin_pct: str | None
    tenants: list[FleetTenantOut]


# ------------------------------------------------------------------------ rendering
#
# `str(Decimal)` and nothing else: no formatting, no locale, no rounding. Every figure
# reaching here has already been quantized by `billing/service.to_paise` or allocated by
# `allocate_paise`, and re-rounding at the boundary is how two surfaces publish two
# spellings of one rupee (D-375).


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _agent_charge(agent: AgentAttribution) -> AgentChargeOut:
    return AgentChargeOut(
        agent_id=str(agent.agent_id) if agent.agent_id else None,
        agent_name=agent.agent_name,
        calls=agent.calls,
        minutes=str(agent.minutes),
        charged_inr=str(agent.charged_inr),
    )


def _call_charge(call: CallAttribution) -> CallChargeOut:
    return CallChargeOut(
        call_id=str(call.call_id),
        agent_id=str(call.agent_id) if call.agent_id else None,
        agent_name=call.agent_name,
        started_at=call.started_at.isoformat() if call.started_at else None,
        direction=call.direction,
        minutes=str(call.minutes),
        charged_inr=str(call.charged_inr),
    )


def _agent_spend(agent: AgentAttribution) -> AgentSpendOut:
    return AgentSpendOut(
        agent_id=str(agent.agent_id) if agent.agent_id else None,
        agent_name=agent.agent_name,
        calls=agent.calls,
        minutes=str(agent.minutes),
        charged_inr=str(agent.charged_inr),
        cost_inr=str(agent.cost_inr),
        margin_inr=str(agent.charged_inr - agent.cost_inr),
        cost_currency_assumed=agent.cost_currency_assumed,
    )


def _call_spend(call: CallAttribution) -> CallSpendOut:
    return CallSpendOut(
        call_id=str(call.call_id),
        agent_id=str(call.agent_id) if call.agent_id else None,
        agent_name=call.agent_name,
        started_at=call.started_at.isoformat() if call.started_at else None,
        direction=call.direction,
        minutes=str(call.minutes),
        charged_inr=str(call.charged_inr),
        cost_inr=str(call.cost_inr),
        margin_inr=str(call.charged_inr - call.cost_inr),
        cost_currency_assumed=call.cost_currency_assumed,
    )


def _by_charge(period: PeriodAttribution) -> list[CallAttribution]:
    """The client's ordering: what drove MY bill. Ties by cost, then by id — never by
    dict order, so two renders of one closed month list the same calls in the same
    places."""
    return sorted(period.by_call, key=lambda c: (-c.charged_inr, -c.cost_inr, str(c.call_id)))


def _by_cost(period: PeriodAttribution) -> list[CallAttribution]:
    """The operator's ordering: what cost US the most."""
    return sorted(period.by_call, key=lambda c: (-c.cost_inr, -c.charged_inr, str(c.call_id)))


# -------------------------------------------------------------------------- routes


@client_router.get(
    "",
    response_model=SpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This month's bill, itemised by agent and by call",
    description=(
        "Every rupee on this account's calling charge, attributed to the agent and the "
        "call that produced it. `charge_basis` says what kind of number the per-call "
        "figure is: `wallet_debit` is the exact amount taken off a prepaid balance for "
        "that call, `allocated` is that call's share of a month priced as a whole. "
        "Requires `billing:read`, which account owners hold and staff do not. Calevate's "
        "own supplier cost never appears here."
    ),
)
async def my_spend(
    session: Session,
    principal: SpendReader,
    month: str | None = None,
    limit: int = Query(DEFAULT_CALLS, ge=1, le=MAX_CALLS),
) -> SpendOut:
    """The tenant comes from the PRINCIPAL — there is no id to tamper with, and `session`
    is RLS-scoped to that principal's own tenant, so another account's month is not
    merely forbidden but unaddressable (hard rule 1)."""
    assert principal.tenant_id is not None
    period = await period_attribution(session, tenant_id=principal.tenant_id, month=month)
    ranked = _by_charge(period)
    return SpendOut(
        month=period.month,
        charge_basis=period.charge_basis,
        calls=period.calls,
        minutes_used=str(period.minutes),
        retainer_inr=_money(period.retainer_inr),
        period_charge_inr=str(period.period_charge_inr),
        itemised_charge_inr=str(period.itemised_charge_inr),
        itemisation_residual_inr=str(period.itemisation_residual_inr),
        residual_reason=period.residual_reason,
        by_agent=[_agent_charge(a) for a in period.by_agent],
        top_calls=[_call_charge(c) for c in ranked[:limit]],
        top_calls_truncated=len(ranked) > limit,
    )


@router.get(
    "/tenants/{tenant_id}/spend",
    response_model=TenantSpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="One client's month, both directions — what we paid, what we charged, margin",
)
async def tenant_spend(
    tenant_id: UUID,
    session: AdminSession,
    _: AdminSpendReader,
    month: str | None = None,
    limit: int = Query(DEFAULT_CALLS, ge=1, le=MAX_CALLS),
) -> TenantSpendOut:
    """Admin realm only, for the reason `tenant_margin` is: `unit_cost_paid` is our
    supplier pricing.

    Runs the reads inside the client's own `tenant_session` because `usage_events`,
    `calls` and `agents` are RLS'd and stay that way — `app.admin` opens the client
    DIRECTORY, never their data (migration b57e2f9c4a13). The existence check comes first
    for the reason it does on the margin card: a mistyped id and a client with no usage
    both aggregate to zero, and a ₹0 page about a client that does not exist is worse
    than a 404.

    ONE ATTRIBUTION, and the margin is folded out of it — see `TenantSpendOut` for why a
    second `margin_for_tenant` read would let this page's header disagree with its own
    lines. It also removes the whole question of the two reads landing either side of a
    month boundary, which is what `month=period.month` used to have to defend against.
    """
    if not await admin_service.tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")
    async with tenant_session(tenant_id) as scoped:
        period = await period_attribution(scoped, tenant_id=tenant_id, month=month)
        # OUR absorbed dashboard-AI cost, read in the SAME scope and for the SAME resolved
        # month (`period.month`, already validated by the attribution above), through the
        # one reader of the AI ledger. It is `_NOT_AI_UNITS`-excluded from `period` by
        # design — see `AbsorbedAiSpendOut` — so this is where the copilot spend a client
        # generated becomes visible on the money board an operator opens.
        ai = await read_ai_quota(scoped, tenant_id=tenant_id, month=period.month)
    margin = _margin_of(period)
    ranked = _by_cost(period)
    return TenantSpendOut(
        month=period.month,
        plan_tier=period.plan_tier,
        charge_basis=period.charge_basis,
        calls=period.calls,
        minutes_used=str(period.minutes),
        retainer_inr=_money(period.retainer_inr),
        revenue_inr=str(margin.revenue_inr),
        cost_inr=str(margin.cost_inr),
        margin_inr=str(margin.margin_inr),
        margin_pct=_money(margin.margin_pct),
        period_charge_inr=str(period.period_charge_inr),
        itemised_charge_inr=str(period.itemised_charge_inr),
        itemisation_residual_inr=str(period.itemisation_residual_inr),
        residual_reason=period.residual_reason,
        cost_currency=period.cost_currency,
        cost_currency_stated=period.cost_currency_stated,
        unattributed=(
            None
            if period.unattributed is None
            else UnattributedSpendOut(
                minutes=str(period.unattributed.minutes),
                cost_inr=str(period.unattributed.cost_inr),
            )
        ),
        # Published only when there is something to show: `requests_used` is the
        # `COUNT(DISTINCT ref)` over the AI unit types, so > 0 means this client actually
        # ran an assist this month. `used_inr` goes through `to_paise` like every other
        # rupee on this response.
        ai_assist=(
            AbsorbedAiSpendOut(used_inr=str(to_paise(ai.used_inr)), requests=ai.requests_used)
            if ai.requests_used > 0
            else None
        ),
        by_unit=[
            UnitSpendOut(unit_type=u.unit_type, qty=str(u.qty), cost_inr=str(u.cost_inr))
            for u in period.by_unit
        ],
        by_agent=[_agent_spend(a) for a in period.by_agent],
        top_calls=[_call_spend(c) for c in ranked[:limit]],
        top_calls_truncated=len(ranked) > limit,
    )


@dataclass(frozen=True, slots=True)
class _Margin:
    """D-12's margin for one attributed month. Derived, never separately queried."""

    revenue_inr: Decimal
    cost_inr: Decimal
    margin_inr: Decimal
    margin_pct: Decimal | None


def _margin_of(period: PeriodAttribution) -> _Margin:
    """`margin_for_tenant`'s arithmetic over the attribution's own single scan.

    Revenue is the retainer plus the month's calling charge, which is exactly the pair
    `margin_for_tenant` adds — `period_charge_inr` IS `calling_revenue_inr` for the month
    (`billing/attribution.py`), and the retainer is `usage_summary.monthly_fee_inr`, the
    same field. Cost is the sum of `_ROW_COST_SQL` the breakdown beneath it partitions.
    `margin_pct` is the one shared function, never a second copy of the no-revenue rule.

    Both addends are already paise-exact, so `to_paise` here rounds nothing that was not
    rounded the same way one function over; it is spelled anyway because every money field
    in every billing response goes through it and a field that skipped it would be the one
    that renders four decimals.
    """
    revenue = (period.retainer_inr or Decimal("0.00")) + period.period_charge_inr
    margin = to_paise(revenue - period.cost_inr)
    return _Margin(
        revenue_inr=to_paise(revenue),
        cost_inr=period.cost_inr,
        margin_inr=margin,
        margin_pct=billing.margin_pct(margin_inr=margin, revenue_inr=revenue),
    )


@dataclass(frozen=True, slots=True)
class _FleetRow:
    """One walked client, before it is stringified."""

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    margin: dict[str, object]


@router.get(
    "/spend",
    response_model=FleetSpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Every live client's month — revenue, our cost, margin — worst margin first",
)
async def fleet_spend(
    directory: AdminSession,
    _: AdminSpendReader,
    month: str | None = None,
) -> FleetSpendOut:
    """The board that answers "which client is costing us money", one row per client.

    ONE directory query, then ONE `tenant_session` per client, exactly as
    `admin/health.py::client_health` does — the directory comes from the `app.admin`
    session (which widens `organizations` and nothing else) and every rupee is read under
    ordinary RLS inside the client's own scope. Nothing here can see two tenants at once
    and no policy is widened to make it faster.

    Nothing truncates, for the reason the health board does not: hiding the client at the
    bottom of a money board defeats the board. The walk is watched instead.
    """
    started = perf_counter()
    rows = (await directory.execute(text(_DIRECTORY), {"ended": list(_ENDED_STATUSES)})).all()
    # ONE month for the whole walk. `margin_for_tenant` resolves `None` to "now" per call,
    # and a walk that straddles midnight IST on the 1st would otherwise put some clients
    # in August and the rest in September on one board.
    period = month or billing.current_billing_month()

    walked: list[_FleetRow] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            margin = await billing.margin_for_tenant(scoped, tenant_id=tenant_id, month=period)
        walked.append(
            _FleetRow(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                plan_tier=str(org[3]),
                margin=margin,
            )
        )

    elapsed = perf_counter() - started
    if elapsed > FLEET_BUDGET_S:
        # Counts and seconds only, never a client name (the same log discipline
        # `client_health_walk_over_budget` keeps), and the remedy on the line.
        log.warning(
            "fleet_spend_walk_over_budget",
            extra={
                "clients": len(walked),
                "elapsed_s": round(elapsed, 2),
                "budget_s": FLEET_BUDGET_S,
                "remedy": "the client list has outgrown the per-tenant margin walk — "
                "materialize the monthly rollup (billing/spend_routes.py)",
            },
        )

    revenue = sum((_dec(r.margin["revenue_inr"]) for r in walked), Decimal("0.00"))
    cost = sum((_dec(r.margin["cost_inr"]) for r in walked), Decimal("0.00"))
    total_margin = revenue - cost
    return FleetSpendOut(
        month=period,
        clients=len(walked),
        revenue_inr=str(revenue),
        cost_inr=str(cost),
        margin_inr=str(total_margin),
        # Suppressed rather than zeroed when nothing has been billed across the fleet,
        # through the SAME function `margin_for_tenant` uses per client rather than a
        # second copy of the rule (`billing.service.margin_pct`).
        margin_pct=_money(billing.margin_pct(margin_inr=total_margin, revenue_inr=revenue)),
        tenants=[
            FleetTenantOut(
                tenant_id=str(r.tenant_id),
                name=r.name,
                slug=r.slug,
                plan_tier=r.plan_tier,
                minutes_used=str(r.margin["minutes_used"]),
                calls=int(str(r.margin["calls"])),
                revenue_inr=str(r.margin["revenue_inr"]),
                cost_inr=str(r.margin["cost_inr"]),
                margin_inr=str(r.margin["margin_inr"]),
                margin_pct=_money(_opt_dec(r.margin["margin_pct"])),
            )
            # Worst first: the client we are losing the most on is the one an operator
            # opened this page for. Ties by name so the order is stable between renders.
            for r in sorted(walked, key=lambda r: (_dec(r.margin["margin_inr"]), r.name))
        ],
    )


def _dec(value: object) -> Decimal:
    """A money field off `margin_for_tenant`, which types its dict `Any`.

    `Decimal(str(...))` and never `Decimal(float)`: hard rule 7 is not only about the
    database, and a float that reaches here would round a fleet total.
    """
    return Decimal(str(value))


def _opt_dec(value: object) -> Decimal | None:
    return None if value is None else _dec(value)


__all__ = ["client_router", "router"]
