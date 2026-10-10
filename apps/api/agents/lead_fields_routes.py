"""The lead details a business captures, as one screen reads and changes them.

    GET   /v1/lead-fields                        the core, the business type, each agent's
                                                 business fields and the AI draft's state
    POST  /v1/lead-fields/draft                  queue the one AI draft (custom business)
    POST  /v1/lead-fields/replace                replace agents' business fields with the
                                                 standard set for the business type (or the
                                                 AI draft, for a custom business)

    GET   /v1/admin/tenants/{tenant_id}/lead-fields           the same, for an operator
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/draft     queue the draft
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/replace   replace, optionally from
                                                              another type's standard set

Editing one agent's business fields stays `PUT /v1/agents/{agent_id}/extraction-schema`
(and its admin twin): one write path for a field list, whatever screen it is edited from.
Every write here is a new schema version per agent; nothing captured is rewritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import CORE_LEAD_FIELDS, NEED_KEY
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.routes import Vertical
from apps.api.agents import lead_fields as service
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/lead-fields", tags=["agents"])
admin_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/lead-fields", tags=["admin"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
AdminReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: Every agent of one business, and then some: bounds the replace body.
MAX_AGENT_IDS = 50


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: `agents.models.LEAD_FIELD_DRAFT_STATUSES`, which the table's CHECK holds.
DraftStatus = Literal["queued", "running", "done", "failed"]


class LeadFieldsDraftOut(_Out):
    """The one AI draft of a custom business's fields."""

    status: DraftStatus
    requested_at: datetime
    completed_at: datetime | None
    #: What was drafted, as drafted. The agents' current fields may since differ.
    fields: list[ExtractionField]
    #: A machine code when `failed` (`no_draft`, `no_provider`, `draft_crashed`).
    error_code: str | None


class LeadFieldsAgentOut(_Out):
    id: UUID
    name: str
    direction: str
    status: str
    #: The agent's current schema version; 0 when it has none yet.
    version: int
    business_fields: list[ExtractionField]


class LeadFieldsOut(_Out):
    business_type: str | None
    business_type_label: str
    #: The details every lead carries, whatever the business. Never editable.
    core_fields: list[ExtractionField]
    #: The core field that says what the caller wants.
    need_key: str
    #: The standard set for this business type; empty for a custom business.
    standard_fields: list[ExtractionField]
    has_standard_set: bool
    draft: LeadFieldsDraftOut | None
    #: May a draft be queued now: a custom business with no draft, or a failed one.
    can_draft: bool
    agents: list[LeadFieldsAgentOut]


class ReplaceIn(BaseModel):
    """Which agents get a fresh set of business fields. Omit `agent_ids` for all of them."""

    model_config = ConfigDict(extra="forbid")

    agent_ids: list[UUID] | None = Field(default=None, max_length=MAX_AGENT_IDS)


class AdminReplaceIn(ReplaceIn):
    #: Take another type's standard set instead of this business's own type's. Lets an
    #: operator move an account to a new type and its fields in two deliberate steps.
    business_type: Vertical | None = None


class ReplaceOut(_Out):
    agents_changed: int
    agents_unchanged: int


class DraftRequestOut(_Out):
    draft: LeadFieldsDraftOut


def _draft_out(draft: service.Draft | None) -> LeadFieldsDraftOut | None:
    if draft is None:
        return None
    return LeadFieldsDraftOut(
        status=cast(DraftStatus, draft.status),
        requested_at=draft.requested_at,
        completed_at=draft.completed_at,
        fields=draft.fields,
        error_code=draft.error_code,
    )


async def _render(session: AsyncSession, *, tenant_id: UUID) -> LeadFieldsOut:
    vertical = await service.vertical_of(session, tenant_id=tenant_id)
    draft = await service.read_draft(session, tenant_id=tenant_id)
    standard = service.has_standard_set(vertical)
    return LeadFieldsOut(
        business_type=vertical,
        business_type_label=service.business_type_label(vertical),
        core_fields=list(CORE_LEAD_FIELDS),
        need_key=NEED_KEY,
        standard_fields=service.standard_fields(vertical) if standard else [],
        has_standard_set=standard,
        draft=_draft_out(draft),
        can_draft=not standard and (draft is None or draft.status == "failed"),
        agents=[
            LeadFieldsAgentOut(
                id=a["id"],
                name=a["name"],
                direction=a["direction"],
                status=a["status"],
                version=a["version"],
                business_fields=a["fields"],
            )
            for a in await service.agents_with_fields(session)
        ],
    )


async def _replacement_fields(
    session: AsyncSession, *, tenant_id: UUID, business_type: str | None
) -> list[ExtractionField]:
    """The standard set for the type, or — for a custom business — its finished draft."""
    vertical = business_type or await service.vertical_of(session, tenant_id=tenant_id)
    if service.has_standard_set(vertical):
        return service.standard_fields(vertical)
    draft = await service.read_draft(session, tenant_id=tenant_id)
    if draft is None or draft.status != "done":
        raise ProblemError.business_rule(
            "lead_fields_nothing_to_replace_with",
            (
                "This business has no standard set of lead details, and none has been "
                "drafted from its details yet."
            ),
            remediation="Draft the details first, or edit each agent's details directly.",
        )
    return draft.fields


def _replace_out(written: list[service.AgentWrite]) -> ReplaceOut:
    changed = sum(1 for w in written if w.changed)
    return ReplaceOut(agents_changed=changed, agents_unchanged=len(written) - changed)


_REPLACE_NOTE = (
    "Each agent named (every agent when none is named) gets the set as a NEW version of its "
    "lead details; values already captured stay on their leads and calls, readable under "
    "their old names."
)


@router.get(
    "",
    response_model=LeadFieldsOut,
    openapi_extra=permission_meta("org:read"),
    summary="The lead details this business captures",
)
async def get_lead_fields(session: Session, principal: Reader) -> LeadFieldsOut:
    assert principal.tenant_id is not None
    return await _render(session, tenant_id=principal.tenant_id)


@router.post(
    "/draft",
    response_model=DraftRequestOut,
    status_code=202,
    openapi_extra=permission_meta("org:manage"),
    summary="Draft this business's lead details once, from its business details",
    description=(
        "For a business set up as 'Something else'. Queued; the screen polls `GET` for the "
        "result. Drafted once: a finished draft is never redrafted (409), and a failed one "
        "may be asked for again."
    ),
)
async def post_draft(session: Session, principal: Owner, request: Request) -> DraftRequestOut:
    assert principal.tenant_id is not None
    draft = await service.request_draft(
        session, tenant_id=principal.tenant_id, requested_by=principal.user_id
    )
    await write_audit(
        session,
        action="lead_fields.draft_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"status": draft.status},
    )
    out = _draft_out(draft)
    assert out is not None
    return DraftRequestOut(draft=out)


@router.post(
    "/replace",
    response_model=ReplaceOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Start agents again from this business type's standard lead details",
    description=_REPLACE_NOTE,
)
async def post_replace(
    payload: ReplaceIn, session: Session, principal: Owner, request: Request
) -> ReplaceOut:
    assert principal.tenant_id is not None
    fields = await _replacement_fields(session, tenant_id=principal.tenant_id, business_type=None)
    written = await service.replace_business_fields(
        session, fields=fields, agent_ids=payload.agent_ids
    )
    await write_audit(
        session,
        action="lead_fields.replaced",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={
            "agents": [str(w.agent_id) for w in written],
            "field_keys": [f.key for f in fields],
        },
    )
    return _replace_out(written)


@admin_router.get(
    "",
    response_model=LeadFieldsOut,
    openapi_extra=permission_meta("org:read"),
    summary="The lead details one client captures",
)
async def admin_get_lead_fields(
    tenant_id: UUID, request: Request, principal: AdminReader
) -> LeadFieldsOut:
    async with tenant_session(tenant_id) as scoped:
        out = await _render(scoped, tenant_id=tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return out


@admin_router.post(
    "/draft",
    response_model=DraftRequestOut,
    status_code=202,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Draft one client's lead details once, from its business details",
)
async def admin_post_draft(
    tenant_id: UUID, request: Request, principal: Operator
) -> DraftRequestOut:
    async with tenant_session(tenant_id) as scoped:
        draft = await service.request_draft(
            scoped, tenant_id=tenant_id, requested_by=principal.user_id
        )
        await write_audit(
            scoped,
            action="admin.lead_fields_draft_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"status": draft.status},
        )
    out = _draft_out(draft)
    assert out is not None
    return DraftRequestOut(draft=out)


@admin_router.post(
    "/replace",
    response_model=ReplaceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Replace one client's agents' lead details with a standard set",
    description=_REPLACE_NOTE,
)
async def admin_post_replace(
    tenant_id: UUID, payload: AdminReplaceIn, request: Request, principal: Operator
) -> ReplaceOut:
    async with tenant_session(tenant_id) as scoped:
        fields = await _replacement_fields(
            scoped, tenant_id=tenant_id, business_type=payload.business_type
        )
        written = await service.replace_business_fields(
            scoped, fields=fields, agent_ids=payload.agent_ids
        )
        await write_audit(
            scoped,
            action="admin.lead_fields_replaced",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "business_type": payload.business_type,
                "agents": [str(w.agent_id) for w in written],
                "field_keys": [f.key for f in fields],
            },
        )
    return _replace_out(written)


__all__ = ["admin_router", "router"]
