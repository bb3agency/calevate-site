"""Suggested changes to what one campaign or inbound line notes, as the Lead details screen and
the job's own What it notes read and answer them (D-889; per job since D-1029).

    GET  /v1/campaigns/{campaign_id}/lead-suggestions                        the suggestions
    POST /v1/campaigns/{campaign_id}/lead-suggestions/check                  "Check again"
    POST /v1/campaigns/{campaign_id}/lead-suggestions/{suggestion_id}/accept
    POST /v1/campaigns/{campaign_id}/lead-suggestions/{suggestion_id}/dismiss

the same four under `/v1/inbound-lines/{line_id}/lead-suggestions`, and all eight under
`/v1/admin/tenants/{tenant_id}/...` for an operator, whose tenant is named in the path
(impersonation is read-only, so a mutation cannot infer it). One set of handlers serves both
kinds (`_mount`); the path names the job the way the job's own routes do.

Accepting saves the job's list through `campaigns/notes.save_notes`, the write the What it notes
Save uses, and then puts a job that holds calls live again (`campaigns/notes_live`), so its
next call asks for the change. Leads captured earlier keep what they noted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import field_suggestions as service
from apps.api.agents.models import MAX_FIELD_SUGGESTIONS
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.billing.trials import trial_billing_active
from apps.api.campaigns import notes_live
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

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Owner = Annotated[Principal, Depends(requires("org:manage"))]
OperatorReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
SuggestionId = Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]
Kind = Literal["campaign", "line"]


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
    source: Literal["purpose", "script", "business", "facts", "calls"]
    #: Recent calls on this job whose answer this would have caught.
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


class LeadSuggestionsAcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The suggestions to accept, in order; one no longer on offer is skipped.
    ids: list[Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]] = Field(
        min_length=1, max_length=MAX_FIELD_SUGGESTIONS
    )


class LeadSuggestionsAcceptedOut(_Out):
    #: What was accepted (at most the ids sent), and what is left.
    accepted: list[LeadSuggestionOut]
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


async def _state(session: AsyncSession, kind: Kind, job_id: UUID) -> LeadSuggestionsOut:
    read = await service.read_state(session, kind, job_id)
    return LeadSuggestionsOut(
        state=read.state,
        suggestions=[_one(s) for s in read.suggestions],
        checked_at=read.checked_at,
    )


def _audit_summary(kind: Kind, s: service.Suggestion) -> dict[str, object]:
    """Kind, field key and how many choices: the choice words are the business's wording, and
    a choice an owner typed could carry anything, so they stay out of the audit row."""
    return {
        "job": kind,
        "suggestion": s.id,
        "kind": s.kind,
        "field_key": s.field_key,
        "values": len(s.values),
    }


def _object_type(kind: Kind) -> str:
    return "campaign" if kind == "campaign" else "inbound_line"


_DESCRIPTION: Final = (
    "Suggestions come from the business's details, the job's script, the quick facts and what "
    "the job's recent callers asked for that no choice fitted. Nothing changes until one is "
    "accepted; a dismissed one is not offered again."
)


def _mount(client: APIRouter, admin: APIRouter, kind: Kind, id_param: str) -> None:
    """The four client handlers and their four admin twins for one kind of job. `id_param` is
    the path's own name for the job (`campaign_id`, `line_id`), read through an alias."""
    noun = "campaign" if kind == "campaign" else "line"
    # A default, not an annotation: annotations are strings here (PEP 563) and FastAPI
    # resolves them in module scope, where `id_param` does not exist.
    job_path = Path(alias=id_param)

    @client.get(
        "",
        response_model=LeadSuggestionsOut,
        openapi_extra=permission_meta("org:read"),
        summary=f"Suggested changes to what this {noun} notes",
        description=_DESCRIPTION,
        operation_id=f"get_{noun}_lead_suggestions",
    )
    async def get_lead_suggestions(
        *, job_id: UUID = job_path, session: Session, principal: Reader
    ) -> LeadSuggestionsOut:
        assert principal.tenant_id is not None
        return await _state(session, kind, job_id)

    @client.post(
        "/check",
        response_model=LeadSuggestionsOut,
        status_code=202,
        openapi_extra=permission_meta("org:manage"),
        summary=f"Look again for changes to what this {noun} notes",
        description=(
            "Queues a fresh look. On a paying account it uses the monthly AI allowance; on a "
            "trial it is free."
        ),
        operation_id=f"check_{noun}_lead_suggestions",
    )
    async def check_lead_suggestions(
        *,
        job_id: UUID = job_path,
        session: Session,
        principal: Owner,
        request: Request,
    ) -> LeadSuggestionsOut:
        tenant_id = principal.tenant_id
        assert tenant_id is not None
        # A stranger's job is a 404 before anything about this account is read.
        await service.read_state(session, kind, job_id)
        if not await trial_billing_active(session, tenant_id=tenant_id):
            # A pass spends this account's AI allowance (D-827), so it is refused up front
            # rather than queued only to be skipped by the worker.
            assert_view_as_may(principal, "billing.ai_assist")
            await require_ai_assist(session, tenant_id=tenant_id)
        await service.queue_pass(session, tenant_id=tenant_id, kind=kind, job_id=job_id, force=True)
        await write_audit(
            session,
            action="lead_suggestions.checked",
            actor=principal,
            tenant_id=tenant_id,
            object_type=_object_type(kind),
            object_id=str(job_id),
            ip=client_request_ip(request),
        )
        return await _state(session, kind, job_id)

    @client.post(
        "/accept",
        response_model=LeadSuggestionsAcceptedOut,
        openapi_extra=permission_meta("org:manage"),
        summary=f"Make several suggested changes to what this {noun} notes, at once",
        description=(
            "Each as its single accept would, in one save, then the job is put live once. "
            "A suggestion an earlier one overtook, or no longer on offer, is skipped."
        ),
        operation_id=f"accept_{noun}_lead_suggestions",
    )
    async def accept_lead_suggestions(
        body: LeadSuggestionsAcceptIn,
        *,
        job_id: UUID = job_path,
        principal: Owner,
        request: Request,
    ) -> LeadSuggestionsAcceptedOut:
        tenant_id = principal.tenant_id
        assert tenant_id is not None
        async with tenant_session(tenant_id) as own:
            accepted = await service.accept_many(own, kind, job_id, suggestion_ids=body.ids)
            for one in accepted:
                await write_audit(
                    own,
                    action="lead_suggestions.accepted",
                    actor=principal,
                    tenant_id=tenant_id,
                    object_type=_object_type(kind),
                    object_id=str(job_id),
                    ip=client_request_ip(request),
                    summary=_audit_summary(kind, one),
                )
        await notes_live.put_live(tenant_id, kind, job_id)
        async with tenant_session(tenant_id) as session:
            return LeadSuggestionsAcceptedOut(
                accepted=[_one(s) for s in accepted], remaining=await _state(session, kind, job_id)
            )

    @client.post(
        "/{suggestion_id}/accept",
        response_model=LeadSuggestionAnsweredOut,
        openapi_extra=permission_meta("org:manage"),
        summary=f"Make one suggested change to what this {noun} notes",
        description=(
            "Saved as the job's list, exactly as its What it notes Save does; leads captured "
            "earlier keep their details. 409 when the list changed since the suggestion was "
            "made."
        ),
        operation_id=f"accept_{noun}_lead_suggestion",
    )
    async def accept_lead_suggestion(
        *,
        job_id: UUID = job_path,
        suggestion_id: SuggestionId,
        principal: Owner,
        request: Request,
    ) -> LeadSuggestionAnsweredOut:
        tenant_id = principal.tenant_id
        assert tenant_id is not None
        # Its own transaction, committed before the put-live reads the list in another.
        async with tenant_session(tenant_id) as own:
            accepted = await service.accept(own, kind, job_id, suggestion_id=suggestion_id)
            await write_audit(
                own,
                action="lead_suggestions.accepted",
                actor=principal,
                tenant_id=tenant_id,
                object_type=_object_type(kind),
                object_id=str(job_id),
                ip=client_request_ip(request),
                summary=_audit_summary(kind, accepted),
            )
        await notes_live.put_live(tenant_id, kind, job_id)
        async with tenant_session(tenant_id) as session:
            return LeadSuggestionAnsweredOut(
                answered=_one(accepted), remaining=await _state(session, kind, job_id)
            )

    @client.post(
        "/{suggestion_id}/dismiss",
        response_model=LeadSuggestionAnsweredOut,
        openapi_extra=permission_meta("org:manage"),
        summary="Turn down one suggested change; it is not offered again",
        operation_id=f"dismiss_{noun}_lead_suggestion",
    )
    async def dismiss_lead_suggestion(
        *,
        job_id: UUID = job_path,
        suggestion_id: SuggestionId,
        session: Session,
        principal: Owner,
        request: Request,
    ) -> LeadSuggestionAnsweredOut:
        assert principal.tenant_id is not None
        dismissed = await service.dismiss(session, kind, job_id, suggestion_id=suggestion_id)
        await write_audit(
            session,
            action="lead_suggestions.dismissed",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type=_object_type(kind),
            object_id=str(job_id),
            ip=client_request_ip(request),
            summary=_audit_summary(kind, dismissed),
        )
        return LeadSuggestionAnsweredOut(
            answered=_one(dismissed), remaining=await _state(session, kind, job_id)
        )

    @admin.get(
        "",
        response_model=LeadSuggestionsOut,
        openapi_extra=permission_meta("org:read"),
        summary=f"Suggested changes to what one client {noun} notes",
        description=_DESCRIPTION,
        operation_id=f"admin_get_{noun}_lead_suggestions",
    )
    async def admin_get_lead_suggestions(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        request: Request,
        principal: OperatorReader,
    ) -> LeadSuggestionsOut:
        async with tenant_session(tenant_id) as scoped:
            out = await _state(scoped, kind, job_id)
            await record_admin_tenant_read(
                scoped, request=request, principal=principal, tenant_id=tenant_id
            )
        return out

    @admin.post(
        "/check",
        response_model=LeadSuggestionsOut,
        status_code=202,
        openapi_extra=permission_meta("admin:tenants"),
        summary=f"Look again for changes to what one client {noun} notes",
        operation_id=f"admin_check_{noun}_lead_suggestions",
    )
    async def admin_check_lead_suggestions(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        principal: Operator,
        request: Request,
    ) -> LeadSuggestionsOut:
        async with tenant_session(tenant_id) as scoped:
            await service.read_state(scoped, kind, job_id)
            await service.queue_pass(
                scoped, tenant_id=tenant_id, kind=kind, job_id=job_id, force=True
            )
            await write_audit(
                scoped,
                action="admin.lead_suggestions_checked",
                actor=principal,
                tenant_id=tenant_id,
                object_type=_object_type(kind),
                object_id=str(job_id),
                ip=client_request_ip(request),
            )
            return await _state(scoped, kind, job_id)

    @admin.post(
        "/accept",
        response_model=LeadSuggestionsAcceptedOut,
        openapi_extra=permission_meta("admin:tenants"),
        summary=f"Make several suggested changes to what a client {noun} notes, at once",
        operation_id=f"admin_accept_{noun}_lead_suggestions",
    )
    async def admin_accept_lead_suggestions(
        tenant_id: UUID,
        body: LeadSuggestionsAcceptIn,
        *,
        job_id: UUID = job_path,
        principal: Operator,
        request: Request,
    ) -> LeadSuggestionsAcceptedOut:
        async with tenant_session(tenant_id) as scoped:
            accepted = await service.accept_many(scoped, kind, job_id, suggestion_ids=body.ids)
            for one in accepted:
                await write_audit(
                    scoped,
                    action="admin.lead_suggestions_accepted",
                    actor=principal,
                    tenant_id=tenant_id,
                    object_type=_object_type(kind),
                    object_id=str(job_id),
                    ip=client_request_ip(request),
                    summary=_audit_summary(kind, one),
                )
        await notes_live.put_live(tenant_id, kind, job_id)
        async with tenant_session(tenant_id) as scoped:
            return LeadSuggestionsAcceptedOut(
                accepted=[_one(s) for s in accepted], remaining=await _state(scoped, kind, job_id)
            )

    @admin.post(
        "/{suggestion_id}/accept",
        response_model=LeadSuggestionAnsweredOut,
        openapi_extra=permission_meta("admin:tenants"),
        summary=f"Make one suggested change to what a client {noun} notes",
        operation_id=f"admin_accept_{noun}_lead_suggestion",
    )
    async def admin_accept_lead_suggestion(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        suggestion_id: SuggestionId,
        principal: Operator,
        request: Request,
    ) -> LeadSuggestionAnsweredOut:
        async with tenant_session(tenant_id) as scoped:
            accepted = await service.accept(scoped, kind, job_id, suggestion_id=suggestion_id)
            await write_audit(
                scoped,
                action="admin.lead_suggestions_accepted",
                actor=principal,
                tenant_id=tenant_id,
                object_type=_object_type(kind),
                object_id=str(job_id),
                ip=client_request_ip(request),
                summary=_audit_summary(kind, accepted),
            )
        await notes_live.put_live(tenant_id, kind, job_id)
        async with tenant_session(tenant_id) as scoped:
            return LeadSuggestionAnsweredOut(
                answered=_one(accepted), remaining=await _state(scoped, kind, job_id)
            )

    @admin.post(
        "/{suggestion_id}/dismiss",
        response_model=LeadSuggestionAnsweredOut,
        openapi_extra=permission_meta("admin:tenants"),
        summary=f"Turn down one suggested change to what a client {noun} notes",
        operation_id=f"admin_dismiss_{noun}_lead_suggestion",
    )
    async def admin_dismiss_lead_suggestion(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        suggestion_id: SuggestionId,
        principal: Operator,
        request: Request,
    ) -> LeadSuggestionAnsweredOut:
        async with tenant_session(tenant_id) as scoped:
            dismissed = await service.dismiss(scoped, kind, job_id, suggestion_id=suggestion_id)
            await write_audit(
                scoped,
                action="admin.lead_suggestions_dismissed",
                actor=principal,
                tenant_id=tenant_id,
                object_type=_object_type(kind),
                object_id=str(job_id),
                ip=client_request_ip(request),
                summary=_audit_summary(kind, dismissed),
            )
            return LeadSuggestionAnsweredOut(
                answered=_one(dismissed), remaining=await _state(scoped, kind, job_id)
            )


router = APIRouter(tags=["agents"])
admin_router = APIRouter(tags=["admin"])
_campaigns = APIRouter(prefix="/v1/campaigns/{campaign_id}/lead-suggestions")
_lines = APIRouter(prefix="/v1/inbound-lines/{line_id}/lead-suggestions")
_admin_campaigns = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/lead-suggestions"
)
_admin_lines = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/inbound-lines/{line_id}/lead-suggestions"
)
_mount(_campaigns, _admin_campaigns, "campaign", "campaign_id")
_mount(_lines, _admin_lines, "line", "line_id")
router.include_router(_campaigns)
router.include_router(_lines)
admin_router.include_router(_admin_campaigns)
admin_router.include_router(_admin_lines)

__all__ = ["admin_router", "router"]
