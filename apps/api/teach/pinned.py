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
recompile (`agents/t0.recompile_t0`). The instructions box on ThinnestAI holds 20,000
characters and publish refuses more (`engine_prompt_too_long`), so the pinned list has its
own ceiling, `MAX_PINNED_CHARS` (3,000, founder decision F5, 12 Oct 2026), inside the room a
typical agent leaves the owner (`tests/agent_prompt_budget_test.py`'s `OWNER_RESERVE`).
Pinned facts are re-sent on every reply, so the ceiling also bounds what each turn costs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from calevate_shared.call_script import (
    QUICK_FACTS_HEADER,
    CallScript,
    FaqEntry,
    quick_fact_lines,
    splice_quick_facts,
)
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
MAX_PINNED_CHARS: Final = 3000

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
    session: AsyncSession,
    *,
    adding: Sequence[tuple[str, str]] = (),
    replacing: UUID | None = None,
    tenant_id: UUID | None = None,
) -> None:
    """Refuse a change that would grow the pinned section past `MAX_PINNED_CHARS`, or, given
    `tenant_id`, push a live agent past the calling system's box."""
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
    if tenant_id is not None and after > before:
        await _assert_live_agents_fit(
            session, tenant_id=tenant_id, pairs=[*pairs_of(current), *adding]
        )


_LIVE_AGENTS: Final = (
    "SELECT id, name FROM agents WHERE status = 'live' AND deleted_at IS NULL ORDER BY id"
)


async def _assert_live_agents_fit(
    session: AsyncSession, *, tenant_id: UUID, pairs: Sequence[tuple[str, str]]
) -> None:
    """Refuse a pinned-facts change that would push a live agent's instructions past the
    calling system's box (D-752). Pinned facts ride in every agent's instructions, so a
    change accepted here and refused at the recompile's publish would leave that agent on
    its old script with nobody told."""
    from apps.api.agents.prompt_size import measure_config, publish_config
    from apps.api.engine import get_engine
    from apps.api.engine.hosted_platform import hosted_agent_limits

    engine = get_engine()
    if hosted_agent_limits(engine).prompt_chars is None:
        return
    for agent_id, name in (await session.execute(text(_LIVE_AGENTS))).all():
        row = (
            await session.execute(
                text(
                    "SELECT pv.body, pv.structured_script FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).first()
        if row is None or not row[0]:
            continue
        try:
            cfg = await publish_config(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine=engine,
                body=splice_quick_facts(row[0], pairs),
                structured_script=row[1],
            )
        except ProblemError:
            continue
        size = measure_config(cfg, engine)
        if not size.fits:
            raise ProblemError.business_rule(
                "pinned_facts_too_long_for_agent",
                f"Pinned facts go into every agent's script. With this change, the script of "
                f"{name} would be {size.over:,} characters too long for the calling system, "
                "so it could not be put live.",
                remediation=(
                    "Shorten or unpin a fact, or shorten that agent's script first. Facts "
                    "that are not pinned are still found when a caller asks."
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
    """Queue the re-splice of every agent, in the caller's transaction, and a lead-detail
    suggestion pass for each, since the facts say what the business sells (D-889)."""
    from apps.api.agents.field_suggestions import queue_account

    await enqueue_outbox(session, job=RECOMPILE_JOB, payload={"tenant_id": str(tenant_id)})
    await queue_account(session, tenant_id=tenant_id)


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
    await assert_room(session, adding=[(q or "", a)], tenant_id=tenant_id)
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
    from apps.api.agents.models import is_published
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
    if is_published(row[0], row[1]) and not staged:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
    log.info(
        "pinned_facts_recompiled",
        extra={"agent_id": str(agent_id), "prompt_version": version, "staged": staged},
    )
    return version


NotYetReason = Literal["waiting_put_live", "too_long", "on_the_way"]


@dataclass(frozen=True, slots=True)
class NotYetOn:
    """An agent whose live instructions do not carry the current pinned facts, and why."""

    agent_id: UUID
    agent_name: str
    reason: NotYetReason
    #: What it means and what to do, in the owner's words.
    sentence: str


def _section(body: str) -> list[str]:
    """The quick-facts section of a compiled body, header to the next section."""
    lines: list[str] = []
    inside = False
    for line in body.splitlines():
        if line.startswith("["):
            inside = line.startswith(QUICK_FACTS_HEADER)
        if inside and line.strip():
            lines.append(line)
    return lines


def _carries(body: str, pairs: Sequence[tuple[str, str]]) -> bool:
    """Does `body` hold exactly these facts? Compared section to section rather than whole
    bodies, because a body written before splicing existed differs in layout alone."""
    return _section(body) == _section(splice_quick_facts(body, pairs))


async def not_yet_on(session: AsyncSession) -> list[NotYetOn]:
    """Every agent whose LIVE instructions lack the current pinned facts (D-838).

    `recompile_agent` leaves two cases behind on purpose: an agent with a script edit staged
    gets the facts in its draft only, and an agent the engine would refuse (instructions over
    the limit) keeps what it had while an operator is alerted. Both are invisible to the owner
    unless they are named here. Read from the versions themselves, so a recompile still
    queued shows as `on_the_way` until it lands.
    """
    from apps.api.agents.script_builder import compiled_preview

    pairs = pairs_of(await list_pinned(session))
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, live.body, draft.body, draft.structured_script, "
                "(a.system_prompt_id IS DISTINCT FROM a.live_prompt_id) "
                "FROM agents a JOIN prompt_versions live ON live.id = a.live_prompt_id "
                "LEFT JOIN prompt_versions draft ON draft.id = a.system_prompt_id "
                "WHERE a.deleted_at IS NULL AND a.status <> 'archived' "
                "ORDER BY a.created_at, a.id"
            )
        )
    ).all()
    missing: list[NotYetOn] = []
    for agent_id, name, live_body, draft_body, structured, staged in rows:
        if not live_body or _carries(live_body, pairs):
            continue
        name = str(name)
        if staged and draft_body and _carries(draft_body, pairs):
            missing.append(
                NotYetOn(
                    agent_id=agent_id,
                    agent_name=name,
                    reason="waiting_put_live",
                    sentence=(
                        f"Not yet on {name}: it has script changes waiting. Put them live "
                        "from its Script tab and these facts go live with them."
                    ),
                )
            )
            continue
        script = (
            CallScript.model_validate(structured)
            if isinstance(structured, dict)
            else CallScript.from_freeform(str(draft_body or live_body))
        )
        size = (await compiled_preview(session, agent_id, script)).size
        missing.append(
            NotYetOn(
                agent_id=agent_id,
                agent_name=name,
                reason="on_the_way",
                sentence=f"Being added to {name}. This takes a minute.",
            )
            if size.fits
            else NotYetOn(
                agent_id=agent_id,
                agent_name=name,
                reason="too_long",
                sentence=(
                    f"Not on {name}: its instructions would be too long with these facts, so "
                    "it keeps the ones it had. Shorten its script or remove a pinned fact."
                ),
            )
        )
    return missing


__all__ = [
    "MAX_PINNED_CHARS",
    "RECOMPILE_JOB",
    "NotYetOn",
    "NotYetReason",
    "PinnedFact",
    "absorb_script_facts",
    "add_pinned",
    "assert_room",
    "clean_pinned",
    "list_pinned",
    "not_yet_on",
    "pairs_of",
    "recompile_agent",
    "reorder",
    "request_recompile",
    "section_chars",
    "spliced_body",
]
