"""Uploads and links: the half of the Knowledge screen that was missing (D-532).

`/c/{slug}/knowledge` offered a client a title box and a text box, so a clinic with a
four-page price list in a Word file had to retype it, and a shop whose menu exists only as
a laminated card photographed on a phone had no way in at all. This module is the door for
both, plus the link a client wants their agent to know about.

═══ WHAT IS OURS AND WHAT IS INHERITED ═══

An upload IS a `kb_sources` version. Everything that already governs knowledge governs it
unchanged — the approval gate, the version numbering and rollback (FLOWS §7), the retention
sweep, the vendor-object claim (`engine_kb_routes`, D-519) and the whole of
`publish_source`'s attach-then-detach ordering. This module adds exactly three things:

1. the bytes (`kb_uploads`, object storage, and the 20 MB the vendor's route refuses above);
2. the conversion seam — a Word file, a spreadsheet, plain text or a photograph becomes
   TEXT (`calevate_shared.document_ingest`, implemented by a separate lane), which is then
   chunked, previewed, approved and published by the path pasted knowledge has always
   taken. The PDF is still made by `kb/pdf_render.py` at publish, and a client's PDF is the
   one thing that skips all of it: those bytes ARE the document, and what a reviewer
   approves is the file itself;
3. a per-item status a client can read while the engine indexes asynchronously.

═══ THE FOUR REFUSALS AT THE DOOR, AND WHY THEY ARE AT THE DOOR ═══

* **Too large.** The engine refuses a file over 20 MB, so we refuse it before storing a
  byte, while the client still has the file in front of them. Accepting it and failing in
  a worker would be the same outcome twenty minutes later with nobody watching.
* **A kind nothing can read.** `SUPPORTED_UPLOAD_KINDS` is DERIVED from the conversion
  lane's own `CONVERTIBLE_KINDS`, so the door and the worker cannot disagree about what
  will be accepted — the shape where a client uploads a file the endpoint admits and a
  worker then refuses.
* **A URL we will not fetch.** A client-supplied URL is fetched by US as well as by the
  vendor — we read the page to detect a material change (see `kb_ingest`), and that makes
  it an SSRF surface in the textbook sense. It goes through
  `integrations/egress_guard.assert_public_http_url`, the one gate every outbound fetch in
  this repo already goes through, at submission AND again before each fetch (the guard's
  own docstring explains why once is not enough: the DNS is the client's).
* **Someone else's agent.** `insert_source_version` runs `assert_visible` first, because
  PostgreSQL checks foreign keys with row security BYPASSED and a `kb_sources` row naming
  another tenant's agent would take a slot in `(agent_id, name, version)` that the owning
  tenant could then never use.

═══ WHO IS REVIEWED ═══

The founder's decision, implemented in one place: an OWNER's submission is auto-approved,
a STAFF member's is reviewed. The authority question is answered by `kb/curation.py`, which
already owns it, and this module receives the answer — see `may_self_approve`. A link
re-ingested by the sweep is ALWAYS reviewed: nobody asked for that change, so nobody has
approved it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final
from uuid import UUID

from calevate_shared.document_ingest import CONVERTIBLE_KINDS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.integrations.egress_guard import EgressRefusedError, assert_public_http_url
from apps.api.kb.models import UPLOAD_RECEIVED
from apps.api.kb.pdf_render import MAX_UPLOAD_BYTES
from apps.api.kb.service import insert_source_version, withdraw_source
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

#: The job that converts, publishes and reports back. Named as a module constant because
#: `scripts/check_job_wiring.py` resolves enqueue arguments through exactly these — a job
#: enqueued by a literal is a name that guard cannot follow, and an enqueue whose worker
#: does not answer to it succeeds, DLQs and reports green everywhere.
INGEST_KB_SOURCE_JOB: Final = "ingest_kb_source"

#: The largest list this module will return in one response (D-302). A client mints these
#: rows one per document they upload and nothing prunes them, so the length is
#: caller-controlled — `list_sources`' ceiling, for its reason and with its number.
MAX_UPLOADS_PAGE: Final = 200

#: Filename extension -> our `SourceKind`. The client's `Content-Type` is a HINT and is
#: recorded, never trusted: browsers send `application/octet-stream` for a `.docx` as often
#: as not, and a hostile one can say anything. The extension decides which converter is
#: asked, and the CONVERTER is what actually reads the bytes — so a lie here buys a
#: conversion failure with a sentence attached, not an execution path.
_EXTENSION_KINDS: Final[dict[str, str]] = {
    "pdf": "pdf",
    "docx": "docx",
    "txt": "txt",
    "md": "txt",
    "csv": "csv",
    "xlsx": "xlsx",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "heic": "image",
    "heif": "image",
    "webp": "image",
    "avif": "image",
}

#: What this deployment accepts as a FILE upload: the one kind the engine takes natively
#: plus everything the conversion lane can read. DERIVED, never listed — a reader added
#: there starts being accepted here in the same change.
#:
#: `url` is deliberately absent: a link is not a file upload and has its own route.
SUPPORTED_UPLOAD_KINDS: Final[frozenset[str]] = frozenset({"pdf"}) | CONVERTIBLE_KINDS

#: The formats a person is likely to try that we deliberately do NOT accept, and the
#: reason, so the refusal can say something better than "no". `.doc` and `.odt` are not
#: the OOXML container the reader opens, and `.xls` is the pre-2007 binary workbook — all
#: three are one "Save as" away from a format that works, which is what the message says.
_NEAR_MISS_EXTENSIONS: Final[dict[str, str]] = {
    "doc": "docx",
    "odt": "docx",
    "rtf": "docx",
    "xls": "xlsx",
    "ods": "xlsx",
    "pages": "docx",
    "numbers": "xlsx",
    "gif": "png",
}

#: What a source name may be. The client's filename is the DEFAULT name and a name is
#: shown on a review screen and on the agent's own knowledge list, so it is stripped of
#: path separators and control characters rather than trusted — and it never reaches an
#: object-storage key (`workers/storage.kb_object_key` builds keys from ids alone).
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")

#: What the engine is told a link is called. Not the URL itself: the vendor echoes
#: `file_name` into its own console and a URL can carry a query string with anything in it.
_MAX_NAME = 120


def may_self_approve(principal: Principal) -> bool:
    """Whether THIS submitter's knowledge goes live without a second reader.

    The founder's rule: an owner's submission is auto-approved, a staff member's is
    reviewed. `role_has(role, "kb:write")` is the role table's own answer to "is this
    person the account's principal" and it is asked through `curation.may_curate_knowledge`
    -- no, deliberately NOT through it: that function also answers True for a STAFF member
    in an account whose owner switched staff curation on, which is a grant to SUBMIT and
    explicitly not a grant to approve (`kb/curation.py`, "It does not let them approve or
    publish anything"). Reading it here would silently convert one into the other.

    So the test is the role table alone, plus the two clauses every authority read in this
    repo carries: the client realm (an admin's authority comes from the admin realm's own
    audited surfaces, never from a client-writable row) and D-22 (an impersonating operator
    may not approve anything under a client's name).
    """
    from apps.api.core.rbac import role_has

    if principal.realm != "client" or principal.impersonating:
        return False
    return role_has(principal.role or "", "kb:write")


def classify_upload(*, filename: str, content_type: str | None) -> str:
    """Which kind this file is, or a 422 naming what we do accept.

    THE EXTENSION DECIDES, and the sniffing alternative was considered and refused. Reading
    magic bytes tells you what a file IS, which sounds stronger and is the wrong question
    HERE: the reader has to open the file anyway and refuses a mislabelled one by name
    (`document_ingest.DocumentUnreadableError`), so sniffing at the door would be a second
    implementation of "what is this" that can disagree with the first. What it would not
    buy is safety — nothing on this path executes, renders or parses the bytes; they are
    stored opaquely and handed to the reader or to the vendor. The kind is a ROUTING
    decision, and the client's own filename is the honest input to it.

    A NEAR MISS GETS A DIFFERENT SENTENCE. `.doc`, `.xls` and `.pages` are the formats a
    shop owner actually has, and "we cannot read that" is a dead end where "save it as
    .docx and upload it again" is a next step (quality bar: errors are part of the
    interface).
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = _EXTENSION_KINDS.get(extension)
    if kind is not None and kind in SUPPORTED_UPLOAD_KINDS:
        return kind
    readable = ", ".join(
        f".{ext}" for ext in sorted(_EXTENSION_KINDS) if _EXTENSION_KINDS[ext] in SUPPORTED_UPLOAD_KINDS
    )
    instead = _NEAR_MISS_EXTENSIONS.get(extension)
    raise ProblemError(
        kind="validation",
        code="kb_upload_kind_unsupported",
        title="We cannot read that kind of file",
        detail=(
            f"We do not read .{extension} files."
            if extension
            else "That file has no extension, so we cannot tell what it is."
        ),
        remediation=(
            f"Open it and save a copy as .{instead}, then upload that."
            if instead
            else f"Upload one of: {readable}. Or paste the wording as text."
        ),
        status=422,
    )


def safe_name(*, given: str | None, fallback: str) -> str:
    """The source name: what the client called it, or their filename, made safe and short.

    Not a key and not a path — see `_UNSAFE_NAME`. Short because it is a column with a
    unique index behind it and a label on two screens.
    """
    raw = (given or fallback).strip()
    cleaned = _UNSAFE_NAME.sub(" ", raw).strip()
    if len(cleaned) < 2:
        raise ProblemError(
            kind="validation",
            code="kb_name_required",
            title="That upload needs a name",
            detail="A knowledge source needs a name of at least two characters.",
            remediation="Give the document a short name, like 'Price list'.",
            status=422,
        )
    return cleaned[:_MAX_NAME]


def assert_within_limit(byte_size: int) -> None:
    """The vendor's own ceiling, refused BEFORE anything is stored or uploaded.

    20 MB is the engine's documented maximum for a knowledge-base file; the number lives
    once, with the renderer that already had to respect it (`kb/pdf_render.MAX_UPLOAD_BYTES`,
    which cites the vendor page). Refusing here rather than at the vendor is the same
    argument the adapter makes about its own copy of this check: a 400 from the vendor goes
    through the throttle ladder as a transient fault and is retried, three times, with the
    same oversized body.
    """
    if byte_size <= 0:
        raise ProblemError(
            kind="validation",
            code="kb_upload_empty",
            title="That file is empty",
            detail="The uploaded file contains no data.",
            remediation="Check the file opens on your device, then upload it again.",
            status=422,
        )
    if byte_size > MAX_UPLOAD_BYTES:
        raise ProblemError(
            kind="validation",
            code="kb_upload_too_large",
            title="That file is too large",
            detail=(
                f"The voice platform accepts documents up to "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB and this one is "
                f"{byte_size // (1024 * 1024)} MB."
            ),
            remediation="Split it into two documents and upload them separately.",
            status=413,
        )


async def create_upload(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str | None,
    filename: str,
    content_type: str | None,
    data: bytes,
    submitted_by: UUID | None,
    auto_approve: bool,
) -> dict[str, Any]:
    """Store one uploaded document and queue its ingestion. Returns the row's public shape.

    ═══ THE ORDER, AND THE ONE RESIDUE IT LEAVES ═══

    The object is written to storage BEFORE the row is committed, because the row has to
    carry the key and the key has to name an object that exists. A transaction that then
    rolls back leaves an object with no row: unreachable, harmless, inside the tenant's own
    `kb-uploads/{tenant}/{upload}/` prefix so an offboarding still sweeps it up. The
    alternative — commit the row, then store — leaves the strictly worse residue: a row a
    client can see, a status that says received, and no bytes behind it.

    ═══ THE ENQUEUE IS AN OUTBOX WRITE ═══

    `enqueue_outbox`, not `enqueue`: the job and the row share a transaction, so there is
    no state in which a client sees an upload that nothing will ever pick up, and none in
    which a worker is handed an id that was rolled back (BACKEND-PATTERNS, reliability
    triad).
    """
    assert_within_limit(len(data))
    kind = classify_upload(filename=filename, content_type=content_type)
    source_name = safe_name(given=name, fallback=filename)

    upload_id = uuid7()
    # Deferred import: boto3 is heavy and this module is on the API's request path
    # (`crm/routes.py` and `integrations/routes.py` do the same for the same reason).
    from apps.workers.storage import kb_object_key, store_kb_object

    key = kb_object_key(
        tenant_id=tenant_id,
        upload_id=upload_id,
        slot="original",
        suffix=filename.rsplit(".", 1)[-1].lower(),
    )
    await store_kb_object(
        key=key, data=data, content_type=content_type or "application/octet-stream"
    )

    source_id, version, status = await insert_source_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=source_name,
        kind="file",
        # The FILENAME, not the key: `kb_sources.uri` is a human-readable provenance field
        # shown on the review screen, and an object-storage key on a screen is a key one
        # copy-paste from being pasted somewhere it should not be.
        uri=filename[:2048],
        submitted_by=submitted_by,
        auto_approve=auto_approve,
    )
    digest = hashlib.sha256(data).hexdigest()
    # A PDF IS the document the engine will be handed, so both slots point at one object
    # and nothing re-renders it: what a reviewer opens is what an agent answers from.
    # Every other kind is read into TEXT by the conversion lane and then chunked, so
    # `document_key` stays NULL for them and `kb/service._publish_payload` renders their
    # approved chunks exactly as it does for pasted knowledge.
    native = kind == "pdf"
    await session.execute(
        text(
            "INSERT INTO kb_uploads (id, tenant_id, agent_id, source_id, source_kind, "
            "original_key, original_filename, original_bytes, original_sha256, "
            "content_type, document_key, document_bytes, document_sha256, ingest_status, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, :sid, :kind, :key, :fname, "
            ":bytes, :sha, :ctype, :dkey, :dbytes, :dsha, :status, now(), now())"
        ),
        {
            "id": upload_id,
            "tid": tenant_id,
            "aid": agent_id,
            "sid": source_id,
            "kind": kind,
            "key": key,
            "fname": filename[:512],
            "bytes": len(data),
            "sha": digest,
            "ctype": (content_type or "")[:255] or None,
            "dkey": key if native else None,
            "dbytes": len(data) if native else None,
            "dsha": digest if native else None,
            "status": UPLOAD_RECEIVED,
        },
    )
    await enqueue_outbox(
        session,
        job=INGEST_KB_SOURCE_JOB,
        payload={"tenant_id": str(tenant_id), "source_id": str(source_id)},
    )
    # Ids, a kind and a byte count. Never the filename (a client's own business data) and
    # never the key (hard rule 6).
    log.info(
        "kb_upload_received",
        extra={
            "upload_id": str(upload_id),
            "source_id": str(source_id),
            "kind": kind,
            "bytes": len(data),
            "auto_approved": auto_approve,
        },
    )
    return {
        "id": upload_id,
        "source_id": source_id,
        "agent_id": agent_id,
        "name": source_name,
        "source_kind": kind,
        "ingest_status": UPLOAD_RECEIVED,
        "ingest_detail": None,
        "review_state": status,
        "is_live": False,
        "version": version,
        "filename": filename[:512],
        "byte_size": len(data),
        "source_url": None,
    }


async def create_link(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str | None,
    url: str,
    submitted_by: UUID | None,
    auto_approve: bool,
) -> dict[str, Any]:
    """Register a web page as knowledge. The ENGINE scrapes it; we only vet and watch it.

    **THE SSRF GATE RUNS HERE AND AGAIN AT EVERY FETCH.** A URL a client types is a URL our
    network will resolve and open, because the re-scrape sweep reads the page to notice a
    material change. `assert_public_http_url` is that gate — the same one every outbound
    delivery in this repo goes through — and calling it twice is not belt-and-braces: the
    DNS behind the name belongs to whoever typed it, so a name that answers publicly today
    can answer `169.254.169.254` at fetch time (the guard's docstring carries the full
    argument and the CVE list).

    What we do NOT do is fetch it now. The submission is a client's decision and must not
    wait on a third-party server; the first read belongs to the ingest job, which has a
    deadline, a size cap and a retry ladder.
    """
    try:
        await assert_public_http_url(url, field="url")
    except EgressRefusedError as refused:
        raise ProblemError(
            kind="validation",
            code="kb_link_refused",
            title="We cannot fetch that address",
            detail=(
                "That web address does not resolve to a public website we are willing to "
                "read."
            ),
            remediation="Check the address and paste the public link to the page.",
            status=422,
        ) from refused

    source_name = safe_name(given=name, fallback=_name_from_url(url))
    source_id, version, status = await insert_source_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=source_name,
        kind="url",
        uri=url[:2048],
        submitted_by=submitted_by,
        auto_approve=auto_approve,
    )
    upload_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_uploads (id, tenant_id, agent_id, source_id, source_kind, "
            "source_url, ingest_status, created_at, updated_at) VALUES (:id, :tid, :aid, "
            ":sid, 'url', :url, :status, now(), now())"
        ),
        {
            "id": upload_id,
            "tid": tenant_id,
            "aid": agent_id,
            "sid": source_id,
            "url": url[:2048],
            "status": UPLOAD_RECEIVED,
        },
    )
    await enqueue_outbox(
        session,
        job=INGEST_KB_SOURCE_JOB,
        payload={"tenant_id": str(tenant_id), "source_id": str(source_id)},
    )
    log.info(
        "kb_link_received",
        extra={
            "upload_id": str(upload_id),
            "source_id": str(source_id),
            "auto_approved": auto_approve,
        },
    )
    return {
        "id": upload_id,
        "source_id": source_id,
        "agent_id": agent_id,
        "name": source_name,
        "source_kind": "url",
        "ingest_status": UPLOAD_RECEIVED,
        "ingest_detail": None,
        "review_state": status,
        "is_live": False,
        "version": version,
        "filename": None,
        "byte_size": None,
        "source_url": url[:2048],
    }


def _name_from_url(url: str) -> str:
    """A readable default name for a link: its host and last path segment.

    The whole URL would be a poor name — query strings, tracking parameters and percent
    escapes are noise on a review screen — and an empty one would fail `safe_name`, so the
    host is always in it.
    """
    without_scheme = url.split("://", 1)[-1]
    host = without_scheme.split("/", 1)[0]
    tail = without_scheme.rstrip("/").rsplit("/", 1)[-1] if "/" in without_scheme else ""
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    return f"{host} {tail}".strip() if tail and tail != host else host


_LIST_SQL = """
SELECT u.id, u.source_id, u.agent_id, s.name, u.source_kind, u.ingest_status,
       u.ingest_detail, s.status, s.is_active, s.version, u.original_filename,
       u.original_bytes, u.source_url, u.change_detected_at, u.created_at, u.updated_at
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
"""


async def list_uploads(
    session: AsyncSession, *, agent_id: UUID | None = None, limit: int = MAX_UPLOADS_PAGE
) -> list[dict[str, Any]]:
    """Every upload and link this tenant has, newest first. RLS does the scoping.

    The JOIN to `kb_sources` is not decoration: the review state, the live flag and the
    NAME live there and are deliberately not duplicated here, so a screen that shows an
    upload shows the same review state the approval queue does.
    """
    clause = "WHERE u.agent_id = :aid " if agent_id else ""
    rows = (
        await session.execute(
            text(f"{_LIST_SQL} {clause}ORDER BY u.created_at DESC LIMIT :limit"),
            {"aid": agent_id, "limit": limit} if agent_id else {"limit": limit},
        )
    ).all()
    return [_row_out(row) for row in rows]


async def get_upload(session: AsyncSession, upload_id: UUID) -> dict[str, Any]:
    """One row, or 404. Absent and invisible are ONE answer, this repo's discriminator
    doctrine: a neighbour's id must not be distinguishable from an id nobody minted."""
    row = (
        await session.execute(text(f"{_LIST_SQL} WHERE u.id = :uid"), {"uid": upload_id})
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge upload")
    return _row_out(row)


def _row_out(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "source_id": row[1],
        "agent_id": row[2],
        "name": row[3],
        "source_kind": row[4],
        "ingest_status": row[5],
        "ingest_detail": row[6],
        "review_state": row[7],
        "is_live": row[8],
        "version": row[9],
        "filename": row[10],
        "byte_size": row[11],
        "source_url": row[12],
        "change_detected_at": row[13],
        "created_at": row[14],
        "updated_at": row[15],
    }


async def original_download(session: AsyncSession, upload_id: UUID) -> str:
    """A short-lived link to the document the client uploaded — how a REVIEWER reads it.

    THE APPROVAL GATE IS A HUMAN READING WHAT THE AGENT WILL BE HANDED, and for typed text
    that is the chunk preview. For a document there are no chunks to preview and inventing
    some would mean parsing the file into a second rendering nobody signed off (see
    `calevate_shared.kb_conversion` on why the converter is not asked for text). So the
    artefact itself is what a reviewer opens, through a presigned URL with the repo's
    five-minute TTL and no public object anywhere.

    A LINK HAS NOTHING TO DOWNLOAD and says so by name rather than by an empty answer.
    """
    row = (
        await session.execute(
            text("SELECT original_key, source_kind FROM kb_uploads WHERE id = :uid"),
            {"uid": upload_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge upload")
    key, kind = row[0], str(row[1])
    if not key:
        raise ProblemError.business_rule(
            "kb_upload_not_a_file",
            "That knowledge source is a web page, not an uploaded file."
            if kind == "url"
            else "That upload has no stored file.",
            remediation="Open the web address itself to review it.",
        )
    from apps.workers.storage import presigned_url

    url = presigned_url(str(key))
    if url is None:
        raise ProblemError(
            kind="dependency",
            code="kb_upload_unavailable",
            title="That document cannot be opened right now",
            detail="The document store did not answer.",
            remediation="Try again in a minute.",
        )
    return url


async def remove_upload(session: AsyncSession, *, tenant_id: UUID, upload_id: UUID) -> None:
    """Take an upload off the agent and delete it, both sides, in that order.

    ═══ WHY THE ORDER IS NOT NEGOTIABLE ═══

    `withdraw_source` runs FIRST and is allowed to fail. It un-references the vendor's copy
    from the agent and deletes it at the vendor, under the same lock a publish takes. Only
    when the engine has confirmed that do our rows go — because the reverse order deletes
    the only record of how the vendor's copy is addressed (`engine_kb_routes.engine_kb_ref`,
    cleared by the detach), leaving a document that still answers a client's callers and
    that nothing of ours can ever find again. That is the orphan `kb/orphans.py` exists to
    report and a human then has to clear by hand.

    ═══ WHAT DELETING OUR ROWS TAKES WITH IT ═══

    The `kb_sources` row, by CASCADE: its chunks, its retrieval projection and this upload
    row. Then the objects, by PREFIX rather than by the two keys we hold — the prefix is
    `kb-uploads/{tenant}/{upload}/`, so a converted document written by a lane that stored
    it under a name this module does not know is removed too. A deletion that removes only
    the keys it remembers is how a client's document survives its own deletion.

    THE OBJECTS GO LAST AND OUTSIDE THE TRANSACTION, which is deliberate: an object store
    has no rollback, so a failure after the DELETE would leave objects with no rows (a
    prefix sweep still reaches them) while a failure before it would leave rows with no
    objects (a client sees a document they cannot open). The first is recoverable and
    invisible; the second is a broken screen.
    """
    row = (
        await session.execute(
            text("SELECT source_id, tenant_id FROM kb_uploads WHERE id = :uid"),
            {"uid": upload_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge upload")
    source_id = UUID(str(row[0]))

    await withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    await session.execute(text("DELETE FROM kb_sources WHERE id = :sid"), {"sid": source_id})

    from apps.workers.storage import delete_objects, kb_upload_prefix, keys_under

    prefix = kb_upload_prefix(tenant_id=tenant_id, upload_id=upload_id)
    removed = await delete_objects(await keys_under(prefix))
    log.info(
        "kb_upload_removed",
        extra={"upload_id": str(upload_id), "source_id": str(source_id), "objects": removed},
    )


__all__ = [
    "INGEST_KB_SOURCE_JOB",
    "MAX_UPLOADS_PAGE",
    "UPLOAD_PROCESSED",
    "assert_within_limit",
    "classify_upload",
    "create_link",
    "create_upload",
    "get_upload",
    "list_uploads",
    "may_self_approve",
    "original_download",
    "remove_upload",
    "safe_name",
]
