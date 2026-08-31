"""Client-realm knowledge-base endpoints (FLOWS §7): submit, preview, list, propose.

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

from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.kb import proposals, service

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
    principal: Principal = Depends(requires("kb:write")),
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


# --- agent-proposed knowledge -------------------------------------------------
#
# TWO ROUTES, AND THE SPLIT IS THE PRODUCT PROPERTY. `POST /proposals` READS — it
# validates a draft and hands back a signed, expiring, single-use token, and a client that
# never calls the second route has changed nothing anywhere. `POST /proposals/confirm` is
# the mutation, and everything it mutates it mutates through `service.submit_source`, the
# same function `submit` above calls: the row it creates is `pending_approval` and reaches
# a live agent only through the SAME admin approve → publish path as a pasted one.
#
# Both carry `kb:write`, checked at both ends, because both are the same decision — what
# the agent knows (D-21). Proposing is gated as well as confirming even though it writes
# nothing: it reads an agent and this tenant's open knowledge gaps to build the draft, and
# "it is only a read" is how an unauthenticated drafting oracle gets shipped.
#
# `kb:write` is MUTATING, so `requires` refuses it to an impersonating admin (D-22) — an
# operator cannot reach either end of this lane through a view-as session, which is
# correct and is why neither route carries an impersonation check of its own.


class ProposeIn(Strict):
    agent_id: UUID
    name: str = Field(min_length=1, max_length=proposals.MAX_NAME_CHARS)
    body: str = Field(min_length=proposals.MIN_BODY_CHARS, max_length=proposals.MAX_BODY_CHARS)
    #: Who raised the subject — `gap_digest` (the agent noticed) or `copilot` (it came up
    #: in conversation). Shown to whoever approves it, because the two carry different
    #: trust; it changes no gate.
    origin: proposals.ProposalOrigin
    #: The canonical knowledge-gap topic this answers. Required for `gap_digest`.
    topic_key: str | None = None


class ProposeOut(Strict):
    """The draft and the token that could execute it. `token` is NOT a credential for
    anything else: it is bound to this tenant, this person and this one draft, it expires,
    and it can be spent once."""

    token: str
    agent_id: UUID
    name: str
    body: str
    origin: proposals.ProposalOrigin
    topic_key: str | None
    expires_at: datetime


class ConfirmIn(Strict):
    token: str = Field(min_length=1, max_length=16_000)


@router.post(
    "/proposals",
    response_model=ProposeOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Draft a knowledge entry for review — writes nothing, returns a signed token",
)
async def propose_knowledge(
    payload: ProposeIn,
    session: Session,
    principal: Principal = Depends(requires("kb:write")),
) -> ProposeOut:
    proposal, token = await proposals.build_proposal(
        session,
        principal=principal,
        agent_id=payload.agent_id,
        name=payload.name,
        body=payload.body,
        origin=payload.origin,
        topic_key=payload.topic_key,
    )
    return ProposeOut(
        token=token,
        agent_id=proposal.agent_id,
        name=proposal.name,
        body=proposal.body,
        origin=proposal.origin,
        topic_key=proposal.topic_key,
        expires_at=proposal.expires_at,
    )


@router.post(
    "/proposals/confirm",
    response_model=SubmitOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Confirm a suggestion — enters the SAME review queue, still NOT live",
)
async def confirm_knowledge_proposal(
    payload: ConfirmIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("kb:write")),
) -> SubmitOut:
    result = await proposals.confirm_proposal(
        session,
        token=payload.token,
        principal=principal,
        ip=client_request_ip(request),
    )
    return SubmitOut.model_validate(result)


__all__ = ["router"]
