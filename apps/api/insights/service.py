"""Knowledge-gap service: detect-and-store (worker), list, dismiss, teach.

THE IDEMPOTENCY CONTRACT (spec 1). `record_call_gaps` is exactly-once per call: it deletes
the call's existing occurrence rows, inserts the freshly detected set, and recomputes every
aggregate the call touched — old topics AND new — so a re-drive REPLACES this call's
contribution and can never double-count. `knowledge_gap_occurrences` is the source of
truth; `knowledge_gaps` is a pure function of it.

THE RACE (spec 2). Two calls of the same (agent, topic) finishing at once must not lose an
aggregate update. `_recompute_aggregate` takes the aggregate ROW LOCK first (an
INSERT … ON CONFLICT DO UPDATE), then reads the occurrences and writes the roll-up in a
SEPARATE statement. Under READ COMMITTED the second statement's snapshot is taken after the
lock is held, so it sees every occurrence any concurrent writer had committed before
releasing the lock — the classic "lock the aggregate, then recompute from the detail"
pattern, correct without SERIALIZABLE. A single INSERT … SELECT … ON CONFLICT would compute
its EXCLUDED values from a snapshot taken BEFORE the lock and is the lost-update bug this
avoids.

RLS (hard rule 1). Every statement runs in the caller's tenant session, so occurrences,
calls and aggregates are all scoped by the FORCEd `tenant_isolation` policy — a query here
can only ever see one tenant's rows, proven by `insights/rls_test.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.insights import detection
from apps.api.insights.schemas import (
    GapTeachIn,
    KnowledgeGapListOut,
    KnowledgeGapOut,
)

log = get_logger(__name__)

#: The most gaps one listing returns. A ceiling, not a target — the urgent surface shows a
#: handful and the count says how many there are (`open_count`), the same split
#: `crm.attention` keeps.
MAX_PAGE = 100

#: The name a KB draft seeded from a taught gap is filed under. The topic label follows so
#: an operator reviewing the draft queue sees which gap it answers.
_KB_DRAFT_PREFIX = "Knowledge gap:"


async def record_call_gaps(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    turns: Sequence[detection.Turn],
) -> int:
    """Detect the gaps on one completed call and fold them into the aggregates.

    Idempotent per call (see module docstring). Returns the number of distinct gap topics
    this call contributed, for the pipeline's stage span. `turns` MUST carry redacted text
    — the pipeline passes `transcript_turns.text_redacted` — so every stored quote is
    redacted by construction (hard rule 6).
    """
    gaps = detection.detect_gaps(turns)
    async with tenant_session(tenant_id) as session:
        # Topics this call PREVIOUSLY contributed — recomputed too, so a re-drive that no
        # longer detects a topic correctly shrinks its aggregate instead of stranding it.
        previous = {
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT topic_key FROM knowledge_gap_occurrences "
                        "WHERE call_id = :cid AND tenant_id = :tid"
                    ),
                    {"cid": call_id, "tid": tenant_id},
                )
            ).all()
        }
        # Replace this call's contribution wholesale — the delete + re-insert is the whole
        # of "exactly-once, keyed by call_id". Both run in one transaction, so a re-drive
        # interrupted mid-flight cannot leave a partial set behind.
        await session.execute(
            text("DELETE FROM knowledge_gap_occurrences WHERE call_id = :cid AND tenant_id = :tid"),
            {"cid": call_id, "tid": tenant_id},
        )
        for gap in gaps:
            await session.execute(
                text(
                    "INSERT INTO knowledge_gap_occurrences "
                    "(id, tenant_id, agent_id, call_id, topic_key, topic_label, "
                    " question_redacted, answer_redacted, signal, hit_count, "
                    " created_at, updated_at) "
                    "VALUES (:id, :tid, :aid, :cid, :key, :label, :q, :a, :sig, :hits, "
                    " now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "cid": call_id,
                    "key": gap.topic_key,
                    "label": gap.topic_label,
                    "q": gap.question_redacted,
                    "a": gap.answer_redacted,
                    "sig": gap.signal,
                    "hits": gap.hit_count,
                },
            )
        affected = previous | {gap.topic_key for gap in gaps}
        for topic_key in affected:
            await _recompute_aggregate(
                session, tenant_id=tenant_id, agent_id=agent_id, topic_key=topic_key
            )
    return len(gaps)


async def _recompute_aggregate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    topic_key: str,
    deprioritise: str | None = None,
) -> None:
    """Re-derive one aggregate from its occurrences, race-safe (see module docstring).

    STEP 1 locks (or creates) the aggregate row. STEP 2, holding that lock, reads the
    occurrences and writes the roll-up; the example quotes and `top_signal` are taken from
    the MOST RECENT contributing call (`array_agg … ORDER BY call time DESC`). `status` is
    never written here — a recurrence must not re-open a gap the client closed.

    `deprioritise` IS THE ERASURE'S DOING AND IS A NO-OP ON THE NORMAL PATH. When an
    erasure or a retention sweep marks a quote, that occurrence is usually still the most
    recent one, so a plain "newest wins" pick would put the MARKER on the client's card
    while a perfectly good older example sat unused — a dashboard degraded as a side
    effect of an unrelated caller's erasure request. Sorting `(quote = :dep)` first puts
    marked quotes last (`false` sorts before `true`), so a surviving sentence wins and the
    marker is chosen only when nothing else is left. Passing `None` compares against NULL,
    which is NULL for every row and therefore orders nothing — the normal path is
    byte-identical to what it was, which is why this is safe to do in the shared
    recompute rather than in a second one. STEP 3
    deletes the aggregate when no occurrences remain, so a re-drive that removed a topic's
    last occurrence leaves no orphan open gap behind.
    """
    # STEP 1 — lock or create. DO UPDATE (not DO NOTHING) so the conflicting row is locked;
    # the placeholder values are overwritten by STEP 2 or removed by STEP 3.
    await session.execute(
        text(
            "INSERT INTO knowledge_gaps "
            "(id, tenant_id, agent_id, topic_key, topic_label, status, occurrence_count, "
            " call_count, example_question_redacted, example_answer_redacted, top_signal, "
            " first_seen_at, last_seen_at, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :key, :key, 'open', 0, 0, '', '', 'dont_know', "
            " now(), now(), now(), now()) "
            "ON CONFLICT (tenant_id, agent_id, topic_key) "
            "DO UPDATE SET updated_at = now()"
        ),
        {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "key": topic_key},
    )
    # STEP 2 — recompute from the detail, now that the row is locked. The subquery's
    # snapshot is fresh (a new statement), so it sees every occurrence a concurrent writer
    # committed before releasing the lock. No row is produced when there are no
    # occurrences, so this UPDATE is a no-op in that case and STEP 3 handles it.
    await session.execute(
        text(
            "UPDATE knowledge_gaps g SET "
            "  occurrence_count = agg.occ, "
            "  call_count = agg.calls, "
            "  topic_label = agg.topic_label, "
            "  example_question_redacted = agg.ex_q, "
            "  example_answer_redacted = agg.ex_a, "
            "  top_signal = agg.top_signal, "
            "  first_seen_at = agg.first_seen, "
            "  last_seen_at = agg.last_seen, "
            "  updated_at = now() "
            "FROM ( "
            "  SELECT sum(o.hit_count) AS occ, count(*) AS calls, "
            "    min(coalesce(c.started_at, c.created_at)) AS first_seen, "
            "    max(coalesce(c.started_at, c.created_at)) AS last_seen, "
            "    (array_agg(o.topic_label ORDER BY coalesce(c.started_at, c.created_at) DESC))[1] "
            "      AS topic_label, "
            "    (array_agg(o.question_redacted ORDER BY (o.question_redacted = :dep), "
            "      coalesce(c.started_at, c.created_at) DESC))[1] AS ex_q, "
            "    (array_agg(o.answer_redacted ORDER BY (o.answer_redacted = :dep), "
            "      coalesce(c.started_at, c.created_at) DESC))[1] AS ex_a, "
            "    (array_agg(o.signal ORDER BY coalesce(c.started_at, c.created_at) DESC))[1] "
            "      AS top_signal "
            "  FROM knowledge_gap_occurrences o JOIN calls c ON c.id = o.call_id "
            "  WHERE o.tenant_id = :tid AND o.agent_id = :aid AND o.topic_key = :key "
            ") agg "
            "WHERE g.tenant_id = :tid AND g.agent_id = :aid AND g.topic_key = :key "
            "  AND agg.occ IS NOT NULL"
        ),
        {"tid": tenant_id, "aid": agent_id, "key": topic_key, "dep": deprioritise},
    )
    # STEP 3 — no occurrences left: the aggregate is derived, so it goes with them. Runs
    # under the same lock; the NOT EXISTS is evaluated now, so a concurrent call that
    # committed an occurrence for this topic keeps the row.
    await session.execute(
        text(
            "DELETE FROM knowledge_gaps g "
            "WHERE g.tenant_id = :tid AND g.agent_id = :aid AND g.topic_key = :key "
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM knowledge_gap_occurrences o "
            "    WHERE o.tenant_id = :tid AND o.agent_id = :aid AND o.topic_key = :key "
            "  )"
        ),
        {"tid": tenant_id, "aid": agent_id, "key": topic_key},
    )


async def scrub_quotes_for_calls(
    session: AsyncSession, *, call_ids: Sequence[UUID], mark: str
) -> int:
    """Remove the caller's own words from both gap tables for these calls. Counts stay.

    **THE HOLE THIS CLOSES.** A DPDP erasure does not DELETE a call — it scrubs the call
    in place (`transcript_turns.text`/`.text_redacted` → the marker, the phone columns →
    NULL, `call_extractions.data` → `{}`) and keeps the row, because the call is billing
    evidence. `knowledge_gap_occurrences.call_id` is `ON DELETE CASCADE`, which reads like
    protection and is not: nothing is ever deleted, so the cascade never fires. The
    quotes in `question_redacted` / `answer_redacted` were copied out of
    `transcript_turns.text_redacted` at detection time, so after an erasure they were the
    LAST surviving copy of what that caller said — and `knowledge_gaps` held a second one
    in `example_question_redacted` / `example_answer_redacted`, with no `call_id` on it at
    all. Neither table appeared in any erasure path or in `DERIVED_COPIES`.

    **REDACTED IS NOT ERASED, and the column name invites exactly that mistake.**
    Redaction removes identifiers — a phone number, an email — from a sentence. It does
    not remove the sentence. "Do you do IVF, my wife and I have been trying for six
    years" survives redaction intact, and it is still that caller's words.

    **SCRUBBED, NOT DELETED, and the choice matters to the client.** The row is kept and
    emptied, which is what `call_extractions` does two statements up the same function.
    Deleting the occurrence would silently move the client's analytics as a side effect of
    a stranger's erasure request — "12 callers asked about parking" becoming 11, with the
    aggregate's `call_count` following it. The count is not the caller's data; the
    sentence is. So the sentence goes and the count stays.

    THE AGGREGATE IS RE-DERIVED RATHER THAN PATCHED. `knowledge_gaps` cannot say which
    occurrence its example came from, so there is nothing to compare against. Re-running
    `_recompute_aggregate` answers the question properly: it re-picks the example from the
    most recent contributing call, which is now either a surviving caller's quote or the
    marker. That is also why this reuses the recompute instead of writing a second
    UPDATE — one definition of what an aggregate row means, not two that can drift.

    Returns the number of occurrence rows scrubbed, for the proof certificate.
    """
    if not call_ids:
        return 0
    ids = list(call_ids)
    # The affected aggregates, read BEFORE the scrub. Afterwards the rows are still there
    # (they are emptied, not deleted) so this could be read either side — it is read first
    # so the set is fixed even if a concurrent call adds a topic mid-statement, which
    # would otherwise be recomputed on data this function has not finished writing.
    affected = (
        await session.execute(
            text(
                "SELECT DISTINCT tenant_id, agent_id, topic_key "
                "FROM knowledge_gap_occurrences WHERE call_id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    ).all()

    result = await session.execute(
        text(
            "UPDATE knowledge_gap_occurrences "
            "SET question_redacted = :mark, answer_redacted = :mark, updated_at = now() "
            # Idempotent, and for `call_extractions`'s reason: a re-run of an erasure must
            # not report a second, larger count for work the first one already did.
            "WHERE call_id = ANY(:ids) "
            "  AND (question_redacted <> :mark OR answer_redacted <> :mark)"
        ),
        {"ids": ids, "mark": mark},
    )
    scrubbed = int(rowcount_of(result) or 0)

    for tenant_id, agent_id, topic_key in affected:
        await _recompute_aggregate(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            topic_key=str(topic_key),
            deprioritise=mark,
        )
    return scrubbed


# --- read + mutate (client realm) --------------------------------------------


def _row_to_out(row: object) -> KnowledgeGapOut:
    r = row  # a SQLAlchemy Row with the SELECT's labels
    return KnowledgeGapOut(
        id=r.id,  # type: ignore[attr-defined]
        agent_id=r.agent_id,  # type: ignore[attr-defined]
        agent_name=r.agent_name,  # type: ignore[attr-defined]
        topic_key=r.topic_key,  # type: ignore[attr-defined]
        topic_label=r.topic_label,  # type: ignore[attr-defined]
        status=r.status,  # type: ignore[attr-defined]
        signal=r.top_signal,  # type: ignore[attr-defined]
        occurrence_count=r.occurrence_count,  # type: ignore[attr-defined]
        call_count=r.call_count,  # type: ignore[attr-defined]
        example_question=r.example_question_redacted,  # type: ignore[attr-defined]
        example_answer=r.example_answer_redacted,  # type: ignore[attr-defined]
        first_seen_at=r.first_seen_at,  # type: ignore[attr-defined]
        last_seen_at=r.last_seen_at,  # type: ignore[attr-defined]
        resolution=r.resolution,  # type: ignore[attr-defined]
        resolved_by=r.resolved_by,  # type: ignore[attr-defined]
        resolved_at=r.resolved_at,  # type: ignore[attr-defined]
        kb_source_id=r.kb_source_id,  # type: ignore[attr-defined]
    )


async def list_gaps(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    status: str | None = "open",
    limit: int = 50,
    offset: int = 0,
) -> KnowledgeGapListOut:
    """Gaps for the org, urgency-ordered: OPEN first, then by how often it has happened,
    then most recent. `agent_id` scopes to one agent's page (spec 4b); `status=None`
    returns every status, `status='open'` (the default and what the dashboard uses) only
    the urgent ones.

    `open_count` and `total` are counted by their own query over the whole scope — never
    off the page — so a busy account's badge is honest, the split `crm.attention` argues
    for at length.
    """
    params: dict[str, object] = {"limit": min(limit, MAX_PAGE), "offset": offset}
    where = ["g.tenant_id = current_setting('app.tenant_id', true)::uuid"]
    if agent_id is not None:
        where.append("g.agent_id = :aid")
        params["aid"] = agent_id
    if status is not None:
        where.append("g.status = :status")
        params["status"] = status
    clause = " AND ".join(where)
    rows = (
        await session.execute(
            text(
                "SELECT g.id, g.agent_id, a.name AS agent_name, g.topic_key, g.topic_label, "
                "  g.status, g.top_signal, g.occurrence_count, g.call_count, "
                "  g.example_question_redacted, g.example_answer_redacted, "
                "  g.first_seen_at, g.last_seen_at, g.resolution, g.resolved_by, g.resolved_at, "
                "  g.kb_source_id "
                "FROM knowledge_gaps g LEFT JOIN agents a ON a.id = g.agent_id "
                f"WHERE {clause} "
                # Urgency: open before resolved, then the most-recurring, then the freshest.
                "ORDER BY (g.status = 'open') DESC, g.occurrence_count DESC, g.last_seen_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()

    # Counts over the SAME scope minus the status filter and the page window.
    count_params: dict[str, object] = {}
    count_where = ["tenant_id = current_setting('app.tenant_id', true)::uuid"]
    if agent_id is not None:
        count_where.append("agent_id = :aid")
        count_params["aid"] = agent_id
    counts = (
        await session.execute(
            text(
                "SELECT count(*) AS total, "
                "  count(*) FILTER (WHERE status = 'open') AS open_count "
                "FROM knowledge_gaps WHERE " + " AND ".join(count_where)
            ),
            count_params,
        )
    ).one()
    return KnowledgeGapListOut(
        items=[_row_to_out(row) for row in rows],
        open_count=int(counts.open_count),
        total=int(counts.total),
    )


async def _load_gap(session: AsyncSession, gap_id: UUID) -> object:
    row = (
        await session.execute(
            text(
                "SELECT g.id, g.agent_id, a.name AS agent_name, g.topic_key, g.topic_label, "
                "  g.status, g.top_signal, g.occurrence_count, g.call_count, "
                "  g.example_question_redacted, g.example_answer_redacted, "
                "  g.first_seen_at, g.last_seen_at, g.resolution, g.resolved_by, g.resolved_at, "
                "  g.kb_source_id "
                "FROM knowledge_gaps g LEFT JOIN agents a ON a.id = g.agent_id "
                "WHERE g.id = :id"
            ),
            {"id": gap_id},
        )
    ).first()
    if row is None:
        # RLS makes another tenant's gap indistinguishable from a missing one — a 404 is
        # the honest answer to both and leaks nothing. The ONE not-found shape
        # (`code="not_found"`), like every other tenant-scoped 404 in the client space, so
        # `adversarial_pass_test`'s IDOR sweep sees the generic row-not-found it asserts on
        # rather than a per-route code that reads as a handler comparison.
        raise ProblemError.not_found("Knowledge gap")
    return row


async def get_gap(session: AsyncSession, gap_id: UUID) -> KnowledgeGapOut:
    return _row_to_out(await _load_gap(session, gap_id))


async def dismiss_gap(
    session: AsyncSession, gap_id: UUID, *, principal: Principal, reason: str | None
) -> KnowledgeGapOut:
    """Mark a gap dismissed. It drops off the urgent surface but its occurrences stay, so
    the count keeps climbing if the question keeps being asked — a client who dismissed it
    can still see it was not really solved."""
    await _load_gap(session, gap_id)  # 404s if not this tenant's, before we write
    await session.execute(
        text(
            "UPDATE knowledge_gaps SET status = 'dismissed', resolution = :reason, "
            "  resolved_by = :by, resolved_at = now(), updated_at = now() WHERE id = :id"
        ),
        {"id": gap_id, "reason": reason, "by": principal.user_id},
    )
    return await get_gap(session, gap_id)


async def teach_gap(
    session: AsyncSession, gap_id: UUID, *, principal: Principal, payload: GapTeachIn
) -> KnowledgeGapOut:
    """Record the answer the agent was missing, and (by default) seed a KB draft from it.

    The KB draft goes in as an ordinary `pending_approval` source through `kb.submit_source`
    — the ONE clean, tenant-safe entry point that module exposes — so it lands in the same
    review queue any other submission does rather than reaching around the KB module's
    boundary. It is a DRAFT on purpose: teaching a gap proposes a fact; publishing it is
    still the reviewed step (`kb.approve_source` → `kb.publish_source`), exactly as it is
    for a source a client pastes in themselves.
    """
    row = await _load_gap(session, gap_id)
    agent_id: UUID = row.agent_id  # type: ignore[attr-defined]
    topic_label: str = row.topic_label  # type: ignore[attr-defined]
    tenant_id = principal.tenant_id
    kb_source_id: UUID | None = None
    if payload.create_kb_draft and tenant_id is not None:
        # Local import: the KB module is an api peer and a module-level import would drag it
        # (and its engine coupling) into the worker that imports this module for detection.
        from apps.api.kb import service as kb

        created = await kb.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=f"{_KB_DRAFT_PREFIX} {topic_label}",
            body=payload.answer,
            submitted_by=principal.user_id,
        )
        kb_source_id = UUID(str(created["id"]))
    await session.execute(
        text(
            "UPDATE knowledge_gaps SET status = 'taught', resolution = :answer, "
            "  resolved_by = :by, resolved_at = now(), kb_source_id = :kb, updated_at = now() "
            "WHERE id = :id"
        ),
        {"id": gap_id, "answer": payload.answer, "by": principal.user_id, "kb": kb_source_id},
    )
    return await get_gap(session, gap_id)


__all__ = [
    "MAX_PAGE",
    "dismiss_gap",
    "get_gap",
    "list_gaps",
    "record_call_gaps",
    "scrub_quotes_for_calls",
    "teach_gap",
]
