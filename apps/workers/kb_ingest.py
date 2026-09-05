"""From an uploaded file or a link to knowledge an agent can answer from (D-534).

**THIS IS THE ONLY PLACE THE THREE LANES MEET.** The API stores the bytes and mints a
`kb_sources` version (`apps/api/kb/uploads.py`); the conversion lane turns a document into
TEXT (`calevate_shared.document_ingest`, `apps/workers/document_text.py`,
`apps/workers/document_ocr.py`); and `kb/service.publish_source` puts an approved version
on the engine. This module is the sequence between them, and it runs in a worker for one
unavoidable reason: attaching a knowledge base is an upload plus an indexing wait the
vendor gives no bound for, budgeted at three minutes by the adapter. A request handler
cannot hold that open, so the client's screen polls `ingest_status` instead.

═══ THE SEQUENCE, AND WHY EACH STEP IS WHERE IT IS ═══

    read the row → extract text (unless PDF or link) → chunk it → approve, if the
    submitter could → publish, if it is approved → record what happened

* **Extraction is skipped for a PDF and a link.** A PDF's bytes ARE the document the
  engine is handed and a link is scraped by the engine itself, so there is nothing to read
  out; what a reviewer approves is the artefact.
* **Approval comes after extraction, never before.** Nobody can approve text that does not
  exist yet, and for a photograph that is the whole product decision:
  `ExtractedText.needs_confirmation` is True for anything a model read, so OCR text is
  ALWAYS reviewed — by the owner, on the confirmation screen — whoever uploaded it.
* **Publishing is last and is idempotent.** `publish_source` holds the agent's publish
  lock, refuses a source that is not approved, and skips the vendor upload entirely when
  the digest and the handle both match. So a retry of this job costs a lock and a read.

═══ EVERY FAILURE LANDS ON THE ROW, IN A SENTENCE A SHOP OWNER CAN READ ═══

The conversion lane's refusals already carry `title` / `detail` / `remediation` written for
a client; this module copies the last two onto `kb_uploads.ingest_detail` and shows them.
An exception with no such sentence gets a generic one and an ERROR log — never a status
that says everything is fine, and never a client-facing string built from an exception.

═══ WHAT IS METERED ═══

OCR is a model call on our credential, so it writes a `usage_events` row in the same
transaction as the text it produced (hard rule 7, and `kb_gloss.py`'s argument verbatim).
A provider that returns no usage block is NOT estimated: it alerts.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import httpx
from calevate_shared.document_ingest import (
    MAX_SOURCE_BYTES,
    DocumentRefusedError,
    ExtractedText,
    OcrUnavailableError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.crm.assist import ASSIST_FEATURE_KB_OCR
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations.egress_guard import EgressRefusedError, assert_public_http_url
from apps.api.kb import service as kb_service
from apps.api.kb.models import (
    UPLOAD_CONVERSION_FAILED,
    UPLOAD_CONVERSION_UNAVAILABLE,
    UPLOAD_CONVERTING,
    UPLOAD_ERROR,
    UPLOAD_PROCESSED,
    UPLOAD_PROCESSING,
    UPLOAD_RECEIVED,
)
from apps.workers.document_ocr import OcrImage, ocr_images
from apps.workers.document_text import extract_document
from apps.workers.storage import read_kb_object

log = get_logger(__name__)

#: How often the sweep runs. Both of its jobs are patient: a link that changed an hour ago
#: is not an incident, and an ingest that stalled is waiting on an operator or on a vendor.
SWEEP_MINUTES: Final = {7, 37}

#: How long a link may go unread before the sweep re-reads it. A day, because the pages
#: this feature is for — a menu, a price list, an opening-hours page — change on the scale
#: of weeks, and every read is a request to somebody else's server made on their behalf.
RESCRAPE_AFTER = timedelta(days=1)

#: How many links one tick will read. The COST bound of the sweep, in somebody else's
#: bandwidth as much as in our worker slots (`kb_gloss.MAX_CHUNKS_PER_TICK`'s argument).
MAX_LINKS_PER_TICK: Final = 50

#: How long an unfinished ingest may sit before the sweep pushes it again. Longer than any
#: single publish can take (the adapter's own budget is three minutes plus its throttle
#: ladder), so the sweep cannot race a job that is still working.
RETRY_STALLED_AFTER = timedelta(minutes=30)

#: The most rows one tick will re-drive.
MAX_RETRIES_PER_TICK: Final = 25

#: One page fetch: the deadline, the redirect budget and the byte ceiling.
#:
#: THE BYTES ARE THE ONE THAT MATTERS, and `storage.MAX_RECORDING_BYTES` is the precedent:
#: the address is a THIRD PARTY'S, so an unbounded body is a worker's memory chosen by
#: somebody else. 2 MB of HTML is a very large page; the digest only needs enough of it to
#: notice a change.
LINK_FETCH_TIMEOUT_S: Final = 15.0
LINK_REDIRECT_LIMIT: Final = 3
MAX_LINK_BYTES: Final = 2 * 1024 * 1024

#: ONE deadline over the WHOLE fetch — every hop, every lookup and every byte.
#:
#: `LINK_FETCH_TIMEOUT_S` above is httpx's, and httpx's timeout is PER OPERATION: a server
#: that sends one byte every fourteen seconds trips no read timeout and holds the worker
#: for as long as it likes, and a redirect chain multiplies that by the hop budget. Same
#: argument, same shape and the same precedent as `storage.RECORDING_FETCH_DEADLINE_S`;
#: the number is the hop budget times the per-operation timeout, so an honest slow page
#: still finishes and a drip does not.
LINK_FETCH_DEADLINE_S: Final = LINK_FETCH_TIMEOUT_S * (LINK_REDIRECT_LIMIT + 1)

#: What we hash to decide "has this page materially changed". Tags, scripts and styles are
#: removed and whitespace collapsed, so a re-render, a rotated CSRF token in a form or a
#: changed asset hash does not read as new knowledge — those move on every request and
#: would make the sweep submit a new version daily for review, which trains a client to
#: approve without reading.
#:
#: **IT IS A CHANGE SIGNAL AND NOT THE KNOWLEDGE.** What the agent answers from is what the
#: ENGINE scrapes, on its own clock; this reading never reaches a vendor and is never shown
#: as the client's content. It exists to answer one question: is this page still the page
#: they approved?
_SCRIPT_STYLE = re.compile(rb"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(rb"<[^>]+>")
_WHITESPACE = re.compile(rb"\s+")


def page_digest(body: bytes) -> str:
    """A stable digest of a page's visible text. See `_SCRIPT_STYLE` for what it ignores."""
    stripped = _TAGS.sub(b" ", _SCRIPT_STYLE.sub(b" ", body))
    return hashlib.sha256(_WHITESPACE.sub(b" ", stripped).strip().lower()).hexdigest()


_ROW_SQL = """
SELECT u.id, u.source_kind, u.original_key, u.content_type, u.ingest_status,
       u.original_sha256, s.status
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
WHERE u.source_id = :sid
"""


#: The one statement that moves a row's status. LITERAL, with the two provenance columns
#: written through `COALESCE` so a caller that has nothing to say about them leaves them
#: alone — an f-string assembling a SET list from a caller's keys is what
#: `tests/raw_sql_guard_test.py` refuses, and correctly: SQL whose text no reader can trace
#: to a literal is SQL nobody can review.
_MARK_SQL = """
UPDATE kb_uploads
   SET ingest_status = :status,
       ingest_detail = :detail,
       text_provenance = COALESCE(:provenance, text_provenance),
       extractor = COALESCE(:extractor, extractor),
       updated_at = now()
 WHERE id = :id
"""


async def _mark(
    session: AsyncSession,
    upload_id: UUID,
    status: str,
    *,
    detail: str | None = None,
    provenance: str | None = None,
    extractor: str | None = None,
) -> None:
    """The one writer of `ingest_status`, and of the two columns that travel with it.

    A single statement rather than a read-modify-write: the sweep and the job can both
    reach one row, and neither needs to know what the other last wrote.
    """
    await session.execute(
        text(_MARK_SQL),
        {
            "id": upload_id,
            "status": status,
            "detail": detail,
            "provenance": provenance,
            "extractor": extractor,
        },
    )


async def _extract(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    upload_id: UUID,
    kind: str,
    key: str,
    content_type: str | None,
    expected_sha256: str | None,
) -> ExtractedText | None:
    """Read the client's document into text, or leave a refusal on the row and answer None.

    THE OBJECT IS READ ONCE AND NEVER LOGGED. A missing object is a refusal rather than a
    retry: the row names a key nothing answers for, and no amount of waiting produces one.
    """
    data = await read_kb_object(key)
    if not data:
        log.error("kb_ingest_object_missing", extra={"upload_id": str(upload_id)})
        await _mark(
            session,
            upload_id,
            UPLOAD_CONVERSION_FAILED,
            detail="We can no longer find that file. Upload it again.",
        )
        return None
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
        # The bytes in the store are not the bytes the client uploaded. It is not a
        # refusal — what we read is what a reviewer will read and what the agent will
        # answer from — but an object that moved under a row that recorded it is something
        # an operator must be able to see afterwards.
        log.warning("kb_ingest_digest_moved", extra={"upload_id": str(upload_id)})
    if len(data) > MAX_SOURCE_BYTES:
        # Belt and braces with the door's own ceiling: the two numbers are the same today
        # and the reader owns its own bound (`document_ingest.MAX_SOURCE_BYTES`).
        await _mark(
            session,
            upload_id,
            UPLOAD_CONVERSION_FAILED,
            detail="That file is larger than we can read. Split it into smaller documents.",
        )
        return None

    try:
        if kind == "image":
            extracted = await ocr_images(
                [
                    OcrImage(
                        data=data,
                        mime_type=(content_type or "image/jpeg"),
                        position=1,
                    )
                ]
            )
        else:
            extracted = extract_document(data, kind)  # type: ignore[arg-type]
    except OcrUnavailableError as unavailable:
        # An OPERATOR fixes this, not a retry and not the client: no model leg is
        # configured for reading photographs on this deployment. The status says so, and
        # `UPLOAD_RETRYABLE` deliberately excludes it so the sweep does not ask for ever.
        log.error("kb_ingest_ocr_unavailable", extra={"reason": unavailable.reason})
        await _mark(
            session,
            upload_id,
            UPLOAD_CONVERSION_UNAVAILABLE,
            detail=f"{unavailable.detail} {unavailable.remediation}",
        )
        return None
    except DocumentRefusedError as refused:
        # The lane's own sentence, written for a shop owner, copied verbatim. Its `code`
        # goes to the log so an operator can count the shapes; the prose goes to the client.
        log.info("kb_ingest_refused", extra={"upload_id": str(upload_id), "code": refused.code})
        await _mark(
            session,
            upload_id,
            UPLOAD_CONVERSION_FAILED,
            detail=f"{refused.detail} {refused.remediation}",
        )
        return None

    if extracted.model is not None:
        await _meter_ocr(session, tenant_id=tenant_id, extracted=extracted)
    return extracted


async def _meter_ocr(session: AsyncSession, *, tenant_id: UUID, extracted: ExtractedText) -> None:
    """Hard rule 7, in the SAME transaction as the text the call produced.

    `kb_gloss._gloss_one`'s ending, verbatim in shape and for its reason: a model call that
    spent our credential is recorded, and a provider that declined to count tokens is the
    one state D-140 refuses to invent a number for — so it alerts instead of estimating
    from the length of the text.
    """
    if extracted.prompt_tokens is None or extracted.output_tokens is None:
        alert(
            "CORE_LOGIC",
            "kb_ocr_unmeterable",
            detail=(
                "A knowledge photograph was read by a model and the provider returned no "
                "usage block, so the spend could not be metered: it is invisible to the "
                "tenant's AI ceiling and to the platform brake. Nothing was estimated."
            ),
            tenant_id=str(tenant_id),
        )
        return
    await record_ai_assist_usage(
        session,
        tenant_id=tenant_id,
        ref=new_assist_ref(),
        tokens_in=extracted.prompt_tokens,
        tokens_out=extracted.output_tokens,
        model=str(extracted.model),
        feature=ASSIST_FEATURE_KB_OCR,
    )


async def ingest_kb_source(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Convert, approve and publish ONE knowledge source. Returns a short outcome string.

    Enqueued through the outbox by `kb/uploads.py` (so the job and the row share a
    transaction) and again by the sweep for a row that stalled. It is idempotent at every
    step: extraction is skipped when chunks already exist, approval is a CAS, and the
    publish's own re-upload guard makes a repeat a lock and a read.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    source_id = UUID(str(payload["source_id"]))
    may_self_approve = bool(payload.get("may_self_approve"))

    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_ROW_SQL), {"sid": source_id})).first()
        if row is None:
            # Deleted between the enqueue and now — a client can withdraw an upload. Not a
            # failure: there is nothing left to do and nothing to report.
            log.info("kb_ingest_source_gone", extra={"source_id": str(source_id)})
            return "gone"
        upload_id = UUID(str(row[0]))
        kind, key, content_type = str(row[1]), row[2], row[3]
        status, expected_sha256 = str(row[4]), row[5]
        review_state = str(row[6])

        if kind not in ("pdf", "url") and status in (UPLOAD_RECEIVED, UPLOAD_CONVERTING):
            await _mark(session, upload_id, UPLOAD_CONVERTING)
            extracted = await _extract(
                session,
                tenant_id=tenant_id,
                upload_id=upload_id,
                kind=kind,
                key=str(key),
                content_type=content_type,
                expected_sha256=expected_sha256,
            )
            if extracted is None:
                return "refused"
            try:
                chunks = await kb_service.store_extracted_text(
                    session, tenant_id=tenant_id, source_id=source_id, body=extracted.text
                )
            except ProblemError as refusal:
                # The knowledge gate's own refusal (invisible characters, empty text). Its
                # `detail` is already client-facing prose; its `remediation` names the fix.
                await _mark(
                    session,
                    upload_id,
                    UPLOAD_CONVERSION_FAILED,
                    detail=f"{refusal.detail} {refusal.remediation or ''}".strip(),
                )
                return "refused"
            await _mark(
                session,
                upload_id,
                UPLOAD_RECEIVED,
                provenance=extracted.provenance,
                extractor=extracted.model or "parsed",
            )
            log.info(
                "kb_ingest_extracted",
                extra={
                    "upload_id": str(upload_id),
                    "kind": kind,
                    "provenance": extracted.provenance,
                    "chunks": chunks,
                    "discarded": len(extracted.discarded),
                },
            )
            # OCR IS NEVER AUTO-APPROVED, whoever uploaded it. A model told us what it
            # thought a photograph said; a person has to agree before an agent recites it
            # on a phone call. `needs_confirmation` is the conversion lane's own field and
            # it is READ here rather than re-derived from the provenance.
            if may_self_approve and not extracted.needs_confirmation:
                await kb_service.approve_source(session, source_id=source_id, approved_by=None)
                review_state = "approved"

        if review_state not in ("approved", "archived"):
            # Waiting for a human. Not an error and not a retry: the row sits at
            # `received`, the client's screen says what it is waiting for, and the confirm
            # route enqueues this job again.
            return "awaiting_review"

        await _mark(session, upload_id, UPLOAD_PROCESSING)

    # THE PUBLISH IS ITS OWN TRANSACTION AND ITS OWN SESSION, deliberately. It takes the
    # agent's publish lock and makes vendor calls that can run for minutes; holding the
    # extraction's transaction open across them would pin a connection and a lock for the
    # whole of it, and a rollback would then also discard the extracted chunks — throwing
    # away a model call we have already paid for because the vendor was slow.
    async with tenant_session(tenant_id) as session:
        try:
            version = await kb_service.publish_source(
                session, tenant_id=tenant_id, source_id=source_id
            )
        except ProblemError as failure:
            # Every publish refusal is already written for a person and carries a
            # remediation. `agent_not_published` is the common one and is not an error the
            # client caused: their agent is not live yet, so there is nowhere to put the
            # knowledge. It stays retryable — the sweep re-drives it — because publishing
            # the agent is exactly the action that makes it succeed.
            await _fail(
                tenant_id,
                upload_id,
                code=failure.code,
                detail=f"{failure.detail} {failure.remediation or ''}".strip(),
                retryable=failure.code == "agent_not_published",
            )
            return f"failed:{failure.code}"
        except Exception as failure:
            log.exception("kb_ingest_publish_failed", extra={"source_id": str(source_id)})
            await _fail(
                tenant_id,
                upload_id,
                code=type(failure).__name__,
                detail=("We could not send that to the voice platform. We will try again shortly."),
                retryable=True,
            )
            return "failed"

    async with tenant_session(tenant_id) as session:
        await _mark(session, upload_id, UPLOAD_PROCESSED)
    log.info("kb_ingest_published", extra={"source_id": str(source_id), "version": version})
    return f"published:v{version}"


async def _fail(
    tenant_id: UUID, upload_id: UUID, *, code: str, detail: str, retryable: bool
) -> None:
    """Record a failure on the row in a session of its own.

    ITS OWN TRANSACTION, because the one it is reporting has just rolled back: writing the
    reason into the session that failed writes it into the rollback. `retryable` chooses
    between a status the sweep will pick up again (`processing`) and one it will not
    (`error`) — the difference between "the vendor was busy" and "this cannot work".
    """
    async with tenant_session(tenant_id) as session:
        await _mark(
            session,
            upload_id,
            UPLOAD_PROCESSING if retryable else UPLOAD_ERROR,
            detail=detail,
        )
    log.warning(
        "kb_ingest_failed",
        extra={"upload_id": str(upload_id), "code": code, "retryable": retryable},
    )


# --- The sweep: stalled ingests, and links whose page moved --------------------------


_DUE_LINKS_SQL = """
SELECT u.id, u.tenant_id, u.source_id, u.agent_id, u.source_url, u.content_digest, s.name
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
WHERE u.source_kind = 'url' AND s.is_active = true
  AND (u.last_checked_at IS NULL OR u.last_checked_at < :due)
ORDER BY u.last_checked_at NULLS FIRST
LIMIT :limit
"""

_STALLED_SQL = """
SELECT u.tenant_id, u.source_id
FROM kb_uploads u
WHERE u.ingest_status = ANY(:statuses) AND u.updated_at < :stale
ORDER BY u.updated_at
LIMIT :limit
"""


async def sweep_kb_uploads(ctx: dict[str, Any]) -> str:
    """Re-drive ingests that stalled, and re-read links whose page may have moved.

    **ONE SWEEP FOR TWO JOBS, and they are the same job seen twice**: both walk
    `kb_uploads` on a timer asking "does this row still reflect reality". A second cron
    would be a second registration, a second alarm story and a second place to forget the
    tenant loop.

    ═══ WHY A SWEEP AND NOT ONLY AN ENQUEUE (`kb_gloss.py`'s argument) ═══

    A cron that selects the rows still owed work is SELF-HEALING in a way an enqueue is
    not: a lost job, a worker restart mid-publish, an agent that was not live when the
    upload landed and is live now, and a row written by a path nobody has invented yet all
    converge on the next tick with no reconciliation code.

    ═══ WHAT A CHANGED LINK DOES, AND WHAT IT DELIBERATELY DOES NOT DO ═══

    It submits a NEW VERSION of the same named source, `pending_approval`, and stops. It
    does not touch the live version, does not detach anything and does not publish. So the
    agent keeps answering from the page a human approved until a human approves the new
    one — and when they do, `publish_source` attaches the new vendor object BEFORE
    withdrawing the old one, which is why the rollover has no gap and why the old
    knowledge base is deleted at the vendor rather than orphaned.

    It is also reversible in the ordinary way: the superseded version is archived, not
    deleted, so FLOWS §7's rollback is a publish of the older row.
    """
    now = datetime.now(UTC)
    redriven = 0
    async with untenanted_session() as session:
        stalled = (
            await session.execute(
                text(_STALLED_SQL),
                {
                    "statuses": list(_RETRYABLE),
                    "stale": now - RETRY_STALLED_AFTER,
                    "limit": MAX_RETRIES_PER_TICK,
                },
            )
        ).all()
        due = (
            await session.execute(
                text(_DUE_LINKS_SQL),
                {"due": now - RESCRAPE_AFTER, "limit": MAX_LINKS_PER_TICK},
            )
        ).all()

    for tenant_id, source_id in stalled:
        # Through the JOB, not by calling the body: one path into ingestion, so a retry
        # cannot take a shortcut the first attempt did not.
        await ingest_kb_source(
            ctx,
            {
                "tenant_id": str(tenant_id),
                "source_id": str(source_id),
                # A re-drive NEVER approves anything. The approval decision belonged to the
                # request that made the upload; a sweep has no submitter and no authority.
                "may_self_approve": False,
            },
        )
        redriven += 1

    changed = 0
    for row in due:
        if await _recheck_link(
            upload_id=UUID(str(row[0])),
            tenant_id=UUID(str(row[1])),
            agent_id=UUID(str(row[3])),
            url=str(row[4]),
            known_digest=row[5],
            name=str(row[6]),
        ):
            changed += 1

    log.info(
        "kb_upload_sweep",
        extra={"redriven": redriven, "links": len(due), "changed": changed},
    )
    return f"redriven={redriven} links={len(due)} changed={changed}"


#: The statuses the sweep re-drives. `kb/models.UPLOAD_RETRYABLE`, imported rather than
#: spelled, so a status that stops being retryable stops being swept in the same edit.
_RETRYABLE: Final = (UPLOAD_RECEIVED, UPLOAD_CONVERTING, UPLOAD_PROCESSING)


async def _recheck_link(
    *,
    upload_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    url: str,
    known_digest: str | None,
    name: str,
) -> bool:
    """Read one page, and submit a new version for review if it has materially changed.

    **THE SSRF GATE RUNS HERE, NOT ONLY AT SUBMISSION, AND THAT IS THE POINT OF RUNNING IT
    TWICE.** The name belongs to whoever typed it, so a host that answered publicly when
    the link was added can answer `169.254.169.254` today — a time-of-check/time-of-use
    hole rather than a filter hole, which is exactly what `integrations/egress_guard.py`
    exists to narrow and what its docstring's CVE list is about. Redirects are followed by
    hand for the same reason: each hop is a NEW destination and is vetted before it is
    opened.
    """
    fetched = await fetch_page(url)
    async with tenant_session(tenant_id) as session:
        if fetched is None:
            # A page we could not read proves nothing about whether it changed. The clock
            # still moves so one unreachable host cannot monopolise every tick.
            await session.execute(
                text("UPDATE kb_uploads SET last_checked_at = now() WHERE id = :id"),
                {"id": upload_id},
            )
            return False
        digest = page_digest(fetched)
        await session.execute(
            text("UPDATE kb_uploads SET last_checked_at = now() WHERE id = :id"),
            {"id": upload_id},
        )
        if known_digest is None:
            # The FIRST reading of this page: it is the baseline, not a change. Nothing is
            # submitted for review and nothing is flagged.
            await session.execute(
                text("UPDATE kb_uploads SET content_digest = :d WHERE id = :id"),
                {"id": upload_id, "d": digest},
            )
            return False
        if digest == known_digest:
            return False

        source_id, version, _ = await kb_service.insert_source_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            kind="url",
            uri=url[:2048],
            # NOBODY submitted this, so nobody is recorded as having submitted it, and it
            # is never auto-approved: a page that changed under a client is precisely the
            # thing a human must read before their agent starts saying it.
            submitted_by=None,
            auto_approve=False,
        )
        await session.execute(
            text(
                "INSERT INTO kb_uploads (id, tenant_id, agent_id, source_id, source_kind, "
                "source_url, ingest_status, content_digest, last_checked_at, created_at, "
                "updated_at) VALUES (gen_random_uuid(), :tid, :aid, :sid, 'url', :url, "
                ":status, :digest, now(), now(), now())"
            ),
            {
                "tid": tenant_id,
                "aid": agent_id,
                "sid": source_id,
                "url": url[:2048],
                "status": UPLOAD_RECEIVED,
                "digest": digest,
            },
        )
        # The flag the client's screen shows against the LIVE row: "this page has changed,
        # there is a new version waiting for you".
        await session.execute(
            text("UPDATE kb_uploads SET change_detected_at = now() WHERE id = :id"),
            {"id": upload_id},
        )
    log.info(
        "kb_link_changed",
        extra={"upload_id": str(upload_id), "source_id": str(source_id), "version": version},
    )
    return True


def link_http_client() -> httpx.AsyncClient:
    """THE SEAM. The client one page fetch is made with, as a module-level function.

    A function rather than an inlined constructor for `egress_guard.resolve_addresses`'
    reason exactly: the properties worth testing here — the byte ceiling, the hop budget,
    the deadline — cannot be provoked against a real server in a unit test, and a test that
    substituted `httpx.AsyncClient` globally would also be substituting it for the guard's
    own transport check. Nothing else about the fetch moves with it: every judgement in
    `_fetch_page` is still made there.

    `follow_redirects=False` is NOT a detail this seam may lose. A vetted address is vetted
    for the hop we make, so the `Location` is followed by hand and re-vetted — the same
    rule `integrations.service.deliver` and `storage._fetch_recording` state.
    """
    return httpx.AsyncClient(timeout=LINK_FETCH_TIMEOUT_S, follow_redirects=False)


async def _fetch_page(url: str) -> bytes | None:
    """One page, vetted at every hop and bounded in time and bytes. None if unreadable.

    NEVER RAISES ON A REMOTE FAILURE. A client's link pointing at a host that is down must
    not fail a sweep that has forty-nine other tenants' rows to walk.

    STREAMED, AND THE CAP IS CHECKED AS THE BYTES ARRIVE. This read `response.content` and
    then sliced it to `MAX_LINK_BYTES`, which is not a limit: by the time the number is
    known the memory is already spent, and the number is chosen by whoever the CLIENT
    pointed us at. `storage._fetch_recording` had the identical defect and the identical
    fix, and this is that idiom rather than a second one. `Content-Length` is consulted
    first so an honest oversized page costs no bytes at all, but it is a HINT — a chunked
    response declares none and a hostile one can lie — so the running total is what
    enforces the ceiling.

    A page that is LARGER than the ceiling is refused outright rather than truncated. A
    prefix of a document is a different document: `page_digest` over it would report a
    change whenever anything before the cut moved and silence when everything after it
    did, so a truncated read is a change signal that lies in both directions.
    """
    current = url
    async with link_http_client() as client:
        for _hop in range(LINK_REDIRECT_LIMIT + 1):
            try:
                vetted = await assert_public_http_url(current, field="url")
            except EgressRefusedError:
                # Logged by the guard itself, with the category. Nothing further to say
                # here and deliberately nothing about the address in this line.
                log.warning("kb_link_egress_refused")
                return None
            try:
                # `vetted.url`, not `current`: what was judged is what is requested.
                async with client.stream(
                    "GET", vetted.url, headers={"Accept": "text/html,text/*"}
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = str(httpx.URL(vetted.url).join(location))
                        continue
                    if response.status_code >= 400:
                        log.info("kb_link_fetch_status", extra={"status": response.status_code})
                        return None
                    declared = response.headers.get("content-length")
                    if (
                        declared is not None
                        and declared.isdigit()
                        and int(declared) > MAX_LINK_BYTES
                    ):
                        log.info("kb_link_too_large", extra={"declared": int(declared)})
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_LINK_BYTES:
                            log.info("kb_link_too_large", extra={"declared": None})
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.HTTPError as failure:
                log.info("kb_link_fetch_failed", extra={"reason": type(failure).__name__})
                return None
    log.info("kb_link_redirect_limit")
    return None


async def fetch_page(url: str) -> bytes | None:
    """`_fetch_page` under ONE deadline covering the whole chain. The only caller's door.

    Separate from `_fetch_page` so the deadline wraps hops, lookups and bytes together
    rather than each hop separately — a bound a redirect chain walks straight past.
    """
    try:
        async with asyncio.timeout(LINK_FETCH_DEADLINE_S):
            return await _fetch_page(url)
    except TimeoutError:
        log.info("kb_link_fetch_deadline")
        return None


__all__ = [
    "MAX_LINKS_PER_TICK",
    "RESCRAPE_AFTER",
    "RETRY_STALLED_AFTER",
    "SWEEP_MINUTES",
    "fetch_page",
    "ingest_kb_source",
    "link_http_client",
    "page_digest",
    "sweep_kb_uploads",
]
