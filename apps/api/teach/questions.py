"""The questions an account's agents need answered, in one list (D-893, PIP-AGENT-PLAN §5).

Three kinds of question, merged by topic key so one subject is asked once:

1. **Callers asked it** (`callers`): open knowledge gaps, every agent's gaps on one topic
   together, ranked by the calls they cost. The quote is the caller's redacted words.
2. **Practice callers need it** (`practice`): a fact callers commonly ask for that nothing
   the business gave has (`test_conversations.missing_facts`, today prices), the same
   reading that writes "Add your prices first" above a practice run.
3. **Setup leaves it open** (`setup`): opening hours and the address, which the after-hours
   branch and every "where are you?" depend on (`business_profile.BLOCKER_STEPS`), while
   neither the profile nor a fact gives them.

A question is answered through the teach path: the answer becomes a fact every agent searches
(`facts.add_facts`, D-821's store), the topic's open gaps close as taught, and the facts
source is republished so the next call carries it. "Not something we answer" closes the
gaps as dismissed. A practice or setup question has no gap to close, so its settlement is
kept in `teach_questions`; a later gap on the same topic asks it again, because a caller did.

DRAFTS. Where what the business already gave us (its profile, its facts, its earlier answers,
its files) answers a question, Pip drafts the answer and names that source; a draft without
a source is never offered. Drafting calls a model, so it runs in the worker
(`workers/teach_questions.py`), never here. A read queues at most `MAX_DRAFTS_PER_READ`
drafts, each once per fingerprint of its inputs (`enqueue_outbox_once`), and a cached draft
is reused until those inputs change.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.test_conversations import missing_facts
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.teach import facts as fact_store
from apps.api.teach.models import MAX_DISMISS_REASON_CHARS, MAX_QUESTION_KEY_CHARS
from apps.api.tenancy.business_profile import fact_lines, load_profile

#: The worker job that drafts one question's answer (`workers/teach_questions.py`).
DRAFT_JOB: Final = "draft_teach_question"
MAX_QUESTIONS: Final = 50
#: Drafts one read may queue: the top of the list is what the owner answers first.
MAX_DRAFTS_PER_READ: Final = 10

Why = Literal["callers", "practice", "setup"]
SourceKind = Literal["profile", "fact", "answer", "file"]

#: The plain question for each canonical gap topic (`insights/detection._TOPICS`). A topic
#: made from a caller's own words is asked in those (redacted) words instead.
TOPIC_QUESTIONS: Final[dict[str, str]] = {
    "pricing": "What do your products or services cost?",
    "refund": "Do you give refunds or take returns?",
    "warranty": "Is there a warranty?",
    "delivery": "Do you deliver, and where?",
    "timings": "When are you open?",
    "location": "Where are you, and how do callers find you?",
    "availability": "What do you have in stock?",
    "booking": "How can callers book?",
    "offers": "Do you have any offers or discounts now?",
    "payment": "How can customers pay?",
    "documents": "What documents do customers need?",
}

#: Something that reads as opening times in a fact or a document. Postgres regex.
_HOURS_PATTERN: Final = (
    r"\m[0-9]{1,2}(:[0-9]{2})?\s*(am|pm)\M|o'?clock|\mopen(s|ing)?\M|\mclosed\M|\mtimings?\M"
    r"|\mhours\M|గంటల|సమయం|बजे|खुल"
)
#: Something that reads as an address.
_ADDRESS_PATTERN: Final = (
    r"\maddress|\mroad\M|\mstreet|nagar\M|\mnear\M|\mopposite\M|\mlocated|\mbranch"
    r"|చిరునామా|पता"
)

_WHY_ORDER: Final[dict[Why, int]] = {"callers": 0, "practice": 1, "setup": 2}


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    question: str
    topic: str
    why: Why
    #: Calls on which a caller asked it; 0 for practice and setup questions.
    callers: int
    times: int
    agent_ids: tuple[UUID, ...]
    latest_call_id: UUID | None
    latest_at: datetime | None
    #: What a caller said, redacted (hard rule 6); None for practice and setup questions.
    example: str | None
    draft: str | None = None
    draft_source_kind: SourceKind | None = None
    draft_source_label: str | None = None
    drafting: bool = False


@dataclass(frozen=True, slots=True)
class QuestionList:
    items: list[Question]
    open_count: int


_GAPS_SQL: Final = (
    "SELECT g.topic_key, min(g.topic_label) AS label, sum(g.call_count) AS calls, "
    "  sum(g.occurrence_count) AS times, array_agg(DISTINCT g.agent_id) AS agents, "
    "  max(g.last_seen_at) AS last_seen, "
    "  (array_agg(g.example_question_redacted ORDER BY g.last_seen_at DESC))[1] AS example, "
    "  (SELECT o.call_id FROM knowledge_gap_occurrences o WHERE o.topic_key = g.topic_key "
    "   AND (CAST(:aid AS uuid) IS NULL OR o.agent_id = CAST(:aid AS uuid)) "
    "   ORDER BY o.created_at DESC LIMIT 1) AS last_call "
    "FROM knowledge_gaps g WHERE g.status = 'open' "
    "  AND (CAST(:aid AS uuid) IS NULL OR g.agent_id = CAST(:aid AS uuid)) "
    "GROUP BY g.topic_key ORDER BY calls DESC, last_seen DESC LIMIT :limit"
)

_COVERED_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM kb_facts WHERE removed_at IS NULL AND text ~* :pattern) "
    "OR EXISTS (SELECT 1 FROM kb_documents d JOIN kb_sources s ON s.id = d.source_id "
    "WHERE s.is_active AND s.published_at IS NOT NULL AND d.content ~* :pattern)"
)

#: What a draft is written from, as change markers: any edit to the facts, the profile, the
#: live knowledge or the earlier answers moves it, and nothing else does.
_INPUTS_SQL: Final = (
    "SELECT concat_ws('|', "
    "(SELECT COALESCE(max(updated_at)::text, '-') || ':' || count(*) FROM kb_facts "
    " WHERE removed_at IS NULL), "
    "(SELECT COALESCE(max(updated_at)::text, '-') FROM business_profiles), "
    "(SELECT COALESCE(max(updated_at)::text, '-') || ':' || count(*) FROM kb_sources "
    " WHERE is_active), "
    "(SELECT COALESCE(max(resolved_at)::text, '-') || ':' || count(*) FROM knowledge_gaps "
    " WHERE status = 'taught'))"
)


def _gap_question(key: str, label: str, example: str | None) -> str:
    asked = TOPIC_QUESTIONS.get(key)
    if asked is not None:
        return asked
    return (example or "").strip() or label


async def _covered(session: AsyncSession, pattern: str) -> bool:
    return bool((await session.execute(text(_COVERED_SQL), {"pattern": pattern})).scalar())


async def _open_questions(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID | None
) -> list[Question]:
    rows = (await session.execute(text(_GAPS_SQL), {"aid": agent_id, "limit": MAX_QUESTIONS})).all()
    found: dict[str, Question] = {}
    for r in rows:
        key = str(r.topic_key)
        found[key] = Question(
            key=key,
            question=_gap_question(key, str(r.label), r.example),
            topic=str(r.label),
            why="callers",
            callers=int(r.calls),
            times=int(r.times),
            agent_ids=tuple(sorted(r.agents)),
            latest_call_id=r.last_call,
            latest_at=r.last_seen,
            example=(r.example or None),
        )

    extra: list[Question] = []
    if "prices" in await missing_facts(session):
        extra.append(_asked("pricing", "Pricing", "practice"))
    profile = await load_profile(session, tenant_id=tenant_id)
    if not profile.hours and not await _covered(session, _HOURS_PATTERN):
        extra.append(_asked("timings", "Opening hours", "setup"))
    if not profile.branches and not await _covered(session, _ADDRESS_PATTERN):
        extra.append(_asked("location", "Location & directions", "setup"))
    settled = await _settled_keys(session, [q.key for q in extra])
    for question in extra:
        if question.key not in found and question.key not in settled:
            found[question.key] = question

    return sorted(
        found.values(),
        key=lambda q: (
            -q.callers,
            _WHY_ORDER[q.why],
            -(q.latest_at.timestamp() if q.latest_at else 0.0),
            q.key,
        ),
    )


def _asked(key: str, topic: str, why: Why) -> Question:
    return Question(
        key=key,
        question=TOPIC_QUESTIONS[key],
        topic=topic,
        why=why,
        callers=0,
        times=0,
        agent_ids=(),
        latest_call_id=None,
        latest_at=None,
        example=None,
    )


async def _settled_keys(session: AsyncSession, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    rows = await session.execute(
        text(
            "SELECT question_key FROM teach_questions "
            "WHERE question_key = ANY(:keys) AND settled IS NOT NULL"
        ),
        {"keys": keys},
    )
    return {str(r[0]) for r in rows}


async def inputs_marker(session: AsyncSession) -> str:
    return str((await session.execute(text(_INPUTS_SQL))).scalar_one())


def inputs_hash(marker: str, question: Question) -> str:
    """The fingerprint of what one question's draft is written from."""
    return hashlib.sha256(f"{marker}\n{question.key}\n{question.question}".encode()).hexdigest()


async def list_questions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID | None = None,
    queue_drafts: bool = False,
) -> QuestionList:
    """The open questions, most-asked first, each with its cached draft.

    `queue_drafts` lets this read queue the worker for questions whose draft is missing or
    was written from inputs that have since changed. A view-as read passes False: an
    operator looking must not spend the client's AI allowance."""
    questions = await _open_questions(session, tenant_id=tenant_id, agent_id=agent_id)
    if not questions:
        return QuestionList(items=[], open_count=0)
    marker = await inputs_marker(session)
    cached = {
        str(r.question_key): r
        for r in await session.execute(
            text(
                "SELECT question_key, inputs_hash, draft_status, draft, draft_source_kind, "
                "draft_source_label FROM teach_questions WHERE question_key = ANY(:keys)"
            ),
            {"keys": [q.key for q in questions]},
        )
    }
    out: list[Question] = []
    queued = 0
    for question in questions:
        fingerprint = inputs_hash(marker, question)
        row = cached.get(question.key)
        if row is not None and row.inputs_hash == fingerprint:
            if row.draft_status == "ready":
                question = replace(
                    question,
                    draft=row.draft,
                    draft_source_kind=row.draft_source_kind,
                    draft_source_label=row.draft_source_label,
                )
            elif row.draft_status == "queued":
                question = replace(question, drafting=True)
        elif queue_drafts and queued < MAX_DRAFTS_PER_READ:
            await _queue_draft(
                session, tenant_id=tenant_id, key=question.key, fingerprint=fingerprint
            )
            queued += 1
            question = replace(question, drafting=True)
        out.append(question)
    return QuestionList(items=out, open_count=len(out))


async def _queue_draft(
    session: AsyncSession, *, tenant_id: UUID, key: str, fingerprint: str
) -> None:
    """Mark the draft as being written for these inputs, and queue the worker once per
    fingerprint. A draft from older inputs is cleared, so it is never offered stale."""
    await session.execute(
        text(
            "INSERT INTO teach_questions (id, tenant_id, question_key, inputs_hash, "
            "draft_status, created_at, updated_at) VALUES (:id, :tid, :key, :hash, 'queued', "
            "now(), now()) ON CONFLICT (tenant_id, question_key) DO UPDATE SET "
            "inputs_hash = EXCLUDED.inputs_hash, draft_status = 'queued', draft = NULL, "
            "draft_source_kind = NULL, draft_source_label = NULL, updated_at = now() "
            "WHERE teach_questions.inputs_hash IS DISTINCT FROM EXCLUDED.inputs_hash"
        ),
        {"id": uuid7(), "tid": tenant_id, "key": key, "hash": fingerprint},
    )
    await enqueue_outbox_once(
        session,
        job=DRAFT_JOB,
        payload={"tenant_id": str(tenant_id), "question_key": key, "inputs_hash": fingerprint},
        dedupe_key=f"{DRAFT_JOB}:{tenant_id}:{key}:{fingerprint}",
    )


async def find_question(session: AsyncSession, *, tenant_id: UUID, key: str) -> Question:
    """One open question by key, or a 409 that says it is no longer waiting."""
    if not key or len(key) > MAX_QUESTION_KEY_CHARS:
        raise ProblemError.not_found("Question")
    for question in await _open_questions(session, tenant_id=tenant_id, agent_id=None):
        if question.key == key:
            return question
    raise ProblemError.conflict(
        "question_not_open",
        "This question was already answered or dismissed.",
        remediation="Reload the list of questions to answer.",
    )


@dataclass(frozen=True, slots=True)
class Settled:
    key: str
    #: The fact the answer became; None when the agents already knew those exact words.
    fact_id: UUID | None
    gaps_closed: int


async def _settle(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    key: str,
    settled: Literal["answered", "dismissed"],
    reason: str | None,
    by: UUID | None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO teach_questions (id, tenant_id, question_key, settled, settled_reason, "
            "settled_by, settled_at, created_at, updated_at) VALUES (:id, :tid, :key, :settled, "
            ":reason, :by, now(), now(), now()) ON CONFLICT (tenant_id, question_key) DO UPDATE "
            "SET settled = EXCLUDED.settled, settled_reason = EXCLUDED.settled_reason, "
            "settled_by = EXCLUDED.settled_by, settled_at = now(), updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "key": key,
            "settled": settled,
            "reason": reason,
            "by": by,
        },
    )


async def _close_gaps(
    session: AsyncSession,
    *,
    key: str,
    status: Literal["taught", "dismissed"],
    resolution: str | None,
    by: UUID | None,
) -> int:
    # Every agent's open gap on this topic closes: the answer is a fact every agent carries
    # (D-689). `status = 'open'` in the WHERE is the compare-and-set that `insights.service.
    # _claim_gap` keeps for one gap: a gap settled meanwhile keeps its own resolution.
    rows = await session.execute(
        text(
            "UPDATE knowledge_gaps SET status = :status, resolution = :resolution, "
            "resolved_by = :by, resolved_at = now(), updated_at = now() "
            "WHERE topic_key = :key AND status = 'open' RETURNING id"
        ),
        {"key": key, "status": status, "resolution": resolution, "by": by},
    )
    return len(rows.all())


async def answer_question(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    key: str,
    answer: str,
    saved_by: UUID | None,
    client_user_id: UUID | None,
    auto_approve: bool,
) -> Settled:
    """Save the owner's answer as a fact every agent searches, and close the question."""
    question = await find_question(session, tenant_id=tenant_id, key=key)
    added = await fact_store.add_facts(
        session,
        tenant_id=tenant_id,
        texts=[answer],
        origin="call_gap" if question.why == "callers" else "taught",
        teaching_id=None,
        created_by=saved_by,
        auto_approve=auto_approve,
    )
    closed = await _close_gaps(
        session,
        key=key,
        status="taught",
        resolution=fact_store.clean_fact(answer),
        by=client_user_id,
    )
    await _settle(
        session, tenant_id=tenant_id, key=key, settled="answered", reason=None, by=client_user_id
    )
    return Settled(key=key, fact_id=added[0] if added else None, gaps_closed=closed)


async def dismiss_question(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    key: str,
    reason: str | None,
    client_user_id: UUID | None,
) -> Settled:
    """ "Not something we answer": the question leaves the list; occurrences stay, so a gap
    that keeps being asked still counts its calls."""
    await find_question(session, tenant_id=tenant_id, key=key)
    note = " ".join((reason or "").split())[:MAX_DISMISS_REASON_CHARS] or None
    closed = await _close_gaps(
        session, key=key, status="dismissed", resolution=note, by=client_user_id
    )
    await _settle(
        session,
        tenant_id=tenant_id,
        key=key,
        settled="dismissed",
        reason=note,
        by=client_user_id,
    )
    return Settled(key=key, fact_id=None, gaps_closed=closed)


# --- what a draft is written from (read by the worker) -----------------------------


@dataclass(frozen=True, slots=True)
class Source:
    kind: SourceKind
    #: How the owner reads the source beside the draft.
    label: str
    text: str


MAX_SOURCES: Final = 40
MAX_FILES: Final = 3
MAX_FILE_EXCERPT: Final = 1500
MAX_ANSWERS: Final = 20


_STOPWORDS: Final = frozenset(
    {
        "what",
        "when",
        "where",
        "how",
        "your",
        "you",
        "the",
        "and",
        "are",
        "any",
        "can",
        "for",
        "have",
        "now",
        "with",
        "there",
        "they",
        "this",
        "that",
        "callers",
        "find",
        "give",
        "take",
    }
)


def search_words(value: str) -> str:
    """`value`'s content words joined with `or`, for `websearch_to_tsquery`: a file that
    names any of them is a candidate, ranked by how many it names. Only letters and digits
    pass, so nothing in the question can be read as query syntax."""
    words: list[str] = []
    for word in re.findall(r"\w{3,}", value.casefold()):
        if word not in _STOPWORDS and word not in words:
            words.append(word)
    return " or ".join(words[:12])


async def draft_sources(
    session: AsyncSession, *, tenant_id: UUID, question: Question
) -> list[Source]:
    """Everything the business gave us that could answer `question`, bounded: its profile,
    its facts, its earlier answers to callers' questions, and the files whose words best
    match the question. The owner's own content (tenant-authored); no caller's words."""
    sources: list[Source] = [
        Source("profile", "Your business profile", line)
        for line in fact_lines(await load_profile(session, tenant_id=tenant_id))
    ]
    sources.extend(
        Source("fact", "What you taught", fact.text)
        for fact in await fact_store.list_facts(session)
    )
    answers = await session.execute(
        text(
            "SELECT topic_label, resolution FROM knowledge_gaps WHERE status = 'taught' "
            "AND COALESCE(resolution, '') <> '' ORDER BY resolved_at DESC NULLS LAST LIMIT :limit"
        ),
        {"limit": MAX_ANSWERS},
    )
    sources.extend(
        Source("answer", f"Your answer about {r.topic_label}", str(r.resolution)) for r in answers
    )
    files = await session.execute(
        text(
            "SELECT s.name, left(d.content, :excerpt) AS excerpt FROM kb_documents d "
            "JOIN kb_sources s ON s.id = d.source_id "
            "WHERE s.is_active AND s.published_at IS NOT NULL AND s.name <> :facts "
            "AND to_tsvector('simple', d.content) @@ websearch_to_tsquery('simple', :q) "
            "ORDER BY ts_rank(to_tsvector('simple', d.content), "
            "websearch_to_tsquery('simple', :q)) DESC LIMIT :limit"
        ),
        {
            "excerpt": MAX_FILE_EXCERPT,
            "facts": fact_store.FACTS_SOURCE_NAME,
            "q": search_words(f"{question.topic} {question.question}"),
            "limit": MAX_FILES,
        },
    )
    sources.extend(Source("file", str(r.name), str(r.excerpt)) for r in files)
    return sources[:MAX_SOURCES]


__all__ = [
    "DRAFT_JOB",
    "MAX_DRAFTS_PER_READ",
    "MAX_QUESTIONS",
    "TOPIC_QUESTIONS",
    "Question",
    "QuestionList",
    "Settled",
    "Source",
    "answer_question",
    "dismiss_question",
    "draft_sources",
    "find_question",
    "inputs_hash",
    "inputs_marker",
    "list_questions",
]
