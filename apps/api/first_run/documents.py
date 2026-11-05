"""The documents a new owner adds on the brief step, read through the knowledge base (D-918).

A first-run document IS a knowledge upload: the screen sends it to `POST /v1/kb/uploads`, so
its formats, size limit, review, OCR metering and permission are the knowledge base's, and it
becomes part of what every agent knows (D-689). This module only reads what the knowledge
pipeline already holds about each one: how far its reading got, whether its words reach the
agents on calls (`kb.service.upload_reaches_agents`), and the words themselves
(`kb_documents`, the chunks `store_extracted_text` and `store_read_copy` write).

Nothing here redacts: the words leave this module only for `workers/first_run`, which redacts
them before any model sees them (D-127 G-1/G-2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.kb.models import READ_FAILED
from apps.api.kb.service import upload_reaches_agents
from apps.api.kb.structured_text import with_title

DocumentState = Literal["reading", "read", "failed"]

#: The knowledge pipeline's resting failures: nothing further will read these
#: (`kb/store._STUCK`, the same three).
_UNREADABLE: Final = ("conversion_unavailable", "conversion_failed", "error")

_DOCUMENTS_SQL: Final = """
SELECT u.id, s.name, u.source_kind, u.ingest_status, u.ingest_detail, u.read_state,
       u.read_detail, s.status,
       (EXISTS (SELECT 1 FROM kb_documents d WHERE d.source_id = u.source_id)
        OR u.call_instructions IS NOT NULL) AS has_words
FROM kb_uploads u JOIN kb_sources s ON s.id = u.source_id
WHERE u.id = ANY(CAST(:ids AS uuid[]))
"""


@dataclass(frozen=True, slots=True)
class Document:
    upload_id: UUID
    name: str
    #: `kb_uploads.source_kind`: `pdf`, `docx`, `txt`, `csv`, `xlsx`, `image`.
    source_kind: str
    state: DocumentState
    #: The knowledge pipeline's own sentence when it could not be read, for the owner.
    detail: str | None
    #: Whether its words reach the agents on calls today (`upload_reaches_agents`). False for
    #: a PDF whose words could not be read.
    reaches_agents: bool


def state_of(
    *, has_words: bool, ingest_status: str, read_state: str | None, review: str
) -> DocumentState:
    """Read once words are stored for it, whatever else is still moving (a publish to the
    voice platform, a review): the writers need the words, nothing more. Failed when the
    pipeline has stopped without any."""
    if has_words:
        return "read"
    if ingest_status in _UNREADABLE or read_state == READ_FAILED or review == "rejected":
        return "failed"
    return "reading"


async def read_documents(session: AsyncSession, ids: Sequence[UUID]) -> list[Document]:
    """This run's documents in the order added; an id whose upload is gone is left out."""
    if not ids:
        return []
    rows = (await session.execute(text(_DOCUMENTS_SQL), {"ids": [str(i) for i in ids]})).all()
    found: dict[UUID, Document] = {}
    for row in rows:
        state = state_of(
            has_words=bool(row.has_words),
            ingest_status=str(row.ingest_status),
            read_state=row.read_state,
            review=str(row.status),
        )
        found[row.id] = Document(
            upload_id=row.id,
            name=str(row.name),
            source_kind=str(row.source_kind),
            state=state,
            detail=(row.read_detail or row.ingest_detail) if state == "failed" else None,
            reaches_agents=upload_reaches_agents(
                source_kind=str(row.source_kind), read_state=row.read_state
            ),
        )
    return [found[i] for i in ids if i in found]


#: Leads the instructions a guide gives the agent, after its facts, so a script writer reads
#: them as how to run the call rather than as more facts to tell callers.
INSTRUCTIONS_LEAD: Final = "How the agent should handle the call:"


async def document_words(session: AsyncSession, upload_id: UUID) -> str:
    """Every stored chunk of one upload, in reading order, unredacted, then the call
    instructions read out of it (`kb_uploads.call_instructions`): kept off the knowledge the
    agents search, and exactly what a script is written from."""
    rows = await session.execute(
        text(
            "SELECT d.content FROM kb_documents d JOIN kb_uploads u ON u.source_id = d.source_id "
            "WHERE u.id = :uid ORDER BY d.idx"
        ),
        {"uid": upload_id},
    )
    parts = [str(r[0]) for r in rows.all()]
    held = (
        await session.execute(
            text("SELECT call_instructions FROM kb_uploads WHERE id = :uid"), {"uid": upload_id}
        )
    ).scalar()
    lines = [
        with_title(str(item.get("section") or "") or None, [str(item.get("text") or "")])
        for item in held or []
        if isinstance(item, dict) and item.get("text")
    ]
    if lines:
        parts.append("\n\n".join([INSTRUCTIONS_LEAD, *lines]))
    return "\n\n".join(parts)


__all__ = ["Document", "DocumentState", "document_words", "read_documents", "state_of"]
