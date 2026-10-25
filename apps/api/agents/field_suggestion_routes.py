"""Suggested changes to an agent's lead details, as the Lead details screen reads and answers
them (D-889).

    GET  /v1/agents/{agent_id}/lead-suggestions                       the suggestions (reader)
    POST /v1/agents/{agent_id}/lead-suggestions/check                 "Check again" (owner)
    POST /v1/agents/{agent_id}/lead-suggestions/{suggestion_id}/accept   make the change (owner)
    POST /v1/agents/{agent_id}/lead-suggestions/{suggestion_id}/dismiss  "Not now" (owner)

and the same four under `/v1/admin/tenants/{tenant_id}/agents/{agent_id}/lead-suggestions` for
an operator, whose tenant is named in the path (`extraction_routes`' rule: impersonation is
read-only, so a mutation cannot infer it).

Accepting writes the agent's fields through `extraction_routes.write_schema`, the one path the
editor's Save uses, so it is versioned, rebuilds what a live agent asks, and leaves leads
captured earlier under the names they were captured with.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import field_suggestions as service
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.billing.trials import trial_billing_active
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import (
    assert_view_as_may,
    client_request_ip,
    record_admin_tenant_read,
    requires,
)
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/agents/{agent_id}/lead-suggestions", tags=["agents"])
admin_router = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/agents/{agent_id}/lead-suggestions", tags=["admin"]
)

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
OperatorReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
SuggestionId = Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeadSuggestionOut(_Out):
    id: str
    kind: Literal["add_choices", "remove_choices", "new_field"]
    #: The detail it changes, or for `new_field` the key the new detail will have.
    field_key: str
    field_label: str
    #: Choices to add or remove; for `new_field`, its choices (none for a free-text detail).
    values: list[str]
    #: For `new_field`: whether it records a choice or free text.
    field_type: Literal["text", "enum"] | None = None
    #: One sentence saying why, for the owner.
    reason: str
    source: Literal["script", "business", "facts", "calls"]
    #: Recent calls whose answer this would have caught.
    callers: int


class LeadSuggestionsOut(_Out):
    #: `none` when no pass has run yet. `skipped`: the AI allowance or the platform pause
    #: stopped it. `failed`: it could not be made; "Check again" may be pressed.
    state: Literal["none", "queued", "running", "done", "failed", "skipped"]
    suggestions: list[LeadSuggestionOut]
    checked_at: datetime | None


class LeadSuggestionAnsweredOut(_Out):
    #: What was accepted or dismissed, and what is left.
    answered: LeadSuggestionOut
    remaining: LeadSuggestionsOut


def _one(s: service.Suggestion) -> LeadSuggestionOut:
    field_type: Literal["text", "enum"] | None = None
    if s.field is not None:
        field_type = "enum" if s.field.type == "enum" else "text"
    return LeadSuggestionOut(
        id=s.id,
        kind=s.kind,
        field_key=s.field_key,
        field_label=s.field_label,
        values=s.values,
        field_type=field_type,
        reason=s.reason,
        source=s.source,
        callers=s.callers,
    )


async def _state(session: AsyncSession, agent_id: UUID) -> LeadSuggestionsOut:
    read = await service.read_state(session, agent_id=agent_id)
    return LeadSuggestionsOut(
        state=read.state,
        suggestions=[_one(s) for s in read.suggestions],
        checked_at=read.checked_at,
    )


def _audit_summary(s: service.Suggestion) -> dict[str, object]:
    """Kind, field key and how many choices: the choice words are the business's wording, and
    a choice an owner typed could carry anything, so they stay out of the audit row."""
    return {"suggestion": s.id, "kind": s.kind, "field_key": s.field_key, "values": len(s.values)}


async def _check(
    session: AsyncSession, principal: Principal, *, tenant_id: UUID, agent_id: UUID
) -> None:
    # A stranger's agent is a 404 before anything about this account is read.
    await service.read_state(session, agent_id=agent_id)
    if not await trial_billing_active(session, tenant_id=tenant_id):
        # A pass spends this account's AI allowance (D-827), so it is refused up front rather
        # than queued only to be skipped by the worker.
        assert_view_as_may(principal, "billing.ai_assist")
        await require_ai_assist(session, tenant_id=tenant_id)
    await service.queue_pass(session, tenant_id=tenant_id, agent_id=agent_id, force=True)


_DESCRIPTION: Final = (
    "Suggestions come from the business's details, the agent's script, its quick facts and "
    "what recent callers asked for that no choice fitted. Nothing changes until one is "
    "accepted; a dismissed one is not offered again."
)


@router.get(
    "",
    response_model=LeadSuggestionsOut,
    openapi_extra=permission_meta("org:read"),
    summary="Suggested changes to this agent's lead details",
    description=_DESCRIPTION,
)
async def get_lead_suggestions(
    agent_id: UUID, session: Session, principal: Reader
) -> LeadSuggestionsOut:
    assert principal.tenant_id is not None
    return await _state(session, agent_id)


@router.post(
    "/check",
    response_model=LeadSuggestionsOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Look again for changes to this agent's lead details",
    description=(
        "Queues a fresh look. On a paying account it uses the monthly AI allowance; on a trial "
        "it is free."
    ),
)
async def check_lead_suggestions(
    agent_id: UUID, session: Session, principal: Owner, request: Request
) -> LeadSuggestionsOut:
    assert principal.tenant_id is not None
    await _check(session, principal, tenant_id=principal.tenant_id, agent_id=agent_id)
    await write_audit(
        session,
        action="agent.lead_suggestions_checked",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
    )
    return await _state(session, agent_id)


@router.post(
    "/{suggestion_id}/accept",
    response_model=LeadSuggestionAnsweredOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Make one suggested change to this agent's lead details",
    description=(
        "Saved as a new version of the agent's lead details, exactly as the editor saves; "
        "leads captured earlier keep their details. 409 when the details changed since the "
        "suggestion was made."
    ),
)
async def accept_lead_suggestion(
    agent_id: UUID,
    suggestion_id: SuggestionId,
    session: Session,
    principal: Owner,
    request: Request,
) -> LeadSuggestionAnsweredOut:
    assert principal.tenant_id is not None
    accepted = await service.accept(session, agent_id=agent_id, suggestion_id=suggestion_id)
    await write_audit(
        session,
        action="agent.lead_suggestion_accepted",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary=_audit_summary(accepted),
    )
    return LeadSuggestionAnsweredOut(
        answered=_one(accepted), remaining=await _state(session, agent_id)
    )


@router.post(
    "/{suggestion_id}/dismiss",
    response_model=LeadSuggestionAnsweredOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Turn down one suggested change; it is not offered again",
)
async def dismiss_lead_suggestion(
    agent_id: UUID,
    suggestion_id: SuggestionId,
    session: Session,
    principal: Owner,
    request: Request,
) -> LeadSuggestionAnsweredOut:
    assert principal.tenant_id is not None
    dismissed = await service.dismiss(session, agent_id=agent_id, suggestion_id=suggestion_id)
    await write_audit(
        session,
        action="agent.lead_suggestion_dismissed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary=_audit_summary(dismissed),
    )
    return LeadSuggestionAnsweredOut(
        answered=_one(dismissed), remaining=await _state(session, agent_id)
    )


@admin_router.get(
    "",
    response_model=LeadSuggestionsOut,
    openapi_extra=permission_meta("org:read"),
    summary="Suggested changes to one client agent's lead details",
    description=_DESCRIPTION,
)
async def admin_get_lead_suggestions(
    tenant_id: UUID, agent_id: UUID, request: Request, principal: OperatorReader
) -> LeadSuggestionsOut:
    async with tenant_session(tenant_id) as scoped:
        out = await _state(scoped, agent_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return out


@admin_router.post(
    "/check",
    response_model=LeadSuggestionsOut,
    status_code=202,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Look again for changes to one client agent's lead details",
)
async def admin_check_lead_suggestions(
    tenant_id: UUID, agent_id: UUID, principal: Operator, request: Request
) -> LeadSuggestionsOut:
    async with tenant_session(tenant_id) as scoped:
        await service.read_state(scoped, agent_id=agent_id)
        await service.queue_pass(scoped, tenant_id=tenant_id, agent_id=agent_id, force=True)
        await write_audit(
            scoped,
            action="admin.agent_lead_suggestions_checked",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
        )
        return await _state(scoped, agent_id)


@admin_router.post(
    "/{suggestion_id}/accept",
    response_model=LeadSuggestionAnsweredOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Make one suggested change to a client agent's lead details",
)
async def admin_accept_lead_suggestion(
    tenant_id: UUID,
    agent_id: UUID,
    suggestion_id: SuggestionId,
    principal: Operator,
    request: Request,
) -> LeadSuggestionAnsweredOut:
    async with tenant_session(tenant_id) as scoped:
        accepted = await service.accept(scoped, agent_id=agent_id, suggestion_id=suggestion_id)
        await write_audit(
            scoped,
            action="admin.agent_lead_suggestion_accepted",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary=_audit_summary(accepted),
        )
        return LeadSuggestionAnsweredOut(
            answered=_one(accepted), remaining=await _state(scoped, agent_id)
        )


@admin_router.post(
    "/{suggestion_id}/dismiss",
    response_model=LeadSuggestionAnsweredOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Turn down one suggested change to a client agent's lead details",
)
async def admin_dismiss_lead_suggestion(
    tenant_id: UUID,
    agent_id: UUID,
    suggestion_id: SuggestionId,
    principal: Operator,
    request: Request,
) -> LeadSuggestionAnsweredOut:
    async with tenant_session(tenant_id) as scoped:
        dismissed = await service.dismiss(scoped, agent_id=agent_id, suggestion_id=suggestion_id)
        await write_audit(
            scoped,
            action="admin.agent_lead_suggestion_dismissed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary=_audit_summary(dismissed),
        )
        return LeadSuggestionAnsweredOut(
            answered=_one(dismissed), remaining=await _state(scoped, agent_id)
        )
