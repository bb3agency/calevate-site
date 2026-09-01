"""Client-realm knowledge-base endpoints (FLOWS §7): submit, preview, list.

The split of permissions IS the workflow: a client owner (`kb:write`) SUBMITS and
previews here; approval and publish live on the ADMIN router instead. That is not
bureaucracy — the agent speaks under the client's own PE registration, so a change to
what it says is a change to a legal instrument, and a human reads it first.

Why approval is not simply another route in this file: an admin reaching a tenant does
so through impersonation, and impersonation is READ-ONLY by D-22. An approve endpoint
here would be permanently un-callable — reachable only with a tenant context that
refuses mutations. So the mutating half goes where D-22 says it goes: "mutations still
go through admin surfaces", with the tenant named explicitly in the path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.kb import service
from apps.api.kb.curation import read_switch, requires_kb_curation, write_switch

router = APIRouter(prefix="/v1/kb", tags=["knowledge-base"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=10, max_length=200_000)
    # `url` and `file` are DECLARED here and REFUSED by the service
    # (`kb.service.SUPPORTED_SUBMISSION_KINDS`, which carries the argument and names the
    # external blocker). They are still in the Literal because narrowing it regenerates
    # the OpenAPI schema and the typed client, which is a whole-tree change; what mattered
    # was that the endpoint stopped answering 201 to a fetch it never performed.
    kind: Literal["text", "url", "file"] = "text"
    #: Where the content came from, for kinds we cannot yet read. Written, never read —
    #: no fetcher and no parser exists (TRD §6's offline ingestion step).
    #:
    #: BOUNDED, because it is STORED (D-302). It was the only string on this model with
    #: no ceiling, so the durable size of a `kb_sources` row was set by the body cap
    #: rather than by anything about a URI. 2048 is the conventional URL ceiling —
    #: IE's historic limit, and what nginx, Apache and every URL-shaped column in this
    #: repo assume (RFC 9110 §4.1 sets no limit and says servers must impose one).
    uri: str | None = Field(default=None, max_length=2048)


class SourceOut(Strict):
    id: UUID
    agent_id: UUID
    name: str
    kind: str
    status: str
    version: int
    is_active: bool
    published_at: datetime | None
    chunks: int


class SubmitOut(Strict):
    id: UUID
    version: int
    chunks: int
    status: str


class ChunkOut(Strict):
    idx: int
    content: str
    chars: int


# The two READS below are gated on `agents:read`, not `kb:write`. They were `kb:write`
# and that made the admin console's approval queue permanently unreadable: the queue is
# read through impersonation (D-22), impersonation refuses every MUTATING permission,
# and `kb:write` is one. Reading what an agent knows is an agent read; only submitting
# changes what it says.
@router.get(
    "/sources", response_model=list[SourceOut], openapi_extra=permission_meta("agents:read")
)
async def list_sources(
    session: Session,
    status: str | None = None,
    # Bounded (D-302): a knowledge source is a row the CLIENT mints, one per document
    # they submit, and nothing prunes the archived ones — so the length of this list is
    # caller-controlled and grows for the life of the account.
    limit: int = Query(200, ge=1, le=200),
    _: Principal = Depends(requires("agents:read")),
) -> list[SourceOut]:
    return [
        SourceOut.model_validate(r)
        for r in await service.list_sources(session, status=status, limit=limit)
    ]


@router.post(
    "/sources",
    response_model=SubmitOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Submit knowledge for review — chunked, previewable, NOT yet live",
)
async def submit(
    payload: SubmitIn,
    session: Session,
    # `requires_kb_curation()`, NOT `requires("kb:write")`, and the swap is ADDITIVE:
    # it runs that dependency's ladder first and unchanged, then asks one further
    # question on the branch that was already a 403 — whether this account's owner
    # switched staff curation on (`kb/curation.py`). An `owner` reaches the identical
    # answer down the identical path in both states of that switch.
    principal: Principal = Depends(requires_kb_curation()),
) -> SubmitOut:
    assert principal.tenant_id is not None
    result = await service.submit_source(
        session,
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        name=payload.name,
        body=payload.body,
        kind=payload.kind,
        uri=payload.uri,
        submitted_by=principal.user_id,
    )
    return SubmitOut.model_validate(result)


@router.get(
    "/sources/{source_id}/preview",
    response_model=list[ChunkOut],
    openapi_extra=permission_meta("agents:read"),
    summary="Side-by-side preview of exactly what the agent would learn",
)
async def preview_source(
    source_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> list[ChunkOut]:
    return [ChunkOut.model_validate(c) for c in await service.preview(session, source_id)]


# --- Who in the account may curate: the OWNER's switch ----------------------------
#
# THE SWITCH LIVES BESIDE THE CAPABILITY IT UNLOCKS, deliberately. It could have been an
# organization-settings route (`/v1/organization/...`, where `default_llm_model` lives),
# and putting it under `/v1/kb` instead is what makes the grant's narrowness legible from
# the URL: this is not an account-wide role setting that happens to affect knowledge, it
# is the Knowledge surface's own answer to "who here may write this". A reader who wants
# the full reach greps `requires_kb_curation` and finds three routes.


class StaffCurationOut(Strict):
    """Whether this account's staff may curate knowledge.

    A DECLARED model rather than a bare mapping, for the reason `admin/routes.KbReviewOut`
    gives: `scripts/check_redaction_exposure.py` walks response models and is structurally
    blind to a route that declares none, and the generated TS client renders a mapping as
    an index signature the frontend then hand-types.
    """

    staff_may_curate_knowledge: bool


class StaffCurationIn(Strict):
    """The whole of the resource, which is what makes this a PUT rather than a PATCH —
    `LlmDefaultIn`'s argument, one field further down."""

    staff_may_curate_knowledge: bool


@router.get(
    "/staff-curation",
    response_model=StaffCurationOut,
    # `org:read`, not `org:manage`: SEEING whether staff may curate is not the authority
    # to decide it, and every role in both realms holds `org:read` — so a staff member can
    # be told why the Add-Knowledge form is closed to them, and an impersonating operator
    # can see the same screen the client sees when explaining it (D-22).
    openapi_extra=permission_meta("org:read"),
    summary="Whether this account lets its staff members curate knowledge",
)
async def get_staff_curation(
    session: Session, _: Principal = Depends(requires("org:read"))
) -> StaffCurationOut:
    return StaffCurationOut(staff_may_curate_knowledge=await read_switch(session))


@router.put(
    "/staff-curation",
    response_model=StaffCurationOut,
    # `org:manage` — THE OWNER'S PERMISSION, and the only permission that is right here.
    # `staff` does not hold it, so staff cannot widen their own authority, which is what
    # keeps this a delegation rather than a self-service escalation. It is in
    # `MUTATING_PERMISSIONS`, so D-22 refuses an impersonating admin: flipping a permission
    # switch is itself a mutation, and an operator who believes the account needs it says
    # so to the owner rather than doing it under the owner's name.
    #
    # NOT `requires_kb_curation()` — that would be the switch guarding itself, and an
    # account that had turned it on could then have it turned off by the very staff it
    # had been turned on for. The gate on the gate is the plain permission.
    openapi_extra=permission_meta("org:manage"),
    summary="Let this account's staff curate knowledge, or stop letting them",
    description=(
        "Off for every account until its owner turns it on. Switching it on lets members "
        "with the `staff` role submit knowledge for review and dismiss or teach a "
        "knowledge gap — and nothing else. It does not let them approve or publish "
        "anything: a staff-submitted source lands in the same review queue an owner's "
        "does, and still needs approval before an agent can say a word of it."
    ),
)
async def set_staff_curation(
    payload: StaffCurationIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> StaffCurationOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolved it
    changed = await write_switch(session, enabled=payload.staff_may_curate_knowledge)
    await write_audit(
        session,
        action="organization.staff_kb_curation_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        # THE VALUE, not just the field name: a boolean about who may act is neither
        # client business copy nor anyone's personal data (hard rule 6), and WHICH WAY the
        # switch went is the entire fact an investigator asking "who let a staff member
        # write this" needs. `changed` sits beside it because a PUT is idempotent — a run
        # of identical entries is a run of requests somebody made, and only one of them
        # moved the account.
        summary={
            "staff_may_curate_knowledge": payload.staff_may_curate_knowledge,
            "changed": changed,
        },
    )
    return StaffCurationOut(staff_may_curate_knowledge=payload.staff_may_curate_knowledge)


__all__ = ["router"]
