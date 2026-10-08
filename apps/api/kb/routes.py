"""Client-realm knowledge-base endpoints (FLOWS §7): submit, preview, list.

What the account's own people add here is approved on submission and published by a
worker with no human step (D-658, `kb/curation.goes_live_without_review`). The admin
approve and publish routes remain for everything else — a view-as operator's submission,
an intake seed, a changed link — and live on the ADMIN router because D-22 says
"mutations still go through admin surfaces", with the tenant named explicitly in the path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.kb import delivery, service, uploads
from apps.api.kb.curation import (
    goes_live_without_review,
    read_switch,
    requires_kb_curation,
    write_switch,
)

router = APIRouter(prefix="/v1/kb", tags=["knowledge-base"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: Knowledge belongs to the CLIENT and every agent answers from it (D-689), so a submission
#: names no agent. The field stays accepted — and is ignored — so a client built before
#: D-689 is not refused by `extra="forbid"`; it goes when that client is gone.
_AGENT_ID_DEPRECATED = (
    "Deprecated and ignored: knowledge is shared by every agent of the account (D-689)."
)


class SubmitIn(Strict):
    agent_id: UUID | None = Field(default=None, deprecated=True, description=_AGENT_ID_DEPRECATED)
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
    #: The MACHINE-WRITTEN English rendering of `content`, or None. NEVER the client's own
    #: words and never what the agent says — it is a retrieval key so that a Tenglish
    #: question (the form Sarvam's Saaras STT returns) can find a Telugu-script chunk at
    #: all (`apps/api/kb/gloss.py` carries the measurement). It is shown at the review
    #: screen so a reviewer can report a bad one, and `gloss_model` is beside it so the
    #: screen labels it by the model tier that wrote it (a tier word, never a model id —
    #: D-680) rather than asserting "machine-generated" as an unenforced convention.
    gloss: str | None = None
    gloss_model: str | None = None


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
    summary="Add knowledge — an account member's goes to every agent without review",
    description=(
        "An account member's submission (the owner, or staff the owner lets curate) is "
        "approved on submission and published to every agent of the account by a "
        "background job: `status` is `approved`, and the source turns live once that job "
        "has run. A view-as session's submission is `pending_approval` and waits for an "
        "admin."
    ),
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
        name=payload.name,
        body=payload.body,
        kind=payload.kind,
        uri=payload.uri,
        submitted_by=principal.user_id,
        auto_approve=goes_live_without_review(
            realm=principal.realm, impersonating=principal.impersonating
        ),
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


# --- Uploads and links: the half of this screen that did not exist (D-534) ---------
#
# `/c/{slug}/knowledge` offered a title box and a text box, so a clinic with a price list
# in a Word file had to retype it. These six routes are the door for a document, a
# photograph and a link. The MODEL of all of it is `kb/uploads.py`; what is here is the
# HTTP shape, the permission and the one thing a route must own: reading a request body
# without letting a stranger decide how much memory we spend on it.


class UploadOut(Strict):
    """One uploaded document or link, as a client's screen shows it.

    THE TWO STATES ARE SEPARATE FIELDS BECAUSE THEY ARE SEPARATE FACTS, and collapsing
    them into one "status" is the mistake this model exists to avoid. `ingest_status` is
    how far the machinery got (are the bytes read, has the voice platform indexed them);
    `review_state` is whether it is approved — on submission for the account's own people
    (D-658), by an admin for anything else. A document can be `processed` and still
    `pending_approval` — read, ready, and deliberately not live.
    """

    id: UUID
    source_id: UUID
    name: str
    #: `pdf` · `url` · `docx` · `txt` · `csv` · `xlsx` · `image`.
    source_kind: str
    #: `received` · `converting` · `conversion_unavailable` · `conversion_failed` ·
    #: `processing` · `processed` · `error`. The last three are the voice platform's own
    #: words, deliberately not paraphrased.
    ingest_status: str
    #: A sentence to show the client when something went wrong. Never a key or a stack.
    ingest_detail: str | None = None
    #: `pending_approval` · `approved` · `rejected` · `archived` — `kb_sources.status`.
    review_state: str
    is_live: bool
    version: int
    filename: str | None = None
    byte_size: int | None = None
    source_url: str | None = None
    #: `parsed` when a deterministic reader took the text out of the file, `ocr` when a
    #: model read it off a photograph, `None` when there was nothing to read (a PDF, a
    #: link). It is on the CLIENT's screen deliberately: text a machine guessed at is
    #: labelled as such where the person confirming it can see the label.
    text_provenance: str | None = None
    #: When a re-scrape last found this link's page materially changed. A NEW version is
    #: submitted when that happens: published like the link itself when a member linked
    #: the page, for review when an operator did.
    change_detected_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LinkIn(Strict):
    agent_id: UUID | None = Field(default=None, deprecated=True, description=_AGENT_ID_DEPRECATED)
    #: Optional: the host and last path segment are used when it is absent.
    name: str | None = Field(default=None, min_length=2, max_length=120)
    #: BOUNDED because it is STORED (D-302), and 2048 is this repo's URL ceiling — the
    #: same number `SubmitIn.uri` carries, for the same reason.
    url: str = Field(min_length=8, max_length=2048)


class DownloadOut(Strict):
    """A short-lived link to the client's own file, for the person reviewing it."""

    url: str
    expires_in_s: int


@router.post(
    "/uploads",
    response_model=UploadOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Upload a document, spreadsheet or photograph as knowledge",
    description=(
        "Accepts a PDF, a Word document, plain text, a CSV, a spreadsheet or a photograph "
        "of a printed page, up to 20 MB. A PDF is sent to the voice platform as it is; "
        "everything else has its text read out first and chunked. An account member's "
        "upload is published once it has been read, with no review. Poll "
        "`GET /v1/kb/uploads` for `ingest_status`."
    ),
)
async def upload_document(
    session: Session,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    agent_id: Annotated[
        UUID | None, Form(deprecated=True, description=_AGENT_ID_DEPRECATED)
    ] = None,
    principal: Principal = Depends(requires_kb_curation()),
) -> UploadOut:
    assert principal.tenant_id is not None
    del agent_id
    data = await _read_bounded(file)
    result = await uploads.create_upload(
        session,
        tenant_id=principal.tenant_id,
        name=name,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
        submitted_by=principal.user_id,
        # D-658. WHEN it takes effect is `create_upload`'s to decide: a PDF is approved the
        # moment it lands because the file is the document, while text not yet read out
        # cannot be approved, so that promotion waits for the ingest job.
        auto_approve=goes_live_without_review(
            realm=principal.realm, impersonating=principal.impersonating
        ),
    )
    return UploadOut.model_validate(result)


async def _read_bounded(file: UploadFile) -> bytes:
    """The upload body, or a 413 — read in chunks and STOPPED at the ceiling.

    **`await file.read()` IS THE BUG THIS FUNCTION EXISTS TO NOT HAVE.** It reads whatever
    was sent, so the amount of memory one request spends is chosen by whoever sent it, and
    on an ASGI server that is every tenant's process rather than only the uploader's. The
    proxy in front caps a body at 25 MB (`infra/nginx/calevate.conf.template`), which is a
    second control and not this one: the app must hold on its own, because a deployment
    without that proxy is a deployment somebody will make.

    Starlette spools an `UploadFile` to disk past 1 MB, so what this bounds is the read
    ITSELF — one chunk at a time, stopping one byte over the ceiling, which is enough to
    know the file is too large without ever holding it.

    The refusal is `assert_within_limit`'s, so the client reads the SAME sentence whether
    the size was known from the header or discovered while reading.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > uploads.MAX_UPLOAD_BYTES:
            # Stop reading and refuse: the remaining body is not worth the memory, and the
            # answer cannot change.
            uploads.assert_within_limit(total)
        chunks.append(chunk)
    uploads.assert_within_limit(total)
    return b"".join(chunks)


#: One read of the spooled upload. 1 MiB is Starlette's own spool threshold, so this is the
#: size at which its buffer stops being in memory anyway.
_READ_CHUNK_BYTES = 1024 * 1024


@router.post(
    "/links",
    response_model=UploadOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Add a web page as knowledge",
    description=(
        "An account member's link is published once it is registered, with no review. "
        "We re-read the page on a schedule; when it changes materially the new version "
        "is published the same way, because the account linked the page and its updates "
        "are the account's. A page an operator linked is re-submitted for review instead."
    ),
)
async def add_link(
    payload: LinkIn,
    session: Session,
    principal: Principal = Depends(requires_kb_curation()),
) -> UploadOut:
    assert principal.tenant_id is not None
    result = await uploads.create_link(
        session,
        tenant_id=principal.tenant_id,
        name=payload.name,
        url=payload.url,
        submitted_by=principal.user_id,
        auto_approve=goes_live_without_review(
            realm=principal.realm, impersonating=principal.impersonating
        ),
    )
    return UploadOut.model_validate(result)


@router.get(
    "/uploads",
    response_model=list[UploadOut],
    openapi_extra=permission_meta("agents:read"),
    summary="Every document and link, with its live status",
)
async def list_uploads(
    session: Session,
    agent_id: UUID | None = Query(None, deprecated=True, description=_AGENT_ID_DEPRECATED),
    # Bounded (D-302): a client mints one of these per document they upload and nothing
    # prunes them, so the length is caller-controlled — `list_sources`' ceiling and number.
    limit: int = Query(uploads.MAX_UPLOADS_PAGE, ge=1, le=uploads.MAX_UPLOADS_PAGE),
    _: Principal = Depends(requires("agents:read")),
) -> list[UploadOut]:
    del agent_id
    return [
        UploadOut.model_validate(row) for row in await uploads.list_uploads(session, limit=limit)
    ]


@router.get(
    "/uploads/{upload_id}",
    response_model=UploadOut,
    openapi_extra=permission_meta("agents:read"),
    summary="One document or link",
)
async def read_upload(
    upload_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> UploadOut:
    return UploadOut.model_validate(await uploads.get_upload(session, upload_id))


@router.get(
    "/uploads/{upload_id}/original",
    response_model=DownloadOut,
    openapi_extra=permission_meta("agents:read"),
    summary="A short-lived link to the uploaded file",
    description=(
        "For a PDF the file itself is what the agent is handed; there are no chunks to "
        "preview and none are invented."
    ),
)
async def download_original(
    upload_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> DownloadOut:
    from apps.workers.storage import PRESIGN_TTL_S

    return DownloadOut(
        url=await uploads.original_download(session, upload_id), expires_in_s=PRESIGN_TTL_S
    )


@router.post(
    "/uploads/{upload_id}/confirm",
    response_model=UploadOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Approve an upload that is waiting for review, and publish it",
    description=(
        "The account's own approval of a version nobody in the account added: a "
        "view-as session's upload, or a changed page an operator linked. What an account "
        "member uploads or links is approved on its own and never needs this."
    ),
)
async def confirm_upload(
    upload_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> UploadOut:
    assert principal.tenant_id is not None
    result = await uploads.confirm_upload(
        session,
        tenant_id=principal.tenant_id,
        upload_id=upload_id,
        principal=principal,
    )
    await write_audit(
        session,
        action="kb.approved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(result["source_id"]),
        ip=client_request_ip(request),
        # Ids and the two states. Never the document, its name or its text (hard rule 6).
        summary={"upload_id": str(upload_id), "self_approved": True},
    )
    return UploadOut.model_validate(result)


@router.delete(
    "/uploads/{upload_id}",
    status_code=204,
    openapi_extra=permission_meta("kb:write"),
    summary="Remove a document or link from every agent, and delete it",
    description=(
        "Withdraws the copy the voice platform holds before deleting anything of ours, so "
        "neither side is left holding knowledge the other cannot see."
    ),
)
async def delete_upload(
    upload_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> None:
    assert principal.tenant_id is not None
    source_id = (await uploads.get_upload(session, upload_id))["source_id"]
    await uploads.remove_upload(session, tenant_id=principal.tenant_id, upload_id=upload_id)
    await write_audit(
        session,
        action="kb.removed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_source",
        object_id=str(source_id),
        ip=client_request_ip(request),
        summary={"upload_id": str(upload_id)},
    )


# --- Did it reach the phone: the one surface onto the in-call knowledge pack -------
#
# WHY THIS IS A READ ON THE KB ROUTER AND NOT ON `/v1/agents`. It answers a question about
# KNOWLEDGE — "is what I published what my agent is answering out of" — and the object it
# reports on is built, stored and pointed at entirely by this package. An agent's roster
# row is the join key, not the subject. A reader who wants to know what happens to a
# publish after the review queue finds the whole story under one prefix.


class AgentDeliveryOut(Strict):
    """One agent, and whether its knowledge is live on the phone.

    Nothing here is caller-derived (hard rule 6): counts of the CLIENT's own approved
    chunks, the digest of their own text, and one timestamp. `kb/delivery.py` states the
    full argument, including why no call row is joined.
    """

    agent_id: UUID
    agent_name: str
    #: `kb/delivery.DeliveryState`, restated as a Literal so the generated TypeScript client
    #: carries the union and the console cannot render a fifth state it invented. The two
    #: spellings are pinned together by `tests/kb_delivery_test.py`.
    state: Literal["no_knowledge", "live", "preparing", "not_delivered"]
    #: The pack the agent is answering out of, or None if none was ever recorded. Shown so
    #: a client stuck on `not_delivered` has something exact to quote to support.
    pack_id: str | None
    live_chunks: int
    awaiting_translation: int
    #: When this agent started answering out of `pack_id`. NOT "when publish was last
    #: pressed" — a republish of unchanged knowledge moves neither the pointer nor this
    #: (`kb/pack._RECORD_PACK_SQL`). None for a pack recorded before migration f4b18c7d2e59.
    last_reached_at: datetime | None


class DeliveryListOut(Strict):
    """A declared model rather than a bare list, for `StaffCurationOut`'s reason and one
    more: `not_delivered_count` is the server's own tally, so the dashboard badge is never
    computed from a page the ceiling truncated."""

    items: list[AgentDeliveryOut]
    not_delivered_count: int


@router.get(
    "/delivery",
    response_model=DeliveryListOut,
    # `agents:read`, the permission the two reads above settled on and for the same reason:
    # this reports what an agent KNOWS, which is an agent read and not a knowledge write. It
    # stays open under impersonation (D-22), which is deliberate — "my agent doesn't know
    # that" is a support conversation, and an operator answering it needs to see the same
    # screen the client is looking at rather than ask them to read a digest aloud.
    openapi_extra=permission_meta("agents:read"),
    summary="Whether each agent's published knowledge has reached the phone",
    description=(
        "For every agent on the roster: whether the knowledge this account published is "
        "the knowledge the agent is actually answering callers out of, and when it last "
        "changed. `preparing` heals itself within the hour; `not_delivered` does not and "
        "means the agent is still answering out of its previous knowledge."
    ),
)
async def list_delivery(
    session: Session, principal: Principal = Depends(requires("agents:read"))
) -> DeliveryListOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolved it
    rows = await delivery.tenant_delivery(session, tenant_id=principal.tenant_id)
    return DeliveryListOut(
        # Field by field rather than `**vars(row)`: `AgentDelivery` is a slots dataclass
        # (no `__dict__`), and spelling the mapping out is what makes mypy check that the
        # wire model and the read agree rather than trusting two field lists to match.
        items=[
            AgentDeliveryOut(
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                state=row.state,
                pack_id=row.pack_id,
                live_chunks=row.live_chunks,
                awaiting_translation=row.awaiting_translation,
                last_reached_at=row.last_reached_at,
            )
            for row in rows
        ],
        not_delivered_count=sum(1 for row in rows if row.state == "not_delivered"),
    )


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
        "with the `staff` role add knowledge (text, documents, links) and dismiss or "
        "teach a knowledge gap — and nothing else. What they add goes to the agent "
        "without review, exactly as the owner's does (D-658)."
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
