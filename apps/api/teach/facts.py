"""The business's facts: the searched ones and the pinned ones (founder decision 9).

A fact is a row in `kb_facts`, shared by every agent (D-689).

* An UNPINNED fact is searched. Every change rewrites ONE knowledge source,
  `FACTS_SOURCE_NAME`, as a new version through `kb.service.submit_source`, so the facts
  reach every agent by the ordinary publish path (approval, fan-out, supersession) and the
  engine holds one document of facts rather than one per fact. One source per fact was
  rejected: each source is a separate vendor document on every agent, and thirty one-line
  facts would be thirty documents per agent to re-index.
* A PINNED fact is in every agent's instructions and wins over anything searched
  (`teach/pinned.py`). It is not in the knowledge source too: one place per fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.kb import service as kb
from apps.api.teach import pinned as pinned_store
from apps.api.teach.models import MAX_FACT_CHARS

#: The knowledge source every unpinned fact compiles into.
FACTS_SOURCE_NAME: Final = "Facts you taught"

#: The facts source's text once every unpinned fact has gone.
NO_FACTS_BODY: Final = "There are no short facts on file for this business at the moment."

#: The most facts one account keeps. A list longer than this belongs in a document.
MAX_FACTS: Final = 300

FactsState = Literal["none", "live", "publishing", "in_review"]


@dataclass(frozen=True, slots=True)
class Fact:
    id: UUID
    text: str
    question: str | None
    pinned: bool
    origin: str
    created_at: datetime


def clean_fact(value: str) -> str:
    """One line, trimmed, within the limit for a searched fact."""
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ProblemError.business_rule("fact_empty", "Write the fact before saving it.")
    if len(cleaned) > MAX_FACT_CHARS:
        raise ProblemError.business_rule(
            "fact_too_long",
            f"A fact is at most {MAX_FACT_CHARS} characters.",
            remediation="Split it into two facts, or add it as a document under Files.",
        )
    return cleaned


async def list_facts(session: AsyncSession, *, pinned: bool | None = None) -> list[Fact]:
    """Live facts: pinned first in their order, then the rest in the order they were taught."""
    clause = "" if pinned is None else ("AND pinned" if pinned else "AND NOT pinned")
    rows = (
        await session.execute(
            text(
                "SELECT id, text, question, pinned, origin, created_at FROM kb_facts "
                f"WHERE removed_at IS NULL {clause} "
                "ORDER BY pinned DESC, position NULLS LAST, created_at, id LIMIT :limit"
            ),
            {"limit": MAX_FACTS},
        )
    ).all()
    return [
        Fact(id=r[0], text=r[1], question=r[2], pinned=bool(r[3]), origin=r[4], created_at=r[5])
        for r in rows
    ]


async def facts_state(session: AsyncSession) -> FactsState:
    """Whether the newest version of the facts source has reached the agents."""
    row = (
        await session.execute(
            text(
                "SELECT status, is_active FROM kb_sources WHERE name = :name "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"name": FACTS_SOURCE_NAME},
        )
    ).first()
    if row is None or row[0] in ("rejected", "archived"):
        return "none"
    if row[1]:
        return "live"
    return "in_review" if row[0] == "pending_approval" else "publishing"


async def _lock_facts(session: AsyncSession, tenant_id: UUID) -> None:
    # Two saves at once would each compile the list they read, and the later version would
    # drop the other's fact. One transaction-scoped lock per tenant serialises them.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"kb:facts:{tenant_id}"},
    )


async def _republish(
    session: AsyncSession, *, tenant_id: UUID, submitted_by: UUID | None, auto_approve: bool
) -> None:
    """Compile every live unpinned fact into the next version of the facts source.

    With none left, the next version says so rather than the source being withdrawn. A
    withdrawal is not ordered against a publish still in the queue, so an earlier version
    could go live after it and bring removed facts back; versions are ordered by
    `publish_unless_superseded`, so the newest always wins.
    """
    facts = await list_facts(session, pinned=False)
    # A blank line between facts: `chunk_text` splits on it first, so a fact is never cut.
    body = "\n\n".join(fact.text for fact in facts) if facts else NO_FACTS_BODY
    await kb.submit_source(
        session,
        tenant_id=tenant_id,
        name=FACTS_SOURCE_NAME,
        body=body,
        submitted_by=submitted_by,
        auto_approve=auto_approve,
    )


async def add_facts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    texts: list[str],
    origin: str,
    teaching_id: UUID | None,
    created_by: UUID | None,
    auto_approve: bool,
) -> list[UUID]:
    """Add searched facts and publish the new list. Exact repeats of a live fact are skipped."""
    cleaned = [clean_fact(t) for t in texts]
    if not cleaned:
        return []
    await _lock_facts(session, tenant_id)
    existing = {fact.text.casefold() for fact in await list_facts(session)}
    if len(existing) + len(cleaned) > MAX_FACTS:
        raise ProblemError.business_rule(
            "facts_full",
            f"Your agents already know {len(existing)} facts, and the limit is {MAX_FACTS}.",
            remediation="Remove facts that are out of date, or add a document under Files.",
        )
    ids: list[UUID] = []
    for value in cleaned:
        if value.casefold() in existing:
            continue
        existing.add(value.casefold())
        fact_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO kb_facts (id, tenant_id, text, origin, teaching_id, created_by, "
                "created_at, updated_at) VALUES (:id, :tid, :text, :origin, :teaching, :by, "
                "now(), now())"
            ),
            {
                "id": fact_id,
                "tid": tenant_id,
                "text": value,
                "origin": origin,
                "teaching": teaching_id,
                "by": created_by,
            },
        )
        ids.append(fact_id)
    if ids:
        await _republish(
            session, tenant_id=tenant_id, submitted_by=created_by, auto_approve=auto_approve
        )
    return ids


async def _fact(session: AsyncSession, fact_id: UUID) -> Fact:
    row = (
        await session.execute(
            text(
                "SELECT id, text, question, pinned, origin, created_at FROM kb_facts "
                "WHERE id = :id AND removed_at IS NULL"
            ),
            {"id": fact_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Fact")
    return Fact(
        id=row[0],
        text=row[1],
        question=row[2],
        pinned=bool(row[3]),
        origin=row[4],
        created_at=row[5],
    )


async def _after_change(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    searched: bool,
    pinned: bool,
    by: UUID | None,
    auto_approve: bool,
) -> None:
    if searched:
        await _republish(session, tenant_id=tenant_id, submitted_by=by, auto_approve=auto_approve)
    if pinned:
        await pinned_store.request_recompile(session, tenant_id=tenant_id)


async def update_fact(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    fact_id: UUID,
    text_value: str | None,
    question: str | None,
    pinned: bool | None,
    edited_by: UUID | None,
    auto_approve: bool,
) -> Fact:
    """Change a fact's wording, its question, or whether it is pinned.

    Pinning moves it out of the searched source into every agent's instructions; unpinning
    moves it back. A pinned fact keeps a question and may run to the old quick-fact length;
    a searched fact is one short line.
    """
    await _lock_facts(session, tenant_id)
    current = await _fact(session, fact_id)
    to_pinned = current.pinned if pinned is None else pinned
    answer = current.text if text_value is None else text_value
    asked = current.question if question is None else question
    if to_pinned:
        q, a = pinned_store.clean_pinned(asked, answer)
        await pinned_store.assert_room(session, adding=[(q or "", a)], replacing=fact_id)
    else:
        q, a = None, clean_fact(answer)
    position_sql = ""
    if to_pinned and not current.pinned:
        position_sql = (
            ", position = (SELECT COALESCE(max(position), 0) + 1 FROM kb_facts "
            "WHERE pinned AND removed_at IS NULL)"
        )
    await session.execute(
        text(
            f"UPDATE kb_facts SET text = :text, question = :q, pinned = :pinned{position_sql}, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": fact_id, "text": a, "q": q, "pinned": to_pinned},
    )
    await _after_change(
        session,
        tenant_id=tenant_id,
        searched=not current.pinned or not to_pinned,
        pinned=current.pinned or to_pinned,
        by=edited_by,
        auto_approve=auto_approve,
    )
    return await _fact(session, fact_id)


async def remove_fact(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    fact_id: UUID,
    removed_by: UUID | None,
    auto_approve: bool,
) -> None:
    await _lock_facts(session, tenant_id)
    current = await _fact(session, fact_id)
    await session.execute(
        text("UPDATE kb_facts SET removed_at = now(), updated_at = now() WHERE id = :id"),
        {"id": fact_id},
    )
    await _after_change(
        session,
        tenant_id=tenant_id,
        searched=not current.pinned,
        pinned=current.pinned,
        by=removed_by,
        auto_approve=auto_approve,
    )


__all__ = [
    "FACTS_SOURCE_NAME",
    "MAX_FACTS",
    "NO_FACTS_BODY",
    "Fact",
    "FactsState",
    "add_facts",
    "clean_fact",
    "facts_state",
    "list_facts",
    "remove_fact",
    "update_fact",
]
