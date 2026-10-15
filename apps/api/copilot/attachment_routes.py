"""Files a person attaches to Pip (D-781): upload, download, remove — both realms.

THE BODY IS STREAMED, NOT HELD. `POST .../uploads` reads the raw request body chunk by
chunk and hands it to an S3 multipart upload into the private uploads bucket
(`attachments.receive`), with no `Depends(db)`: a pooled connection is not held across a
20 MB upload, so the row is recorded in one short transaction before the stream and settled
in another after it. A raw body rather than `multipart/form-data` because Starlette spools
a multipart file part to a temporary FILE past 1 MB (`kb/routes._read_bounded` notes the
same), and this path writes nothing to local disk.

THE BROWSER NEVER TALKS TO THE STORE. Downloads stream back through `.../content` to the
person who uploaded the file and to nobody else, with the headers `_SERVE_HEADERS` lists.
No URL to the store and no object key leaves this module, in a response or a log line.

THIS PATH HAS ITS OWN BODY LIMIT. `core/middleware.MAX_BODY_BYTES` stays 2 MiB for every
other route; `core/middleware.ROUTE_BODY_LIMITS` names these two POSTs at the file limit,
and nginx gives the same two paths their own `client_max_body_size` and stops buffering
them (`infra/nginx/calevate.conf.template`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Final, Literal
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import attachments, session_run
from apps.api.copilot.consent import require_consent
from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.schemas import CopilotUploadOut
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import storage

router = APIRouter(prefix="/v1/copilot/uploads", tags=["copilot"])
admin_router = APIRouter(prefix="/v1/admin/copilot/uploads", tags=["admin-copilot"])

ClientUser = Annotated[Principal, Depends(requires("copilot:use"))]
AdminUser = Annotated[Principal, Depends(requires("copilot:admin", realm="admin"))]
Session = Annotated[AsyncSession, Depends(db)]
UploadId = Annotated[UUID, Path()]
#: The name the person chose, percent-encoded UTF-8. A header rather than the query
#: string, so a name (which can be a customer's) is not in an access log.
UploadName = Annotated[str, Header(alias="X-Upload-Name", min_length=1, max_length=1024)]
DeclaredType = Annotated[str, Header(alias="Content-Type", max_length=100)]
DeclaredLength = Annotated[int | None, Header(alias="Content-Length", ge=0)]
#: For the text the browser took out of a PDF (D-781): the id of that PDF.
TextOf = Annotated[UUID | None, Header(alias="X-Upload-Text-Of")]

#: Every download carries these. `nosniff` so a browser renders only the stored type;
#: a CSP that allows nothing, so even a text file opened in a tab runs no script and loads
#: nothing; `private, no-store` so no cache keeps a copy.
_SERVE_HEADERS: Final = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
    "Cross-Origin-Resource-Policy": "same-site",
}

_UPLOAD_BODY: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {
            kind: {"schema": {"type": "string", "format": "binary"}}
            for kind in ("image/jpeg", "application/pdf", "text/plain", "text/csv")
        },
    }
}

_UPLOAD = f"""\
Attach one file to {ASSISTANT_NAME}'s next question. The body IS the file — not a form —
with `Content-Type` set to the type the browser produced, and `X-Upload-Name` set to the
name the person chose, percent-encoded.

Allowed: pictures (JPG, PNG, WebP, HEIC — re-drawn by the browser as `image/jpeg`, which
drops their location and camera data), text and CSV (`text/plain`, `text/csv`), and Word,
Excel and PowerPoint files the browser has turned into `text/plain`, and PDFs
(`application/pdf`, sent as they are). Up to 20 MB a file, 5 MB a picture and 14 MB a PDF;
up to 5 files, 2 of them pictures, 50 MB in all and 14 MB of pictures and PDFs together, on
one message. For a PDF the browser also sends the text it found in it, as `text/plain` with
`X-Upload-Text-Of` naming the PDF: Pip reads that only when the PDF itself cannot be read.
Files with macros, older Office formats, ZIPs, audio and anything else are refused with a
sentence saying what to do; so is a body whose first bytes are not what its type says.

When files cannot be stored this answers 503 `copilot_uploads_unavailable`; the
conversation read says so beforehand in `uploads_available`, so a browser never starts
such an upload.

Nothing in the file is opened, scanned or reviewed: it is stored privately and sent to
{ASSISTANT_NAME}'s AI provider as it is. Requires `copilot:use`.\
"""


def _out(upload: attachments.Upload, *, size: int | None = None) -> CopilotUploadOut:
    return CopilotUploadOut(
        id=upload.id,
        file_name=upload.file_name,
        kind=upload.kind,
        content_type=upload.stored_type,
        size_bytes=size if size is not None else upload.size_bytes,
        status="ready",
    )


def _not_signed_in() -> ProblemError:
    return ProblemError(
        kind="auth",
        code="copilot_upload_no_session",
        title="Your session has ended",
        detail="Files belong to the session they were attached in.",
        remediation="Sign in again and attach the file.",
    )


def _owner_of(principal: Principal) -> UUID:
    # Resolved by `requires` on both realms; a principal without one never gets here.
    assert principal.user_id is not None
    return principal.user_id


async def _run(principal: Principal, realm: Literal["client", "admin"]) -> tuple[UUID, datetime]:
    # Resolved by `requires` on both realms; a principal without one never gets here.
    assert principal.user_id is not None
    run = await session_run.current_run_start(realm=realm, subject_id=principal.user_id)
    if run is None:
        raise _not_signed_in()
    return principal.user_id, run


async def _upload(
    request: Request,
    *,
    realm: attachments.Realm,
    session_for: Any,
    owner: UUID,
    tenant_id: UUID | None,
    run: datetime,
    name: str,
    declared_type: str,
    declared_length: int | None,
    text_of: UUID | None,
    on_settled: Callable[[AsyncSession, attachments.Upload, int], Awaitable[None]] | None = None,
) -> CopilotUploadOut:
    """Record, stream, settle. Each transaction is short; none is open during the stream.

    `on_settled` runs inside the settling transaction, so a row it writes (the admin
    realm's audit row) commits with the file being marked ready, or not at all."""
    async with session_for() as session:
        begun = await attachments.begin(
            session,
            realm,
            owner=owner,
            tenant_id=tenant_id,
            run=run,
            file_name=unquote(name),
            declared_type=declared_type,
            declared_length=declared_length,
            text_of=text_of,
        )
    try:
        size = await attachments.receive(begun.upload, request.stream(), budget=begun.budget)
    except BaseException as failure:
        async with session_for() as session:
            await attachments.forget(session, realm, upload_id=begun.upload.id)
        if isinstance(failure, storage.StorageUnavailableError):
            raise attachments.uploads_unavailable() from None
        raise
    async with session_for() as session:
        await attachments.finish(session, realm, upload_id=begun.upload.id, size=size)
        if on_settled is not None:
            await on_settled(session, begun.upload, size)
    return _out(begun.upload, size=size)


async def _serve(upload: attachments.Upload) -> StreamingResponse:
    try:
        chunks = await storage.upload_chunks(upload.object_key)
    except storage.StorageUnavailableError:
        raise attachments.uploads_unavailable() from None
    if chunks is None:
        raise ProblemError(
            kind="not_found",
            code="not_found",
            title="That file is gone",
            detail="It is no longer stored.",
            remediation="Attach it again.",
        )
    # Inline only for a picture, which is only ever stored as JPEG; everything else is a
    # download. The person's own file name is not put in the header (a header is not where
    # their text goes); the browser names the download.
    disposition = "inline" if upload.kind == "picture" else "attachment"
    return StreamingResponse(
        _relay(chunks),
        media_type=upload.stored_type,
        headers={**_SERVE_HEADERS, "Content-Disposition": disposition},
    )


async def _relay(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    async for chunk in chunks:
        yield chunk


# --- the client realm ----------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    response_model=CopilotUploadOut,
    openapi_extra={**permission_meta("copilot:use"), **_UPLOAD_BODY},
    summary=f"Attach a file for {ASSISTANT_NAME} — the body is the file, streamed to storage",
    description=_UPLOAD,
)
async def upload_file(
    request: Request,
    principal: ClientUser,
    name: UploadName,
    content_type: DeclaredType,
    content_length: DeclaredLength = None,
    text_of: TextOf = None,
) -> CopilotUploadOut:
    owner, run = await _run(principal, "client")
    tenant_id = principal.tenant_id
    assert tenant_id is not None

    def session_for() -> Any:
        return tenant_session(tenant_id)

    # Pip is on for this account (D-788), checked before a byte of the body is read.
    async with session_for() as session:
        await require_consent(session, tenant_id=tenant_id)

    return await _upload(
        request,
        realm=attachments.CLIENT,
        session_for=session_for,
        owner=owner,
        tenant_id=tenant_id,
        run=run,
        name=name,
        declared_type=content_type,
        declared_length=content_length,
        text_of=text_of,
    )


@router.get(
    "/{file_id}/content",
    openapi_extra=permission_meta("copilot:use"),
    summary="One of your own attached files, streamed back to you and nobody else",
    response_class=StreamingResponse,
)
async def download_file(
    file_id: UploadId, session: Session, principal: ClientUser
) -> StreamingResponse:
    owner = _owner_of(principal)
    run = await session_run.current_run_start(realm="client", subject_id=owner)
    upload = await attachments.readable(
        session, attachments.CLIENT, owner=owner, upload_id=file_id, run=run
    )
    return await _serve(upload)


@router.delete(
    "/{file_id}",
    status_code=204,
    openapi_extra=permission_meta("copilot:use"),
    summary="Remove an attached file — deleted from storage at once",
)
async def remove_file(file_id: UploadId, session: Session, principal: ClientUser) -> Response:
    owner = _owner_of(principal)
    await attachments.discard(session, attachments.CLIENT, owner=owner, upload_id=file_id)
    return Response(status_code=204)


# --- the admin realm -----------------------------------------------------------------------
#
# `untenanted_session`, for `load_admin_copilot_conversation`'s reason: the admin table
# carries no tenant and no policy, and the `admin_user_id` predicate is the whole scoping.


@admin_router.post(
    "",
    status_code=201,
    response_model=CopilotUploadOut,
    openapi_extra={**permission_meta("copilot:admin"), **_UPLOAD_BODY},
    summary=f"Attach a file for {ASSISTANT_NAME} (admin console)",
    description=_UPLOAD.replace("copilot:use", "copilot:admin"),
)
async def upload_admin_file(
    request: Request,
    principal: AdminUser,
    name: UploadName,
    content_type: DeclaredType,
    content_length: DeclaredLength = None,
    text_of: TextOf = None,
) -> CopilotUploadOut:
    owner, run = await _run(principal, "admin")

    # SEC-COMP §5: every admin-realm mutation leaves a row. Ids, kind and size only; the
    # file's name can be a customer's (hard rule 6).
    async def audit(session: AsyncSession, upload: attachments.Upload, size: int) -> None:
        await write_audit(
            session,
            action="admin_copilot.file_attached",
            actor=principal,
            # An operator's assistant panel belongs to no client, as with the
            # conversation it is attached to.
            tenant_id=None,
            object_type="admin_copilot_upload",
            object_id=str(upload.id),
            ip=client_request_ip(request),
            summary={"kind": upload.kind, "size_bytes": size},
        )

    return await _upload(
        request,
        realm=attachments.ADMIN,
        session_for=untenanted_session,
        owner=owner,
        tenant_id=None,
        run=run,
        name=name,
        declared_type=content_type,
        declared_length=content_length,
        text_of=text_of,
        on_settled=audit,
    )


@admin_router.get(
    "/{file_id}/content",
    openapi_extra=permission_meta("copilot:admin"),
    summary="One of your own attached files (admin console)",
    response_class=StreamingResponse,
)
async def download_admin_file(file_id: UploadId, principal: AdminUser) -> StreamingResponse:
    owner = _owner_of(principal)
    run = await session_run.current_run_start(realm="admin", subject_id=owner)
    async with untenanted_session() as session:
        upload = await attachments.readable(
            session, attachments.ADMIN, owner=owner, upload_id=file_id, run=run
        )
    return await _serve(upload)


@admin_router.delete(
    "/{file_id}",
    status_code=204,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Remove an attached file (admin console)",
)
async def remove_admin_file(file_id: UploadId, principal: AdminUser, request: Request) -> Response:
    owner = _owner_of(principal)
    async with untenanted_session() as session:
        await attachments.discard(session, attachments.ADMIN, owner=owner, upload_id=file_id)
        await write_audit(
            session,
            action="admin_copilot.file_removed",
            actor=principal,
            tenant_id=None,
            object_type="admin_copilot_upload",
            object_id=str(file_id),
            ip=client_request_ip(request),
        )
    return Response(status_code=204)


__all__ = ["admin_router", "router"]
