"""The ACCOUNT-level half of model selection: which model an org's agents run by default.

WHY THIS ROUTER HAS NO PREFIX
-----------------------------
It carries paths in two spaces — the client realm's `/v1/organization/llm-defaults` and
the admin realm's `/v1/admin/organizations/{org_id}/llm-defaults` — so a shared prefix
could only describe one of them. Same resolution, and the same reason, as `agents/
routes.py` and `agents/voice_routes.py`, which both say so.

THE TWO REALMS SPEAK DIFFERENT VOCABULARIES OVER ONE WRITER (D-680)
-------------------------------------------------------------------
A client chooses a TIER (`agents/llm_tiers.py`) and never reads a model id or a provider
(D-679); an operator chooses and reads real models. So the two doors have two response
shapes — `ClientLlmDefaultsOut` and `LlmDefaultsOut` — and still share what must not differ:
the offer predicate (`offerable_models`), the plan surcharge read, the resolver and the one
writer (`_write_default`). A tier is turned into a model before the writer sees it, so the
column, the publish path and the bill are exactly what they were before tiers existed.

WHY IT LIVES UNDER `agents/`
----------------------------
The value is a property of the AGENTS an account runs, the resolver it feeds is
`agents/llm_models.py`, and the agent detail route reports the same facts. Putting it in
`tenancy/` would have separated the column's writer from its only reader by a module
boundary, and `tenancy/routes.py` is session and identity, not account configuration.

WHAT IS DELIBERATELY NOT HERE: a per-agent route. An agent's own choice is one more field
on `PATCH /v1/agents/{agent_id}`, because it is edited on the same screen as its name and
its language and a separate endpoint would make a two-field form a two-request form with
a half-applied state between them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from calevate_shared.engine import LlmTier
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    QUOTED_CALL_MINUTES,
    LlmModelSource,
    available_models,
    resolve_llm_model,
    unofferable_reason,
    validate_llm_model,
)
from apps.api.agents.llm_tiers import (
    LLM_TIER_DESCRIPTIONS,
    LLM_TIER_LABELS,
    available_tiers,
    resolve_tier_choice,
    tier_label,
    tier_of_model,
)
from apps.api.agents.roster import AGENT_ROSTER_LIMIT
from apps.api.agents.service import publish_agent
from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql
from apps.api.billing.rates import llm_surcharge_applies
from apps.api.billing.service import rate_to_display
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]

# `Annotated` aliases rather than `Depends()` in an argument default — the idiom every
# `*_routes.py` module here uses, because ruff's B008 exemption is scoped to files literally
# named `routes.py`. Each one is the permission the route also DECLARES in `openapi_extra`.
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


# --- The admin realm's shapes: real models ---------------------------------------------


class LlmModelOptionOut(BaseModel):
    """One model an account may run, with what a minute of it costs. ADMIN REALM ONLY.

    Every field is required on the wire: a Pydantic default here would generate an
    OPTIONAL TypeScript property and the screen would have to branch on a case the server
    never emits.
    """

    model_config = ConfigDict(extra="forbid")

    #: The identifier stored in `organizations.default_llm_model` / `agents.llm_model`,
    #: and the one to send back on a PUT.
    model: str
    #: OUR word for where the leg runs (`azure_openai`, `openai`, `google`).
    provider: str
    #: The tier a client sees this model as (`llm_tiers.tier_of_model`), so an operator can
    #: tell which client-facing word a choice made here will read as.
    tier: LlmTier | None
    #: INR per minute of a `QUOTED_CALL_MINUTES`-minute call, as a STRING (hard rule 7). Struck
    #: at a reference length because the language cost grows with call length (TRD §6.1).
    #:
    #: ⚠ **THIS IS OUR SUPPLIER COST AND IT IS NOT WHAT THE CLIENT PAYS** — that is
    #: `client_surcharge_inr_per_minute`. The client realm never receives this figure.
    platform_cost_inr_per_minute: str
    #: What choosing this model adds to this account's bill per minute (D-455), as a STRING.
    #: `"0"` on a model that is not an upgrade, and on every plan that quotes no surcharge.
    #: It is the surcharge for choosing it EXPLICITLY: an account that follows the platform
    #: default is never surcharged (`rates.CLIENT_CHOSEN_LLM_SOURCES`).
    client_surcharge_inr_per_minute: str
    #: True for the model this deployment runs when nobody chooses.
    is_platform_default: bool
    #: Can this platform actually run it. False rows are shown and NOT selectable, with
    #: `unavailable_reason` beside them, so an operator can see what is left to configure.
    is_available: bool
    #: Why not — `null` exactly when `is_available` is true.
    unavailable_reason: str | None


class AgentLlmModelOut(BaseModel):
    """Which model one of the account's agents runs, for the operator. The client realm
    reads the same facts as tiers on `AgentOut`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    #: The agent's own choice, `null` when it inherits.
    llm_model: str | None
    llm_model_effective: str
    llm_model_source: LlmModelSource


class LlmDefaultsOut(BaseModel):
    """What this account has chosen, what that resolves to, and what else it could run."""

    model_config = ConfigDict(extra="forbid")

    #: The account's own choice. `null` means it follows the platform — NOT "no model".
    default_llm_model: str | None
    #: What agents that name no model of their own will actually run. Never null.
    effective_default: str
    available: list[LlmModelOptionOut]
    #: Every non-archived agent on the account with the model it runs, at most
    #: `AGENT_ROSTER_LIMIT` — the roster's own bound.
    agents: list[AgentLlmModelOut]


class LlmDefaultIn(BaseModel):
    """The account's choice, or `null` to go back to following the platform.

    REQUIRED RATHER THAN OPTIONAL, and that is what makes this a PUT rather than a PATCH:
    the body states the whole of the resource, so `null` is unambiguously "clear it".
    """

    model_config = ConfigDict(extra="forbid")

    default_llm_model: str | None


# --- The client realm's shapes: tiers, never models ---------------------------------------


class LlmTierOptionOut(BaseModel):
    """One tier a client may choose. No model id and no provider: which model answers a tier
    is ours, and changing it must not be a client-visible rename (D-679, D-680)."""

    model_config = ConfigDict(extra="forbid")

    tier: LlmTier
    label: str
    description: str
    #: What choosing this tier adds to the account's bill per minute, as a STRING — the
    #: plan's `llm_model_surcharge` when the tier's model is an upgrade, else `"0"`.
    client_surcharge_inr_per_minute: str
    #: The tier the Calevate default runs on.
    is_platform_default: bool
    is_available: bool
    #: The client sentence (`llm_models.CLIENT_UNAVAILABLE_REASON`), never the operator
    #: ground. `null` exactly when `is_available`.
    unavailable_reason: str | None


class ClientLlmDefaultsOut(BaseModel):
    """The client's model settings, in tiers."""

    model_config = ConfigDict(extra="forbid")

    #: The tier the account chose, or `null` when it follows the Calevate default.
    default_llm_tier: LlmTier | None
    #: The tier its agents run when they choose nothing themselves. Never null.
    effective_tier: LlmTier
    effective_tier_label: str
    #: Is the model behind `effective_tier` switched on? False is a real state: the platform
    #: default is a live setting and its credential and price are live properties.
    effective_is_available: bool
    #: What the tier in force adds to every minute, as the meter will apply it — `"0"` when
    #: the account follows the Calevate default, whatever that resolves to.
    in_force_surcharge_inr_per_minute: str
    #: The plan's per-minute surcharge for an upgraded tier, `"0"` when the plan quotes none.
    #: An agent that `llm_surcharged` pays this; a screen multiplies nothing.
    upgrade_surcharge_inr_per_minute: str
    available: list[LlmTierOptionOut]


class ClientLlmDefaultIn(BaseModel):
    """The tier for every agent that chooses none, or `null` to follow the Calevate default.
    Required for `LlmDefaultIn`'s reason. A `Literal` here is right where a model allow-list
    was not: the tier vocabulary is ours and closed, and which model each tier runs is not
    on the wire at all."""

    model_config = ConfigDict(extra="forbid")

    default_llm_tier: LlmTier | None


#: THIS ACCOUNT'S MODEL SURCHARGE, at the instant it is being asked about (D-455). `NOW_SQL`
#: because this screen answers "what will it cost me if I choose this"; through the shared
#: resolver, so the rate quoted is the rate on the row a bill would pick.
_PLAN_SURCHARGE = plan_in_effect_sql("llm_model_surcharge", at=NOW_SQL)

#: The account's own row. RLS scopes it (`organizations`' policy matches on `id`), so no
#: `WHERE` on the tenant is wanted; `deleted_at IS NULL` is the same predicate the writer
#: carries, so a closed account is a 404 on the GET as well as the PUT.
_ORG_DEFAULT = "SELECT id, default_llm_model FROM organizations WHERE deleted_at IS NULL"

#: The operator's per-agent view. Bounded by the roster's own limit, archived agents left
#: out as the roster leaves them out.
_AGENT_MODELS = (
    "SELECT id, llm_model FROM agents WHERE deleted_at IS NULL AND status <> 'archived' "
    "ORDER BY created_at LIMIT :limit"
)


async def _org_default(session: AsyncSession) -> tuple[UUID, str | None]:
    row = (await session.execute(text(_ORG_DEFAULT))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return UUID(str(row[0])), row[1]


async def _upgrade_surcharge(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """The plan's per-minute surcharge for an upgrade, as a display rate. An account with no
    plan row and one whose plan quotes none are both ₹0 — "an upgrade adds nothing"."""
    plan = (await session.execute(text(_PLAN_SURCHARGE), {"tid": tenant_id})).first()
    if plan is None or plan[0] is None:
        return Decimal("0")
    return rate_to_display(Decimal(str(plan[0])))


async def _read_defaults(session: AsyncSession) -> LlmDefaultsOut:
    """The admin realm's reader: real models, with the operator's ground on a blocked row."""
    tenant_id, chosen = await _org_default(session)
    resolved = resolve_llm_model(agent_model=None, organization_model=chosen)
    upgrade = await _upgrade_surcharge(session, tenant_id)
    agent_rows = (await session.execute(text(_AGENT_MODELS), {"limit": AGENT_ROSTER_LIMIT})).all()
    agents = []
    for agent_id, own in agent_rows:
        in_force = resolve_llm_model(agent_model=own, organization_model=chosen)
        agents.append(
            AgentLlmModelOut(
                agent_id=agent_id,
                llm_model=own,
                llm_model_effective=in_force.model,
                llm_model_source=in_force.source,
            )
        )
    return LlmDefaultsOut(
        default_llm_model=chosen,
        effective_default=resolved.model,
        available=[
            LlmModelOptionOut(
                model=option.model,
                provider=option.provider,
                tier=tier_of_model(option.model),
                # Stringified HERE, at the boundary: a `Decimal` everywhere inside.
                platform_cost_inr_per_minute=str(option.inr_per_minute),
                client_surcharge_inr_per_minute=str(
                    upgrade if option.is_surcharged else Decimal("0")
                ),
                is_platform_default=option.is_platform_default,
                is_available=option.is_available,
                unavailable_reason=option.unavailable_reason,
            )
            for option in available_models(audience="operator")
        ],
        agents=agents,
    )


async def _read_client_defaults(session: AsyncSession) -> ClientLlmDefaultsOut:
    """The client realm's reader: tiers, and the client's sentence on a blocked row."""
    tenant_id, chosen = await _org_default(session)
    resolved = resolve_llm_model(agent_model=None, organization_model=chosen)
    upgrade = await _upgrade_surcharge(session, tenant_id)
    effective = tier_of_model(resolved.model)
    if effective is None:
        # Both columns are CHECKed to the catalogue and `platform_llm_model` is typed to it,
        # and every catalogue model has a cost tier — so this is a broken invariant, not a
        # state to render.
        raise RuntimeError("the model in force has no tier")
    in_force = (
        upgrade
        if llm_surcharge_applies(model=resolved.model, source=resolved.source)
        else Decimal("0")
    )
    return ClientLlmDefaultsOut(
        default_llm_tier=tier_of_model(chosen),
        effective_tier=effective,
        effective_tier_label=tier_label(effective),
        effective_is_available=unofferable_reason(resolved.model) is None,
        in_force_surcharge_inr_per_minute=str(in_force),
        upgrade_surcharge_inr_per_minute=str(upgrade),
        available=[
            LlmTierOptionOut(
                tier=option.tier,
                label=LLM_TIER_LABELS[option.tier],
                description=LLM_TIER_DESCRIPTIONS[option.tier],
                client_surcharge_inr_per_minute=str(
                    upgrade if option.is_surcharged else Decimal("0")
                ),
                is_platform_default=option.is_platform_default,
                is_available=option.is_available,
                unavailable_reason=option.unavailable_reason,
            )
            for option in available_tiers(audience="client")
        ],
    )


#: The account's own row, LOCKED, so the "has this actually changed?" read and the write
#: that depends on it are one atomic step.
_ORG_MODEL_FOR_UPDATE = (
    "SELECT default_llm_model FROM organizations WHERE deleted_at IS NULL FOR UPDATE"
)

#: The agents this account's default actually MOVES: live, known to the engine, and with
#: no choice of their own. `ORDER BY id` because `publish_agent` takes `FOR UPDATE` on each
#: row, and a total order over the key every writer uses makes a deadlock impossible.
_INHERITING_LIVE_AGENTS = (
    "SELECT id FROM agents WHERE deleted_at IS NULL AND status = 'live' "
    "AND engine_agent_ref IS NOT NULL AND llm_model IS NULL ORDER BY id"
)


async def _locked_org_default(session: AsyncSession) -> str | None:
    current = (await session.execute(text(_ORG_MODEL_FOR_UPDATE))).first()
    if current is None:
        raise ProblemError.not_found("Organization")
    return None if current[0] is None else str(current[0])


async def _write_default(session: AsyncSession, *, tenant_id: UUID, model: str | None) -> bool:
    """The one writer behind both realms' PUT. Answers whether anything moved.

    The caller has already validated `model` (a model, or a tier resolved to one).

    **THE ROW IS LOCKED FIRST**: deciding "did this change?" reads the current value, and
    without a lock two writers would each read the old value, each conclude they changed it
    and each republish (BACKEND-PATTERNS §5). Re-taking the lock in a transaction that
    already holds it is free.

    **AND IT REPUBLISHES THE AGENTS THIS MOVES**, in the same transaction and after the
    column write, as `set_call_cap` does: `_to_config` resolves the account default at
    PUBLISH time, so an unpublished change would leave every inheriting live agent on the
    old model while every screen reported the new one. A vendor failure rolls the row back.

    Re-asserting the value already on file touches nothing — a double-clicked Save must not
    become a fleet-wide republish.
    """
    if await _locked_org_default(session) == model:
        return False

    await session.execute(
        text(
            "UPDATE organizations SET default_llm_model = CAST(:model AS text), "
            "updated_at = now() WHERE deleted_at IS NULL"
        ),
        {"model": model},
    )
    for agent_id in (await session.execute(text(_INHERITING_LIVE_AGENTS))).scalars().all():
        await publish_agent(session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)))
    return True


_CLIENT_DESCRIPTION = (
    "The AI model tier this account's agents run when the agent itself names none: "
    "`standard`, `plus` or `pro`. Which model answers each tier is Calevate's, and is not "
    "part of this response.\n\n"
    "Resolution is three levels: the agent's own choice, then this account default, then "
    "Calevate's default. `effective_tier` is what an agent that has chosen nothing runs.\n\n"
    "`client_surcharge_inr_per_minute` on each tier is what choosing it ADDS to this "
    "account's bill for every minute it runs — the plan's own model surcharge, `0` when the "
    "plan quotes none and `0` on a tier that is not an upgrade. "
    "`in_force_surcharge_inr_per_minute` is what the tier in force adds now; following "
    "Calevate's default is never surcharged.\n\n"
    "A tier with `is_available: false` cannot be chosen yet; `unavailable_reason` says so."
)

_ADMIN_DESCRIPTION = (
    "The language model one client's agents run when the agent itself names none, with "
    "the real model identifiers the client realm never sees (it reads tiers).\n\n"
    "Each row carries TWO figures of different kinds. `client_surcharge_inr_per_minute` is "
    "what choosing that model ADDS to the client's bill per minute. "
    "`platform_cost_inr_per_minute` is what the language leg costs CALEVATE at list price, "
    f"per minute of a {QUOTED_CALL_MINUTES}-minute call. `tier` is the word the client "
    "reads for the model. `agents` lists each agent with the model it runs and the level "
    "that chose it.\n\n"
    "A row with `is_available: false` cannot be chosen; `unavailable_reason` says what is "
    "missing."
)

_APPLIES_NOW = (
    "\n\nEvery LIVE agent that has not chosen a model of its own is re-published to the "
    "voice platform in the same transaction, so the change reaches the phone line and not "
    "only this record. If that push fails, nothing is saved. Agents that have chosen a "
    "model of their own are untouched — this sets what the others follow."
)


@router.get(
    "/v1/organization/llm-defaults",
    response_model=ClientLlmDefaultsOut,
    # `org:read`: reading which tier you run is not the authority to change it, and an
    # impersonating operator sees exactly the client's screen (D-22).
    openapi_extra=permission_meta("org:read"),
    summary="Which AI model tier this account's agents run, and which tiers it could choose",
    description=_CLIENT_DESCRIPTION,
)
async def get_organization_llm_defaults(session: Session, _: Reader) -> ClientLlmDefaultsOut:
    return await _read_client_defaults(session)


@router.put(
    "/v1/organization/llm-defaults",
    response_model=ClientLlmDefaultsOut,
    # `org:manage` — the OWNER's permission: this decides what every agent on the account
    # costs and how well it answers.
    openapi_extra=permission_meta("org:manage"),
    summary="Choose the AI model tier this account's agents run by default",
    description=(
        f"{_CLIENT_DESCRIPTION}\n\nSend `null` to go back to following Calevate's default. "
        "A tier that is not switched on yet is refused with `llm_tier_not_available`. "
        "Choosing the tier the account is already on changes nothing."
        f"{_APPLIES_NOW}"
    ),
)
async def set_organization_llm_default(
    payload: ClientLlmDefaultIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> ClientLlmDefaultsOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    # Locked before resolving: "the tier this account is already on" is read from the value
    # the writer will compare against, so the two cannot see different rows.
    current = await _locked_org_default(session)
    model = resolve_tier_choice(
        payload.default_llm_tier, current_model=current, field="default_llm_tier"
    )
    changed = await _write_default(session, tenant_id=principal.tenant_id, model=model)
    await write_audit(
        session,
        action="organization.llm_default_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        # The resolved MODEL beside the tier the client named: the tier is what they chose
        # and the model is what a bill dispute turns on. Neither is personal data (hard
        # rule 6); `changed` tells an auditor which of a run of repeats moved a phone line.
        summary={
            "default_llm_tier": payload.default_llm_tier,
            "default_llm_model": model,
            "changed": changed,
        },
    )
    return await _read_client_defaults(session)


admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])


@admin_router.get(
    "/organizations/{org_id}/llm-defaults",
    response_model=LlmDefaultsOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Which language model one client's agents run",
    description=_ADMIN_DESCRIPTION,
)
async def admin_get_llm_defaults(
    org_id: UUID, request: Request, principal: Operator
) -> LlmDefaultsOut:
    """THE ACCOUNT IS NAMED IN THE PATH AND ENTERED EXPLICITLY, never inferred from a
    session: an admin principal carries no tenant of its own, and impersonation is
    READ-ONLY by D-22, so a route that inferred the tenant could not serve the PUT."""
    async with tenant_session(org_id) as scoped:
        defaults = await _read_defaults(scoped)
        # D-482 L-1: a direct per-tenant admin read leaves its own ledger row.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=org_id
        )
    return defaults


@admin_router.put(
    "/organizations/{org_id}/llm-defaults",
    response_model=LlmDefaultsOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set the language model one client's agents run by default",
    description=(
        f"{_ADMIN_DESCRIPTION}\n\nSend `null` to put the account back on the platform's "
        "model. A model this platform does not run is refused with "
        "`llm_model_not_available`; one it supports but cannot serve yet with "
        "`llm_model_not_deployed`. Recorded in the audit ledger against the client's "
        f"account, because it changes what their calls cost and how their agents answer."
        f"{_APPLIES_NOW}"
    ),
)
async def admin_set_llm_default(
    org_id: UUID,
    payload: LlmDefaultIn,
    request: Request,
    principal: Operator,
) -> LlmDefaultsOut:
    model = validate_llm_model(
        payload.default_llm_model, field="default_llm_model", audience="operator"
    )
    async with tenant_session(org_id) as scoped:
        changed = await _write_default(scoped, tenant_id=org_id, model=model)
        # In the SAME transaction as the write, so the entry cannot be missing for a change
        # that happened.
        await write_audit(
            scoped,
            action="admin.organization_llm_default_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=client_request_ip(request),
            summary={"default_llm_model": model, "changed": changed},
        )
        return await _read_defaults(scoped)


__all__ = ["admin_router", "router"]
