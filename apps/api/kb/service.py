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

from calevate_shared.engine import KBSourceRef
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


async def publish_source(session: AsyncSession, *, tenant_id: UUID, source_id: UUID) -> int:
    """Push an APPROVED source to the engine KB and make it the active version.

    Order matters: the engine push happens BEFORE the local activation flip. If the
    engine rejects it, nothing in our state claims the agent knows something it does
    not — the opposite order would leave a client's dashboard confidently wrong.
    """
    row = (
        await session.execute(
            text(
                "SELECT s.agent_id, s.name, s.status, s.version, a.engine_agent_ref "
                "FROM kb_sources s JOIN agents a ON a.id = s.agent_id WHERE s.id = :sid"
            ),
            {"sid": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Knowledge source")
    agent_id, name, status, version, engine_ref = row
    if status != "approved":
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

    chunks = (
        (
            await session.execute(
                text("SELECT content FROM kb_documents WHERE source_id = :sid ORDER BY idx"),
                {"sid": source_id},
            )
        )
        .scalars()
        .all()
    )

    await get_engine().attach_kb(
        engine_ref,
        KBSourceRef(kb_id=str(source_id), title=str(name), text="\n\n".join(chunks)),
    )

    # Archive the previous active version of this named source, then activate this one.
    # Rollback (FLOWS §7) is re-running publish on the archived row.
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = false, status = 'archived', updated_at = now() "
            "WHERE agent_id = :aid AND name = :name AND is_active = true AND id <> :sid"
        ),
        {"aid": agent_id, "name": name, "sid": source_id},
    )
    await session.execute(
        text(
            "UPDATE kb_sources SET is_active = true, published_at = now(), updated_at = now() "
            "WHERE id = :sid"
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
