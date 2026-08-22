"""The ACCOUNT-level half of model selection: which model an org's agents run by default.

WHY THIS ROUTER HAS NO PREFIX
-----------------------------
It carries paths in two spaces — the client realm's `/v1/organization/llm-defaults` and
the admin realm's `/v1/admin/organizations/{org_id}/llm-defaults` — so a shared prefix
could only describe one of them. Same resolution, and the same reason, as `agents/
routes.py` and `agents/voice_routes.py`, which both say so.

WHY THE TWO REALMS ARE ONE MODULE AND NOT TWO
---------------------------------------------
They are the SAME resource with two doors, and the thing that must never differ between
them is the allow-list, the price and the resolution — which is exactly what would drift
if the operator's screen and the client's screen were served by two files. Both doors
call one reader (`_read_defaults`) and one writer (`_write_default`); what differs is who
is admitted and whose account is named, which is a `Depends` and a path parameter, not a
second implementation. `compliance/first_campaign_routes.py` and
`billing/spend_routes.py` already pair a client router with an admin one this way.

WHY IT LIVES UNDER `agents/`
----------------------------
The value is a property of the AGENTS an account runs, the resolver it feeds is
`agents/llm_models.py`, and the agent detail route reports the same three facts. Putting
it in `tenancy/` would have separated the column's writer from its only reader by a
module boundary, and `tenancy/routes.py` is session and identity — `/me`, members,
invitations — not account configuration.

WHAT IS DELIBERATELY NOT HERE: a per-agent route. An agent's own choice is one more field
on `PATCH /v1/agents/{agent_id}`, because it is edited on the same screen as its name and
its language and a separate endpoint would make a two-field form a two-request form with
a half-applied state between them.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import (
    QUOTED_CALL_MINUTES,
    available_models,
    resolve_llm_model,
    validate_llm_model,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session

router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]

# The three principals this module admits, as `Annotated` aliases rather than `Depends()`
# in an argument default — the idiom every `*_routes.py` module here uses, because ruff's
# B008 exemption is scoped to files literally named `routes.py` and an alias needs no
# exemption at all. Each one is the permission the route also DECLARES in
# `openapi_extra`, so the lock and the label cannot come apart.
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class LlmModelOptionOut(BaseModel):
    """One model an account may choose, with what a minute of it costs.

    Every field is required on the wire: a Pydantic default here would generate an
    OPTIONAL TypeScript property and the screen would have to branch on a case the server
    never emits.
    """

    model_config = ConfigDict(extra="forbid")

    #: The identifier stored in `organizations.default_llm_model` / `agents.llm_model`,
    #: and the one to send back on a PUT.
    model: str
    #: OUR word for where the leg runs, not the vendor's — read from the declared
    #: residency posture so a posture move cannot leave a stale provider name on a screen.
    provider: str
    #: INR per minute of a `QUOTED_CALL_MINUTES`-minute call, as a STRING (hard rule 7):
    #: the value is a `Decimal` and a JSON float cannot hold a rupee amount exactly. It is
    #: struck at a reference call length because the in-call language cost is NOT constant
    #: per minute — the conversation is resent on every turn, so cost grows quadratically
    #: with duration (TRD §6.1). Derived from the rate card, never a figure typed here.
    inr_per_minute_five_min: str
    #: True for the model this deployment runs when nobody chooses — the row a picker
    #: marks as the default rather than inventing its own label for.
    is_platform_default: bool
    #: CAN THIS PLATFORM ACTUALLY RUN IT. False rows are shown and NOT selectable: a model
    #: with no Azure deployment behind it would be quoted at its own price and answered by
    #: a different model, so `PUT` refuses it with `llm_model_not_deployed`. A screen
    #: should render these disabled with `unavailable_reason` beside them rather than
    #: hiding them, so an operator can see what is left to configure.
    is_available: bool
    #: Why not — `null` exactly when `is_available` is true.
    unavailable_reason: str | None


class LlmDefaultsOut(BaseModel):
    """What this account has chosen, what that resolves to, and what else it could pick."""

    model_config = ConfigDict(extra="forbid")

    #: The account's own choice. `null` means it has never chosen and follows the
    #: platform — NOT "no model".
    default_llm_model: str | None
    #: What agents that name no model of their own will actually run. Never null.
    effective_default: str
    available: list[LlmModelOptionOut]


class LlmDefaultIn(BaseModel):
    """The account's choice, or `null` to go back to following the platform.

    REQUIRED RATHER THAN OPTIONAL, and that is what makes this a PUT rather than a PATCH:
    the body states the whole of the resource, so `null` is unambiguously "clear it" and
    there is no third "field omitted" case to interpret. `PATCH /v1/agents/{id}` has to
    carry that third case because it edits four properties at once; this one carries a
    single value and does not.
    """

    model_config = ConfigDict(extra="forbid")

    default_llm_model: str | None


async def _read_defaults(session: AsyncSession) -> LlmDefaultsOut:
    """The one reader behind both realms' GET.

    RLS does the scoping: `organizations`' policy matches on `id`, so this reads exactly
    the account the session is scoped to and a wrong id is zero rows, not a neighbour's
    row (hard rule 1). No `WHERE` on the tenant is needed or wanted — one would be a
    second, weaker expression of the isolation the policy already enforces.
    """
    row = (await session.execute(text("SELECT default_llm_model FROM organizations"))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    chosen: str | None = row[0]
    resolved = resolve_llm_model(agent_model=None, organization_model=chosen)
    return LlmDefaultsOut(
        default_llm_model=chosen,
        effective_default=resolved.model,
        available=[
            LlmModelOptionOut(
                model=option.model,
                provider=option.provider,
                # Stringified HERE, at the boundary, and nowhere earlier: the value is a
                # `Decimal` everywhere inside the process.
                inr_per_minute_five_min=str(option.inr_per_minute),
                is_platform_default=option.is_platform_default,
                is_available=option.is_available,
                unavailable_reason=option.unavailable_reason,
            )
            for option in available_models()
        ],
    )


async def _write_default(session: AsyncSession, *, model: str | None) -> None:
    """The one writer behind both realms' PUT.

    The caller has already validated `model` against the allow-list. This is a plain
    UPDATE rather than a CAS: the column has one writer per account, the value does not
    depend on what it replaces, and a lost update here means the second of two people who
    chose in the same second wins — which is the correct outcome and the one they would
    both expect. (Money and vendor handles get CAS; a preference does not.)

    Zero rows is a 404 and not a silent success: under RLS an account that is not this
    session's is indistinguishable from one that does not exist, and answering 200 for a
    write that changed nothing is how a console reports a setting it never stored.
    """
    result = await session.execute(
        text(
            "UPDATE organizations SET default_llm_model = CAST(:model AS text), "
            "updated_at = now() WHERE deleted_at IS NULL"
        ),
        {"model": model},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Organization")


_DESCRIPTION = (
    "The language model this account's agents run when the agent itself names none.\n\n"
    "Resolution is three levels: the agent's own choice, then this account default, then "
    "the platform's model. `effective_default` is what an agent that has chosen nothing "
    "will run, and each agent reports its own resolved model and which level supplied it."
    f"\n\nPrices are INR per minute of a {QUOTED_CALL_MINUTES}-minute call, as strings: "
    "the language leg is resent the whole conversation on every turn, so its cost per "
    "minute rises with call length and a single figure has to say which length it is for."
    "\n\nA row with `is_available: false` cannot be chosen — this platform has no "
    "deployment for it, so choosing it would price one model and run another. "
    "`unavailable_reason` says what is missing."
)


@router.get(
    "/v1/organization/llm-defaults",
    response_model=LlmDefaultsOut,
    # `org:read`, not `org:manage`: reading which model you run is not the authority to
    # change it, and every role in both realms holds `org:read` — so an impersonating
    # operator can see the same screen the client sees when explaining a bill (D-22).
    openapi_extra=permission_meta("org:read"),
    summary="Which language model this account's agents run, and what else it could run",
    description=_DESCRIPTION,
)
async def get_organization_llm_defaults(session: Session, _: Reader) -> LlmDefaultsOut:
    return await _read_defaults(session)


@router.put(
    "/v1/organization/llm-defaults",
    response_model=LlmDefaultsOut,
    # `org:manage` — the OWNER's permission, for the reason the agent lifecycle routes
    # give: this decides what every agent on the account costs and how well it answers,
    # which is an owner's decision and not a support ticket.
    openapi_extra=permission_meta("org:manage"),
    summary="Choose the language model this account's agents run by default",
    description=(
        f"{_DESCRIPTION}\n\nSend `null` to go back to following the platform's model. A "
        "model this platform does not run at all is refused with "
        "`llm_model_not_available`; one it supports but has no deployment for is refused "
        "with `llm_model_not_deployed` — the same rows `available` marks "
        "`is_available: false`.\n\nAgents that have chosen a model of their own are "
        "unaffected — this sets what the others follow."
    ),
)
async def set_organization_llm_default(
    payload: LlmDefaultIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> LlmDefaultsOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    model = validate_llm_model(payload.default_llm_model, field="default_llm_model")
    await _write_default(session, model=model)
    await write_audit(
        session,
        action="organization.llm_default_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        # THE VALUE, not just the field name, and the distinction from `agent.updated`'s
        # summary is deliberate: a model identifier is a configuration constant, not a
        # client's business copy or anyone's personal data (hard rule 6), and WHICH model
        # was selected is the entire fact an auditor reconstructing a bill or a quality
        # complaint needs. `null` is recorded as itself — "went back to the platform
        # default" is a decision somebody took.
        summary={"default_llm_model": model},
    )
    return await _read_defaults(session)


admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])


@admin_router.get(
    "/organizations/{org_id}/llm-defaults",
    response_model=LlmDefaultsOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Which language model one client's agents run",
    description=_DESCRIPTION,
)
async def admin_get_llm_defaults(org_id: UUID, _: Operator) -> LlmDefaultsOut:
    """THE ACCOUNT IS NAMED IN THE PATH AND ENTERED EXPLICITLY, never inferred from a
    session — the same resolution `agents/routes.py::publish` records. An admin principal
    carries no tenant of its own, and the one way it can carry one (impersonation) is
    READ-ONLY by D-22, so a route that inferred the tenant would be un-callable for the
    PUT below and inconsistent with it here."""
    async with tenant_session(org_id) as scoped:
        return await _read_defaults(scoped)


@admin_router.put(
    "/organizations/{org_id}/llm-defaults",
    response_model=LlmDefaultsOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set the language model one client's agents run by default",
    description=(
        f"{_DESCRIPTION}\n\nSend `null` to put the account back on the platform's model. "
        "Recorded in the audit ledger against the client's account, because it changes "
        "what their calls cost and how their agents answer."
    ),
)
async def admin_set_llm_default(
    org_id: UUID,
    payload: LlmDefaultIn,
    request: Request,
    principal: Operator,
) -> LlmDefaultsOut:
    model = validate_llm_model(payload.default_llm_model, field="default_llm_model")
    async with tenant_session(org_id) as scoped:
        await _write_default(scoped, model=model)
        # In the SAME transaction as the write (`write_audit` appends in the caller's),
        # so "an operator changed which model this client's calls run on" cannot be
        # missing for a change that happened.
        await write_audit(
            scoped,
            action="admin.organization_llm_default_set",
            actor=principal,
            tenant_id=org_id,
            object_type="organization",
            object_id=str(org_id),
            ip=client_request_ip(request),
            summary={"default_llm_model": model},
        )
        return await _read_defaults(scoped)
