"""KB ingestion, approval and publish (FLOWS §7).

    client submits text/url → chunk → PREVIEW → admin approves → version bump →
    engine KB sync → live.   Rollback = reactivate the prior version.

The approval gate is the point. A client editing what their agent says is a client
editing a legal instrument — the agent speaks on their behalf under their PE
registration — so a human sees the chunks before they reach the engine. D-28 keeps
that gate ours no matter which vector provider wins the bake-off.

Chunking is paragraph-aware with a size cap rather than a fixed window: KB answers are
read aloud, and a chunk cut mid-sentence becomes a sentence the agent says badly.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from calevate_shared.engine import KBSourceRef, VoiceEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.engine import get_engine

log = get_logger(__name__)

# ~700 characters is roughly 15-20 seconds of spoken Telugu — long enough to answer a
# question, short enough that retrieval returns one idea rather than a page.
MAX_CHUNK_CHARS = 700
MIN_CHUNK_CHARS = 80


def chunk_text(body: str) -> list[str]:
    """Split on paragraph boundaries, packing up to the cap; only split a paragraph
    that exceeds the cap on its own, and then on sentence ends."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_CHARS:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_split_sentences(paragraph))
            continue
        if len(buffer) + len(paragraph) + 2 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        else:
            chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    # Fold a stub tail into its predecessor: a two-word chunk retrieves noisily.
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_CHARS:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks[-1]}"
        chunks.pop()
    return chunks


def _split_sentences(paragraph: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?।])\s+", paragraph)
    out: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(buffer) + len(sentence) + 1 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer:
                out.append(buffer)
            buffer = sentence[:MAX_CHUNK_CHARS]
    if buffer:
        out.append(buffer)
    return out


async def submit_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    body: str,
    kind: str = "text",
    uri: str | None = None,
    submitted_by: UUID | None = None,
) -> dict[str, Any]:
    """Create the next VERSION of a named source, chunked and awaiting approval.

    Nothing here touches the engine. A submission is a proposal; only `publish_source`
    changes what the agent knows.
    """
    chunks = chunk_text(body)
    if not chunks:
        raise ProblemError(
            kind="validation",
            code="kb_empty",
            title="Nothing to add",
            detail="The submitted content is empty.",
        )

    current = (
        await session.execute(
            text(
                "SELECT COALESCE(max(version), 0) FROM kb_sources "
                "WHERE agent_id = :aid AND name = :name"
            ),
            {"aid": agent_id, "name": name},
        )
    ).scalar()
    version = int(current or 0) + 1

    source_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, uri, status, "
            "version, submitted_by, is_active, created_at, updated_at) VALUES (:id, :tid, "
            ":aid, :kind, :name, :uri, 'pending_approval', :version, :by, false, now(), now())"
        ),
        {
            "id": source_id,
            "tid": tenant_id,
            "aid": agent_id,
            "kind": kind,
            "name": name,
            "uri": uri,
            "version": version,
            "by": submitted_by,
        },
    )
    for idx, chunk in enumerate(chunks):
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, "
                "created_at, updated_at) VALUES (:id, :tid, :sid, :idx, :title, :content, "
                "now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "sid": source_id,
                "idx": idx,
                "title": name,
                "content": chunk,
            },
        )
    return {
        "id": source_id,
        "version": version,
        "chunks": len(chunks),
        "status": "pending_approval",
    }


async def preview(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("SELECT idx, content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
            {"sid": source_id},
        )
    ).all()
    return [{"idx": r[0], "content": r[1], "chars": len(r[1])} for r in rows]


async def approve_source(
    session: AsyncSession, *, source_id: UUID, approved_by: UUID | None
) -> None:
    """CAS on `pending_approval` (BACKEND-PATTERNS §5): approving twice, or approving a
    source someone already rejected, is a lost race and not an update."""
    result = await session.execute(
        text(
            "UPDATE kb_sources SET status = 'approved', approved_by = :by, approved_at = now(), "
            "updated_at = now() WHERE id = :sid AND status = 'pending_approval'"
        ),
        {"sid": source_id, "by": approved_by},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.conflict(
            "kb_not_pending",
            "This knowledge source is not awaiting approval.",
            remediation="Reload — it may have already been approved or rejected.",
        )


async def reject_source(session: AsyncSession, *, source_id: UUID, reason: str) -> None:
    result = await session.execute(
        text(
            "UPDATE kb_sources SET status = 'rejected', rejection_reason = :reason, "
            "updated_at = now() WHERE id = :sid AND status = 'pending_approval'"
        ),
        {"sid": source_id, "reason": reason[:500]},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.conflict("kb_not_pending", "This source is not awaiting approval.")


async def _chunks_of(session: AsyncSession, source_id: UUID) -> list[str]:
    """The approved chunks of one source, in reading order — one engine document."""
    rows = (
        await session.execute(
            text("SELECT content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
            {"sid": source_id},
        )
    ).scalars()
    return [str(chunk) for chunk in rows]


async def _engine_kb_ref(session: AsyncSession, source_id: UUID) -> str | None:
    """The engine's handle for this source's attached copy, or None if nothing of ours
    is attached. See `_remember_engine_kb_ref` for why it lives where it lives."""
    value = (
        await session.execute(
            text(
                "SELECT meta ->> 'engine_kb_ref' FROM kb_documents "
                "WHERE source_id = :sid AND idx = 0"
            ),
            {"sid": source_id},
        )
    ).scalar()
    return str(value) if value else None


async def _remember_engine_kb_ref(
    session: AsyncSession, source_id: UUID, engine_kb_ref: str | None
) -> None:
    """Record (or clear) the engine's handle for a source.

    It lives in `kb_documents.meta` because that is where the migration that created
    these tables put it: "Provider-side document and namespace ids land in
    `kb_documents.meta`, which is also what lets a DPDP erasure prove it removed both
    copies." A source is pushed to the engine as ONE document, so the handle hangs off
    its first chunk. No column is added for it — a new column is a migration, and this
    fix is not worth coupling to one when the designed home already exists.

    Clearing on detach is not tidiness: a handle left behind after the engine copy is
    gone is a handle a later publish would try to delete, and that publish would then
    refuse for a reason that is no longer true.
    """
    if engine_kb_ref is None:
        await session.execute(
            text(
                "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) - 'engine_kb_ref', "
                "updated_at = now() WHERE source_id = :sid AND idx = 0"
            ),
            {"sid": source_id},
        )
        return
    await session.execute(
        text(
            "UPDATE kb_documents SET meta = coalesce(meta, '{}'::jsonb) || "
            "jsonb_build_object('engine_kb_ref', to_jsonb(cast(:ref as text))), "
            "updated_at = now() WHERE source_id = :sid AND idx = 0"
        ),
        {"sid": source_id, "ref": engine_kb_ref},
    )


async def _superseded_versions(
    session: AsyncSession, *, agent_id: UUID, name: str, keep: UUID
) -> list[tuple[UUID, str | None]]:
    """The live versions of this named source that publishing `keep` replaces, each with
    the engine handle we recorded for it. Normally exactly one; a list because "exactly
    one" is an invariant we enforce, not one we may assume while enforcing it."""
    rows = (
        await session.execute(
            text(
                "SELECT id FROM kb_sources WHERE agent_id = :aid AND name = :name "
                "AND is_active = true AND id <> :sid"
            ),
            {"aid": agent_id, "name": name, "sid": keep},
        )
    ).scalars()
    live = [UUID(str(row)) for row in rows]
    return [(source_id, await _engine_kb_ref(session, source_id)) for source_id in live]


async def _detach_superseded(
    session: AsyncSession,
    engine: VoiceEngine,
    engine_ref: str,
    source_id: UUID,
    engine_kb_ref: str | None,
) -> None:
    """Withdraw one superseded version from the engine, or refuse to publish.

    **The decision this function encodes: a detach that fails ABORTS the publish, and
    the previously approved version stays live.** The two alternatives are both worse.
    Continuing anyway is the defect being fixed — two versions attached, the agent free
    to answer from the older one, our tables reporting success. Detaching-and-carrying-on
    in the other direction (drop the old, publish nothing) would leave the client with no
    knowledge at all, which is an outage we caused to avoid an inconsistency.

    Refusing keeps the client whole: their agent still answers, from text a human
    approved. What they lose is the UPDATE, and they are told so, with a retry that
    costs nothing — the engine is idempotent from our side here because we have not
    attached anything yet. `kind` is inherited from the adapter's own error so a rate
    limit stays retryable and a rejection stays not.

    A version we have no handle for is the same refusal for the same reason: we cannot
    remove what we cannot address, so we must not publish over it. (Only versions
    published before this path existed can be in that state; the remediation is to
    withdraw the stale copy on the engine side once, not to weaken this.)
    """
    if engine_kb_ref is None:
        log.warning("kb_engine_ref_unknown", extra={"source_id": str(source_id)})
        raise ProblemError(
            kind="business_rule",
            code="kb_engine_ref_unknown",
            title="The live version cannot be withdrawn",
            detail=(
                "We have no record of how the currently live version is filed on the "
                "voice platform, so it cannot be removed before publishing this one."
            ),
            remediation=(
                "Nothing changed — the live version is still the approved one. "
                "Ask support to withdraw the stale copy on the voice platform first."
            ),
        )
    try:
        await engine.detach_kb(engine_ref, engine_kb_ref)
    except ProblemError as exc:
        log.warning(
            "kb_detach_failed", extra={"source_id": str(source_id), "engine_code": exc.code}
        )
        raise ProblemError(
            kind=exc.kind,
            code="kb_detach_failed",
            title="The previous version could not be withdrawn",
            detail=(
                "The voice platform did not confirm removal of the version this one "
                "replaces, so publishing would leave both live."
            ),
            remediation=(
                "Nothing changed — the previously approved version is still live. "
                "Try publishing again."
            ),
        ) from exc
    await _remember_engine_kb_ref(session, source_id, None)


async def _reattach_after_failed_publish(
    engine: VoiceEngine,
    engine_ref: str,
    name: str,
    detached: list[tuple[UUID, str | None]],
    chunks_of: dict[UUID, list[str]],
) -> None:
    """Close the gap the detach-first ordering opens when the ATTACH then fails.

    At this point the agent holds no copy of this source. The previous version's text is
    still in our tables and is still approved, so putting it back restores a state a
    human signed off on — the client keeps a working knowledge base and loses only the
    update.

    What deliberately is NOT done here: recording the new handle. The caller re-raises,
    the transaction rolls back, and any write here would roll back with it — so our
    tables keep pointing at the handle that was just deleted. That is the intended
    residue: the NEXT publish tries to detach a handle the engine no longer has, and
    refuses loudly (`kb_detach_failed`) instead of quietly stacking two versions. A loud
    stop an operator can clear beats a silent divergence nobody sees.
    """
    for source_id, _ in detached:
        try:
            await engine.attach_kb(
                engine_ref,
                KBSourceRef(
                    kb_id=str(source_id),
                    title=name,
                    text="\n\n".join(chunks_of.get(source_id, [])),
                ),
            )
        except Exception:
            # Nothing left to try: the engine is refusing both directions. Say so at
            # ERROR — this agent now has NO knowledge for this source and only an
            # operator can put it back.
            log.error("kb_left_detached", extra={"source_id": str(source_id)})
        else:
            log.info("kb_restored_after_failed_publish", extra={"source_id": str(source_id)})


async def publish_source(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> int:
    """Push an APPROVED source to the engine KB and make it the active version.

    Order matters, in two directions:

    1. The engine work happens BEFORE the local activation flip. If the engine rejects
       it, nothing in our state claims the agent knows something it does not — the
       opposite order would leave a client's dashboard confidently wrong.
    2. The superseded version is DETACHED before the new one is attached. Archiving a
       row only changes our tables; what the caller hears is what the engine holds. Push
       first and there is a window — or, when the detach never happens at all, a
       permanent state — in which the agent can answer from either version, and a
       rollback leaves every version live at once. A client approved v2; the agent
       quoting v1's prices is the divergence the approval gate exists to prevent.

    That ordering costs a gap: between the detach and the attach the agent has no copy
    of this source and answers "I don't know" (T4 refuse-and-escalate). One request of
    silence is the cheaper failure — a stale price is a quote the client is then held to.

    Eligibility is `approved_at IS NOT NULL`, not `status = 'approved'`, because
    FLOWS §7's rollback is republishing a version this same function ARCHIVED when its
    successor went live. Gating on the current status made that impossible: the archive
    step rewrites `status`, so the recovery path refused the only rows it exists for.
    Approval is a fact about a version that a later publish cannot erase; rejection
    never sets `approved_at`, so a rejected source still cannot reach an agent.
    """
    row = (
        await session.execute(
            text(
                "SELECT s.agent_id, s.name, s.status, s.version, s.approved_at, "
                "a.engine_agent_ref FROM kb_sources s JOIN agents a ON a.id = s.agent_id "
                "WHERE s.id = :sid"
            ),
            {"sid": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge source")
    agent_id, name, status, version, approved_at, engine_ref = row
    if approved_at is None or status not in ("approved", "archived"):
        raise ProblemError.business_rule(
            "kb_not_approved",
            "A knowledge source must be approved before it can go live.",
            remediation="Approve it from the admin console first.",
        )
    if not engine_ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "Publish the agent to the voice platform before adding knowledge.",
        )

    chunks = await _chunks_of(session, source_id)

    engine = get_engine()
    superseded = await _superseded_versions(
        session, agent_id=agent_id, name=str(name), keep=source_id
    )
    # Read the fallback text BEFORE anything is withdrawn: if the attach fails we have to
    # put these versions back, and a query issued after the failure is a query issued on
    # a session that may itself be the thing that failed.
    previous_chunks = {
        previous_id: await _chunks_of(session, previous_id) for previous_id, _ in superseded
    }

    for previous_id, previous_kb_ref in superseded:
        await _detach_superseded(session, engine, engine_ref, previous_id, previous_kb_ref)

    try:
        attached_ref = await engine.attach_kb(
            engine_ref,
            KBSourceRef(kb_id=str(source_id), title=str(name), text="\n\n".join(chunks)),
        )
    except Exception:
        await _reattach_after_failed_publish(
            engine, engine_ref, str(name), superseded, previous_chunks
        )
        raise

    await _remember_engine_kb_ref(session, source_id, attached_ref)

    # Archive the previous active version of this named source, then activate this one.
    # Rollback (FLOWS §7) is re-running publish on the archived row, which is why the
    # activation restores `status` as well as `is_active` — a live version left marked
    # `archived` is a row that contradicts itself on every screen that reads it.
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = false, status = 'archived', updated_at = now() "
            "WHERE agent_id = :aid AND name = :name AND is_active = true AND id <> :sid"
        ),
        {"aid": agent_id, "name": name, "sid": source_id},
    )
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = true, status = 'approved', "
            "published_at = now(), updated_at = now() WHERE id = :sid"
        ),
        {"sid": source_id},
    )
    log.info("kb_published", extra={"source_id": str(source_id), "version": version})
    return int(version)


async def list_sources(session: AsyncSession, *, status: str | None = None) -> list[dict[str, Any]]:
    clause = "WHERE status = :status" if status else ""
    rows = (
        await session.execute(
            text(
                "SELECT id, agent_id, name, kind, status, version, is_active, published_at, "
                "(SELECT count(*) FROM kb_documents d WHERE d.source_id = kb_sources.id) "
                f"FROM kb_sources {clause} ORDER BY updated_at DESC"
            ),
            {"status": status} if status else {},
        )
    ).all()
    return [
        {
            "id": r[0],
            "agent_id": r[1],
            "name": r[2],
            "kind": r[3],
            "status": r[4],
            "version": r[5],
            "is_active": r[6],
            "published_at": r[7],
            "chunks": int(r[8] or 0),
        }
        for r in rows
    ]


__all__ = [
    "MAX_CHUNK_CHARS",
    "approve_source",
    "chunk_text",
    "list_sources",
    "preview",
    "publish_source",
    "reject_source",
    "submit_source",
]
