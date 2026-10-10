"""Pinned facts: the business's quick facts, in every agent's instructions (founder decision 9).

A pinned fact is a `kb_facts` row with `pinned = true`. It belongs to the client (D-689), so
every agent carries the same list, spliced into its compiled body as the `[QUICK FACTS]`
section (`calevate_shared.call_script.splice_quick_facts`). Searched knowledge can miss; a
pinned fact cannot, which is why it is in the instructions and not in the knowledge source.

The script no longer owns quick facts: a save that still carries some (a builder from before
this change, or an AI draft) moves them here first (`absorb_script_facts`), so nothing typed
is lost.

A change re-splices every agent in a worker (`RECOMPILE_JOB`): a new prompt version, applied
and re-published on a live agent unless a script edit is staged, exactly as a knowledge
recompile (`agents/t0.recompile_t0`). The instructions box on ThinnestAI holds 8,000
characters and publish refuses more (`engine_prompt_too_long`), so the pinned list has its
own ceiling, `MAX_PINNED_CHARS`, well inside the room a typical agent leaves the owner
(`tests/agent_prompt_budget_test.py` keeps at least 1,800 free).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from calevate_shared.call_script import FaqEntry, quick_fact_lines, splice_quick_facts
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.api.teach.models import MAX_PINNED_ANSWER_CHARS, MAX_PINNED_QUESTION_CHARS

log = get_logger(__name__)

#: The worker job that re-splices every agent (`apps/workers/pinned_facts.JOB_NAME`).
RECOMPILE_JOB: Final = "recompile_pinned_facts"

#: The whole pinned section, in characters, as it is compiled. A ceiling an addition may not
#: cross; a list already over it (a migrated script) can still be edited down.
MAX_PINNED_CHARS: Final = 1500

_NOTES: Final = "Quick facts updated from the business's pinned facts"


@dataclass(frozen=True, slots=True)
class PinnedFact:
    id: UUID
    question: str | None
    answer: str


async def list_pinned(session: AsyncSession) -> list[PinnedFact]:
    rows = (
        await session.execute(
            text(
                "SELECT id, question, text FROM kb_facts WHERE pinned AND removed_at IS NULL "
                "ORDER BY position NULLS LAST, created_at, id"
            )
        )
    ).all()
    return [PinnedFact(id=r[0], question=r[1], answer=r[2]) for r in rows]


def pairs_of(facts: Sequence[PinnedFact]) -> list[tuple[str, str]]:
    return [(fact.question or "", fact.answer) for fact in facts]


def section_chars(pairs: Sequence[tuple[str, str]]) -> int:
    return len(quick_fact_lines(pairs))


async def assert_room(
    session: AsyncSession, *, adding: Sequence[tuple[str, str]] = (), replacing: UUID | None = None
) -> None:
    """Refuse a change that would grow the pinned section past `MAX_PINNED_CHARS`."""
    current = [f for f in await list_pinned(session) if f.id != replacing]
    before = section_chars(pairs_of(await list_pinned(session)))
    after = section_chars([*pairs_of(current), *adding])
    if after > MAX_PINNED_CHARS and after > before:
        raise ProblemError.business_rule(
            "pinned_facts_full",
            f"Pinned facts are read on every call, so they are kept under "
            f"{MAX_PINNED_CHARS:,} characters. This would make them {after:,}.",
            remediation=(
                "Shorten or unpin a fact. Facts that are not pinned are still found when a "
                "caller asks."
            ),
        )


def clean_pinned(question: str | None, answer: str) -> tuple[str | None, str]:
    q = " ".join((question or "").split()) or None
    a = answer.strip()
    if not a:
        raise ProblemError.business_rule("fact_empty", "Write the fact before saving it.")
    if len(a) > MAX_PINNED_ANSWER_CHARS or (q and len(q) > MAX_PINNED_QUESTION_CHARS):
        raise ProblemError.business_rule(
            "fact_too_long",
            f"A pinned answer is at most {MAX_PINNED_ANSWER_CHARS:,} characters and its "
            f"question at most {MAX_PINNED_QUESTION_CHARS}.",
        )
    return q, a


async def _next_position(session: AsyncSession) -> int:
    value = (
        await session.execute(
            text(
                "SELECT COALESCE(max(position), 0) FROM kb_facts "
                "WHERE pinned AND removed_at IS NULL"
            )
        )
    ).scalar()
    return int(value or 0) + 1


async def request_recompile(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Queue the re-splice of every agent, in the caller's transaction."""
    await enqueue_outbox(session, job=RECOMPILE_JOB, payload={"tenant_id": str(tenant_id)})


async def add_pinned(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    question: str | None,
    answer: str,
    origin: str,
    created_by: UUID | None,
    teaching_id: UUID | None = None,
) -> UUID:
    q, a = clean_pinned(question, answer)
    await _lock(session, tenant_id)
    await assert_room(session, adding=[(q or "", a)])
    fact_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO kb_facts (id, tenant_id, question, text, pinned, origin, position, "
            "teaching_id, created_by, created_at, updated_at) VALUES (:id, :tid, :q, :a, true, "
            ":origin, :pos, :teaching, :by, now(), now())"
        ),
        {
            "id": fact_id,
            "tid": tenant_id,
            "q": q,
            "a": a,
            "origin": origin,
            "pos": await _next_position(session),
            "teaching": teaching_id,
            "by": created_by,
        },
    )
    await request_recompile(session, tenant_id=tenant_id)
    return fact_id


async def _lock(session: AsyncSession, tenant_id: UUID) -> None:
    # The same key `teach/facts` takes: one writer at a time on the business's facts.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"kb:facts:{tenant_id}"},
    )


async def reorder(session: AsyncSession, *, tenant_id: UUID, ids: Sequence[UUID]) -> None:
    """Put the pinned facts in this order. Every pinned fact must be named once."""
    await _lock(session, tenant_id)
    current = {fact.id for fact in await list_pinned(session)}
    if set(ids) != current or len(ids) != len(current):
        raise ProblemError.conflict(
            "pinned_facts_changed",
            "The pinned facts changed while you were ordering them.",
            remediation="Reload the list and order it again.",
        )
    for position, fact_id in enumerate(ids, 1):
        await session.execute(
            text("UPDATE kb_facts SET position = :pos, updated_at = now() WHERE id = :id"),
            {"pos": position, "id": fact_id},
        )
    await request_recompile(session, tenant_id=tenant_id)


async def absorb_script_facts(
    session: AsyncSession, *, tenant_id: UUID, faqs: Sequence[FaqEntry], created_by: UUID | None
) -> int:
    """Move quick facts a script save still carries into the pinned facts; answers how many
    were new. Exact repeats (trimmed, case-blind) are not added twice."""
    pairs = [(f.question.strip(), f.answer.strip()) for f in faqs if f.answer.strip()]
    if not pairs:
        return 0
    await _lock(session, tenant_id)
    have = {
        ((fact.question or "").casefold(), fact.answer.casefold())
        for fact in await list_pinned(session)
    }
    added = 0
    for question, answer in pairs:
        key = (question.casefold(), answer.casefold())
        if key in have:
            continue
        have.add(key)
        await session.execute(
            text(
                "INSERT INTO kb_facts (id, tenant_id, question, text, pinned, origin, position, "
                "created_by, created_at, updated_at) VALUES (:id, :tid, :q, :a, true, "
                "'quick_fact', :pos, :by, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "q": question[:MAX_PINNED_QUESTION_CHARS] or None,
                "a": answer[:MAX_PINNED_ANSWER_CHARS],
                "pos": await _next_position(session),
                "by": created_by,
            },
        )
        added += 1
    if added:
        await request_recompile(session, tenant_id=tenant_id)
    return added


async def spliced_body(session: AsyncSession, body: str) -> str:
    """`body` carrying the business's pinned facts as its quick-facts section."""
    return splice_quick_facts(body, pairs_of(await list_pinned(session)))


async def recompile_agent(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> int | None:
    """Re-splice one agent's draft body. Returns the new version, or None if unchanged.

    The `recompile_t0` doctrine: a new immutable version, applied (and re-published on a live
    agent) unless a script edit is staged behind "Put it live", in which case it rides with
    that edit rather than publishing it.
    """
    # Local imports: `agents/` imports `teach/` (script saves splice through here).
    from apps.api.agents.prompts import insert_prompt_version
    from apps.api.agents.service import publish_agent

    row = (
        await session.execute(
            text(
                "SELECT a.status, a.engine_agent_ref, pv.body, pv.compiled_t0_context, "
                "pv.structured_script, (a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
                "FROM agents a JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None or not row[2]:
        return None
    body = await spliced_body(session, row[2])
    if body == row[2]:
        return None
    structured = row[4]
    if isinstance(structured, dict) and structured.get("raw_override") is None:
        # The authored structure no longer holds quick facts; they are the business's now.
        structured = {**structured, "faqs": []}
    elif isinstance(structured, dict):
        structured = None
    staged = bool(row[5])
    version = await insert_prompt_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        body=body,
        notes=_NOTES,
        created_by=None,
        compiled_t0_context=row[3],
        structured_script=structured,
        apply_live=not staged,
    )
    if row[0] == "live" and row[1] and not staged:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "pinned_facts_recompiled",
        extra={"agent_id": str(agent_id), "prompt_version": version, "staged": staged},
    )
    return version


__all__ = [
    "MAX_PINNED_CHARS",
    "RECOMPILE_JOB",
    "PinnedFact",
    "absorb_script_facts",
    "add_pinned",
    "assert_room",
    "clean_pinned",
    "list_pinned",
    "pairs_of",
    "recompile_agent",
    "reorder",
    "request_recompile",
    "section_chars",
    "spliced_body",
]
