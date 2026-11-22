"""The lead details a business captures, as one screen reads and changes them (D-1029).

    GET   /v1/lead-fields                        the core, the business type, the starting
                                                 set, every open campaign's and line's list
                                                 and the AI draft's state
    PUT   /v1/lead-fields/core-labels            the client's own names for the core details
    POST  /v1/lead-fields/draft/review           keep some or none of the AI draft and write
                                                 what is kept onto the ticked campaigns and
                                                 lines (D-821; the draft itself is asked of
                                                 Pip)
    POST  /v1/lead-fields/replace                write the standard set (or the kept draft)
                                                 onto the ticked campaigns and lines

    GET   /v1/admin/tenants/{tenant_id}/lead-fields           the same, for an operator
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/draft     queue the draft
    POST  /v1/admin/tenants/{tenant_id}/lead-fields/replace   replace, optionally from
                                                              another type's standard set
    PUT   /v1/admin/tenants/{tenant_id}/lead-fields/core-labels   the same names, for an operator
    GET   /v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/notes   (and PUT; the same
    GET   /v1/admin/tenants/{tenant_id}/inbound-lines/{line_id}/notes   pair for a line)
                                                 one campaign's or line's list, for an operator

The client edits one job's list through that job's own notes route (`/v1/campaigns/{id}/notes`,
`/v1/inbound-lines/{id}/notes`), the same editor the job's page shows: one write path for a
list, whatever screen it is edited from (`campaigns/notes.save_notes`). Every apply here names
its jobs with the digest the screen showed, so a list changed meanwhile is refused (409)
rather than overwritten.
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
from calevate_shared.verticals import BusinessTypeKey
from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.agents import lead_fields as service
from apps.api.agents import lead_fields_writes as writes
from apps.api.campaigns import notes as job_notes
from apps.api.campaigns import notes_live
from apps.api.campaigns.workspace_routes import JobNotesIn, JobNotesOut, job_notes_out
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

#: Every open campaign and line the screen can list (`lead_fields.MAX_JOBS` of each).
MAX_JOB_REFS = 2 * service.MAX_JOBS

#: Bounds a review body: more keys than a draft ever holds
#: (`workers/lead_fields_draft.MAX_DRAFTED_FIELDS`).
MAX_DRAFT_KEYS = 40

JobKind = Literal["campaign", "line"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: `agents.models.LEAD_FIELD_DRAFT_STATUSES`, which the table's CHECK holds.
DraftStatus = Literal["queued", "running", "done", "failed"]


class LeadFieldsDraftOut(_Out):
    """The one AI draft of a custom business's fields."""

    status: DraftStatus
    requested_at: datetime
    completed_at: datetime | None
    #: What was drafted, as drafted. The jobs' current lists may since differ.
    fields: list[ExtractionField]
    #: A machine code when `failed` (`no_draft`, `no_provider`, `draft_crashed`).
    error_code: str | None
    #: The owner has kept or discarded it (D-821). A `done` draft that is not reviewed
    #: waits on this screen and has reached no campaign or line; once reviewed, `fields` is
    #: what was kept.
    reviewed: bool


class LeadFieldsJobOut(_Out):
    """One open campaign or inbound line and what its calls note."""

    kind: JobKind
    id: UUID
    name: str
    #: A campaign's status, or `live` / `draft` for a line.
    status: str
    #: Running now: a running campaign, or a line callers hear.
    live: bool
    agent_id: UUID
    agent_name: str
    fields: list[ExtractionField]
    #: Sent back with an apply that names this job, so a list changed meanwhile is refused.
    digest: str
    #: Nobody chose this list (empty, or exactly a set the platform offered): an apply of a
    #: new starting set ticks it by default.
    untouched: bool


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
    #: What a new campaign or line starts with: the kept draft, else `standard_fields`.
    starting_fields: list[ExtractionField]
    draft: LeadFieldsDraftOut | None
    #: May a draft be queued now: no draft yet, or a failed one. Every business type may.
    can_draft: bool
    #: Every open campaign, then every line, running ones first, then by name.
    jobs: list[LeadFieldsJobOut]


class JobRefIn(BaseModel):
    """A campaign or line to write, with the `digest` of the list the screen showed for it."""

    model_config = ConfigDict(extra="forbid")

    kind: JobKind
    id: UUID
    digest: str = Field(max_length=64)


class ReplaceIn(BaseModel):
    """Which campaigns and lines get the standard set (or the kept draft)."""

    model_config = ConfigDict(extra="forbid")

    jobs: list[JobRefIn] = Field(min_length=1, max_length=MAX_JOB_REFS)


class AdminReplaceIn(ReplaceIn):
    #: Take another type's standard set instead of this business's own type's. Lets an
    #: operator move an account to a new type and its lists in two deliberate steps.
    business_type: BusinessTypeKey | None = None


class ReplaceOut(_Out):
    jobs_changed: int
    jobs_unchanged: int
    #: Changed jobs that hold calls whose put-live was refused: they keep their previous
    #: list on calls until their next Start or Put it live.
    jobs_waiting: int


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
    starting = await service.starting_business_fields(
        session, tenant_id=tenant_id, vertical=vertical
    )
    return LeadFieldsOut(
        business_type=vertical,
        business_type_label=service.business_type_label(vertical),
        core_fields=core_fields(await service.core_labels(session, tenant_id=tenant_id)),
        core_default_labels={f.key: f.label for f in CORE_LEAD_FIELDS},
        need_key=NEED_KEY,
        standard_fields=service.standard_fields(vertical) if standard else [],
        has_standard_set=standard,
        starting_fields=starting,
        draft=_draft_out(draft),
        can_draft=draft is None or draft.status == "failed",
        jobs=[
            LeadFieldsJobOut(
                kind=job.kind,
                id=job.id,
                name=job.name,
                status=job.status,
                live=job.live,
                agent_id=job.agent_id,
                agent_name=job.agent_name,
                fields=job.fields,
                digest=job.digest,
                untouched=job.untouched,
            )
            for job in await service.jobs_with_fields(session, starting=starting)
        ],
    )


def _refs(jobs: list[JobRefIn]) -> list[service.JobRef]:
    seen: set[tuple[str, UUID]] = set()
    refs: list[service.JobRef] = []
    for job in jobs:
        if (job.kind, job.id) in seen:
            continue
        seen.add((job.kind, job.id))
        refs.append(service.JobRef(kind=job.kind, job_id=job.id, digest=job.digest))
    return refs


def _changed(written: list[service.JobWrite]) -> list[tuple[service.JobKind, UUID]]:
    return [(w.kind, w.job_id) for w in written if w.changed]


def _replace_out(written: list[service.JobWrite], waiting: int) -> ReplaceOut:
    changed = sum(1 for w in written if w.changed)
    return ReplaceOut(
        jobs_changed=changed, jobs_unchanged=len(written) - changed, jobs_waiting=waiting
    )


def _jobs_summary(written: list[service.JobWrite]) -> list[str]:
    """`campaign:<id>` / `line:<id>` per job written, for the audit row: ids, never a value."""
    return [f"{w.kind}:{w.job_id}" for w in written]


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """An operator route names its client in the path: a uuid naming nobody is a 404,
    never a business rule about a draft that an absent account cannot have."""
    if not await tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Organization")


_REPLACE_NOTE = (
    "Each campaign and line named gets the set as its whole list, under a compare-and-set on "
    "the digest the screen showed (409 when one changed meanwhile, and then none is written). "
    "Values already captured stay on their leads and calls. A job that holds calls is put live "
    "again so its next call asks for the new details."
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
    """The drafted fields the owner keeps, by key, and the campaigns and lines that take them.
    An empty `keep` discards the draft and writes nothing."""

    model_config = ConfigDict(extra="forbid")

    keep: list[str] = Field(max_length=MAX_DRAFT_KEYS)
    jobs: list[JobRefIn] = Field(default_factory=list, max_length=MAX_JOB_REFS)


class LeadFieldsReviewOut(_Out):
    fields_kept: int
    jobs_changed: int
    jobs_waiting: int


@router.post(
    "/draft/review",
    response_model=LeadFieldsReviewOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Keep some or none of the drafted lead details (D-821)",
    description=(
        "The kept fields become what a new campaign or line starts with, and are written onto "
        "each campaign and line named in `jobs`; the rest are dropped. Once: a reviewed draft "
        "is refused (409). Asking for the draft is Pip's (`lead_fields_draft`)."
    ),
)
async def post_draft_review(
    payload: LeadFieldsReviewIn, principal: Owner, request: Request
) -> LeadFieldsReviewOut:
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    async with tenant_session(tenant_id) as own:
        done = await writes.keep_draft(
            own, tenant_id=tenant_id, keep=payload.keep, jobs=_refs(payload.jobs)
        )
        await write_audit(
            own,
            action="lead_fields.draft_reviewed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "field_keys": [f.key for f in done.kept],
                "jobs": _jobs_summary(done.written),
            },
        )
    waiting = await notes_live.put_live_each(tenant_id, _changed(done.written))
    return LeadFieldsReviewOut(
        fields_kept=len(done.kept),
        jobs_changed=sum(1 for w in done.written if w.changed),
        jobs_waiting=waiting,
    )


@router.post(
    "/replace",
    response_model=ReplaceOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Start campaigns and lines again from this business's standard lead details",
    description=_REPLACE_NOTE,
)
async def post_replace(payload: ReplaceIn, principal: Owner, request: Request) -> ReplaceOut:
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    async with tenant_session(tenant_id) as own:
        done = await writes.replace_with_standard(
            own, tenant_id=tenant_id, jobs=_refs(payload.jobs)
        )
        await write_audit(
            own,
            action="lead_fields.replaced",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "jobs": _jobs_summary(done.written),
                "field_keys": [f.key for f in done.fields],
            },
        )
    waiting = await notes_live.put_live_each(tenant_id, _changed(done.written))
    return _replace_out(done.written, waiting)


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
    summary="Replace one client's campaigns' and lines' lead details with a standard set",
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
            jobs=_refs(payload.jobs),
            business_type=payload.business_type,
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
                "jobs": _jobs_summary(done.written),
                "field_keys": [f.key for f in done.fields],
            },
        )
    waiting = await notes_live.put_live_each(tenant_id, _changed(done.written))
    return _replace_out(done.written, waiting)


async def _admin_notes_out(tenant_id: UUID, kind: JobKind, job_id: UUID) -> JobNotesOut:
    applied_now = await notes_live.holds_calls(tenant_id, kind, job_id)
    async with tenant_session(tenant_id) as scoped:
        return await job_notes_out(scoped, kind, job_id, applied_now=applied_now)


def _mount_admin_notes(router: APIRouter, kind: JobKind, id_param: str) -> None:
    """GET and PUT of one job's list for an operator, one pair per kind of job. `id_param` is
    the path's own name for the job, read through an alias."""
    noun = "campaign" if kind == "campaign" else "line"
    # A default, not an annotation: annotations are strings here (PEP 563) and FastAPI
    # resolves them in module scope, where `id_param` does not exist.
    job_path = Path(alias=id_param)

    @router.get(
        "",
        response_model=JobNotesOut,
        openapi_extra=permission_meta("org:read"),
        summary=f"What one client {noun}'s calls note",
        operation_id=f"admin_get_{noun}_notes",
    )
    async def admin_get_job_notes(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        request: Request,
        principal: AdminReader,
    ) -> JobNotesOut:
        async with tenant_session(tenant_id) as scoped:
            await _require_tenant(scoped, tenant_id)
            # The 404 for another account's job comes before the read is recorded.
            await job_notes.read_notes(scoped, kind, job_id)
            await record_admin_tenant_read(
                scoped, request=request, principal=principal, tenant_id=tenant_id
            )
        return await _admin_notes_out(tenant_id, kind, job_id)

    @router.put(
        "",
        response_model=JobNotesOut,
        openapi_extra=permission_meta("admin:tenants"),
        summary=f"Set what one client {noun}'s calls note",
        description=(
            "The whole list under a compare-and-set on the digest the editor read, held to "
            "the extraction rules. A job that holds calls is put live again so its next call "
            "asks for the new details."
        ),
        operation_id=f"admin_put_{noun}_notes",
    )
    async def admin_put_job_notes(
        tenant_id: UUID,
        *,
        job_id: UUID = job_path,
        payload: JobNotesIn,
        request: Request,
        principal: Operator,
    ) -> JobNotesOut:
        async with tenant_session(tenant_id) as scoped:
            await _require_tenant(scoped, tenant_id)
            changed = await job_notes.save_notes(
                scoped, kind, job_id, payload.fields, expected_digest=payload.expected_digest
            )
            if changed:
                await write_audit(
                    scoped,
                    action="admin.job_notes_saved",
                    actor=principal,
                    tenant_id=tenant_id,
                    object_type="campaign" if kind == "campaign" else "inbound_line",
                    object_id=str(job_id),
                    ip=client_request_ip(request),
                    # The keys, never a value: who changed which details is what is audited.
                    summary={"fields": [field.key for field in payload.fields]},
                )
        # Unchanged too: an unchanged save is the Save again a refused put-live asks for.
        try:
            await notes_live.put_live(tenant_id, kind, job_id)
        except ProblemError as exc:
            exc.title = "Saved, but not on its calls yet"
            exc.remediation = (
                "The change is kept. Save again to put it on the calls. " + (exc.remediation or "")
            ).strip()
            raise
        return await _admin_notes_out(tenant_id, kind, job_id)


#: The operator's twins of `/v1/campaigns/{id}/notes` and `/v1/inbound-lines/{id}/notes`.
admin_notes_router = APIRouter(tags=["admin"])
_campaign_notes = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/notes")
_line_notes = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/inbound-lines/{line_id}/notes")
_mount_admin_notes(_campaign_notes, "campaign", "campaign_id")
_mount_admin_notes(_line_notes, "line", "line_id")
admin_notes_router.include_router(_campaign_notes)
admin_notes_router.include_router(_line_notes)


__all__ = ["admin_notes_router", "admin_router", "router"]
