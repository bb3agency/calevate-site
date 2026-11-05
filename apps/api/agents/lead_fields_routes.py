"""The lead details a business captures, as one screen reads and changes them.

    GET   /v1/lead-fields                        the core, the business type, each agent's
                                                 business fields and the AI draft's state
    PUT   /v1/lead-fields/core-labels            the client's own names for the core details
    POST  /v1/lead-fields/draft/review           keep some or none of the AI draft (D-821; the
                                                 draft itself is asked of Pip)
    POST  /v1/lead-fields/replace                replace agents' business fields with the
                                                 standard set for the business type (or the
                                                 AI draft, for a custom business)

    GET   /v1/admin/tenants/{tenant_id}/lead-fields           the same, for an operator
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/draft     queue the draft
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/replace   replace, optionally from
                                                              another type's standard set
    PUT   /v1/admin/tenants/{tenant_id}/lead-fields/core-labels   the same names, for an operator

Editing one agent's business fields stays `PUT /v1/agents/{agent_id}/extraction-schema`
(and its admin twin): one write path for a field list, whatever screen it is edited from.
Every write here is a new schema version per agent; nothing captured is rewritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from calevate_shared.lead_fields import (
    CORE_LABEL_MAX_CHARS,
    CORE_LEAD_FIELDS,
    NEED_KEY,
    clean_core_labels,
    core_fields,
)
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.routes import Vertical
from apps.api.admin.service import tenant_exists
from apps.api.agents import lead_fields as service
from apps.api.agents import lead_fields_writes as writes
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

#: Bounds a review body: more keys than a draft ever holds
#: (`workers/lead_fields_draft.MAX_DRAFTED_FIELDS`).
MAX_DRAFT_KEYS = 40


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
    #: The owner has kept or discarded it (D-821). A `done` draft that is not reviewed
    #: waits on this screen and has reached no agent; once reviewed, `fields` is what
    #: was kept.
    reviewed: bool


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
    #: The details every lead carries, whatever the business, under this client's names.
    #: What each holds never changes; only the name shown is the client's.
    core_fields: list[ExtractionField]
    #: The platform's name for each core detail, by key: what a cleared name goes back to.
    core_default_labels: dict[str, str]
    #: The core field that says what the caller wants.
    need_key: str
    #: The standard set for this business type; empty for a custom business.
    standard_fields: list[ExtractionField]
    has_standard_set: bool
    draft: LeadFieldsDraftOut | None
    #: May a draft be queued now: no draft yet, or a failed one. Every business type may.
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
        reviewed=draft.reviewed,
    )


async def _render(session: AsyncSession, *, tenant_id: UUID) -> LeadFieldsOut:
    vertical = await service.vertical_of(session, tenant_id=tenant_id)
    draft = await service.read_draft(session, tenant_id=tenant_id)
    standard = service.has_standard_set(vertical)
    return LeadFieldsOut(
        business_type=vertical,
        business_type_label=service.business_type_label(vertical),
        core_fields=core_fields(await service.core_labels(session, tenant_id=tenant_id)),
        core_default_labels={f.key: f.label for f in CORE_LEAD_FIELDS},
        need_key=NEED_KEY,
        standard_fields=service.standard_fields(vertical) if standard else [],
        has_standard_set=standard,
        draft=_draft_out(draft),
        can_draft=draft is None or draft.status == "failed",
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


def _replace_out(written: list[service.AgentWrite]) -> ReplaceOut:
    changed = sum(1 for w in written if w.changed)
    return ReplaceOut(agents_changed=changed, agents_unchanged=len(written) - changed)


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """An operator route names its client in the path: a uuid naming nobody is a 404,
    never a business rule about a draft that an absent account cannot have."""
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Organization")


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


class LeadFieldsReviewIn(BaseModel):
    """The drafted fields the owner keeps, by key. Empty discards the draft."""

    model_config = ConfigDict(extra="forbid")

    keep: list[str] = Field(max_length=MAX_DRAFT_KEYS)


class LeadFieldsReviewOut(_Out):
    fields_kept: int
    agents_changed: int


@router.post(
    "/draft/review",
    response_model=LeadFieldsReviewOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Keep some or none of the drafted lead details (D-821)",
    description=(
        "The kept fields go onto every agent that has no business details of its own yet "
        "and become what a new agent starts with; the rest are dropped. Once: a reviewed "
        "draft is refused (409). Asking for the draft is Pip's (`lead_fields_draft`)."
    ),
)
async def post_draft_review(
    payload: LeadFieldsReviewIn, session: Session, principal: Owner, request: Request
) -> LeadFieldsReviewOut:
    assert principal.tenant_id is not None
    reviewed = await writes.keep_draft(session, tenant_id=principal.tenant_id, keep=payload.keep)
    await write_audit(
        session,
        action="lead_fields.draft_reviewed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={
            "field_keys": [f.key for f in reviewed.kept],
            "agents": [str(w.agent_id) for w in reviewed.written],
        },
    )
    return LeadFieldsReviewOut(
        fields_kept=len(reviewed.kept),
        agents_changed=sum(1 for w in reviewed.written if w.changed),
    )


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
    # The scripts ask for the new details from the next call (D-722).
    done = await writes.replace_with_standard(
        session, tenant_id=principal.tenant_id, agent_ids=payload.agent_ids
    )
    fields, written = done.fields, done.written
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


CoreKey = Literal["name", "need", "preferred_time", "other_number", "language", "notes"]


class CoreLabelsIn(BaseModel):
    """The client's names for the core details, every one at once. A blank or omitted
    detail shows the platform's name."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[CoreKey, Annotated[str, Field(max_length=CORE_LABEL_MAX_CHARS)]]


def _checked_labels(labels: dict[str, str]) -> dict[str, str]:
    """Refuse two details under one name rather than quietly keeping a default."""
    defaults = {f.key: f.label for f in CORE_LEAD_FIELDS}
    named = clean_core_labels(labels)
    for key, raw in labels.items():
        wanted = " ".join(raw.split())
        if wanted and wanted != defaults[key] and key not in named:
            raise ProblemError.business_rule(
                "core_label_taken",
                f"“{wanted}” is already the name of another detail.",
                remediation="Give each detail its own name.",
            )
    return named


async def _save_labels(
    session: AsyncSession, *, tenant_id: UUID, payload: CoreLabelsIn
) -> dict[str, str]:
    return await service.save_core_labels(
        session,
        tenant_id=tenant_id,
        labels=dict(_checked_labels({str(k): v for k, v in payload.labels.items()})),
    )


_CORE_LABELS_NOTE = (
    "Only the name shown on this client's screens, lists and exports changes; what each "
    "detail holds, and the instruction the call reader follows, stay the platform's. A blank "
    "name shows the platform's again. Two details may not share a name."
)


@router.put(
    "/core-labels",
    response_model=LeadFieldsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Name the details every lead carries in this business's own words",
    description=_CORE_LABELS_NOTE,
)
async def put_core_labels(
    payload: CoreLabelsIn, session: Session, principal: Owner, request: Request
) -> LeadFieldsOut:
    assert principal.tenant_id is not None
    named = await _save_labels(session, tenant_id=principal.tenant_id, payload=payload)
    await write_audit(
        session,
        action="lead_fields.core_labels_named",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"named_keys": sorted(named)},
    )
    return await _render(session, tenant_id=principal.tenant_id)


@admin_router.put(
    "/core-labels",
    response_model=LeadFieldsOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Name one client's core lead details in its own words",
    description=_CORE_LABELS_NOTE,
)
async def admin_put_core_labels(
    tenant_id: UUID, payload: CoreLabelsIn, request: Request, principal: Operator
) -> LeadFieldsOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        named = await _save_labels(scoped, tenant_id=tenant_id, payload=payload)
        await write_audit(
            scoped,
            action="admin.lead_fields_core_labels_named",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"named_keys": sorted(named)},
        )
        return await _render(scoped, tenant_id=tenant_id)


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
        await _require_tenant(scoped, tenant_id)
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
        await _require_tenant(scoped, tenant_id)
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
        await _require_tenant(scoped, tenant_id)
        done = await writes.replace_with_standard(
            scoped,
            tenant_id=tenant_id,
            agent_ids=payload.agent_ids,
            business_type=payload.business_type,
        )
        fields, written = done.fields, done.written
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
