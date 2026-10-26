"""Client-realm routes for teaching and the improvement loop.

Reads are `agents:read` (what the agents know, a teaching's state, saved tests) or
`calls:read` (where they struggled, a test drafted from a call). Changing what the agents
know is `kb:write` through `requires_kb_curation()`, the gate every knowledge write uses.
Saved tests and the test chat are `agents:write`; settling a waiting rule is `org:manage`,
the permission the script itself is written under. Every mutation writes an audit row with
ids and counts only (hard rule 6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.script_builder import assert_agent_visible
from apps.api.agents.test_conversations import readiness
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.kb.curation import goes_live_without_review, requires_kb_curation
from apps.api.teach import facts as fact_store
from apps.api.teach import knows, questions, rules, struggles, teaching, test_cases, try_chat
from apps.api.teach import pinned as pinned_store
from apps.api.teach.models import (
    MAX_CASE_EXPECTED_CHARS,
    MAX_CASE_LINE_CHARS,
    MAX_CASE_LINES,
    MAX_DISMISS_REASON_CHARS,
    MAX_FACT_CHARS,
    MAX_PINNED_ANSWER_CHARS,
    MAX_PINNED_QUESTION_CHARS,
    MAX_RULE_CHARS,
)

router = APIRouter(tags=["teach"])

Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- what it knows -----------------------------------------------------------------


class FactOut(Strict):
    id: UUID
    #: The fact, or a pinned fact's answer.
    text: str
    #: The caller's question a pinned fact answers, when it has one.
    question: str | None = None
    #: In every agent's instructions, winning over anything searched (the old quick facts).
    pinned: bool
    #: `taught` · `quick_fact` · `call_gap`.
    origin: str
    created_at: datetime


class KnownItemOut(Strict):
    id: UUID
    #: `document` · `photo` · `page`.
    kind: str
    name: str
    #: `live` · `getting_ready` · `in_review` · `needs_attention`.
    state: str
    url: str | None = None
    updated_at: datetime | None = None


class PinnedNotYetOut(Strict):
    agent_id: UUID
    agent_name: str
    #: `waiting_put_live` · `too_long` · `on_the_way`.
    reason: str
    sentence: str


class KnowsOut(Strict):
    facts: list[FactOut]
    #: Whether the newest facts have reached the agents: `none` · `live` · `publishing` ·
    #: `in_review`.
    facts_state: str
    items: list[KnownItemOut]
    #: Agents whose live instructions do not carry the current pinned facts, each with the
    #: sentence saying why and what to do. Empty when every agent has them.
    pinned_not_yet_on: list[PinnedNotYetOut]


@router.get(
    "/v1/kb/knows",
    response_model=KnowsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Everything the agents know: facts, documents, photos, pages and notes",
)
async def what_it_knows(
    session: Session, _: Principal = Depends(requires("agents:read"))
) -> KnowsOut:
    found = await knows.what_it_knows(session)
    return KnowsOut(
        facts=[FactOut.model_validate(f, from_attributes=True) for f in found.facts],
        facts_state=found.facts_state,
        items=[KnownItemOut.model_validate(i, from_attributes=True) for i in found.items],
        pinned_not_yet_on=[
            PinnedNotYetOut.model_validate(n, from_attributes=True) for n in found.pinned_not_yet_on
        ],
    )


class FactIn(Strict):
    text: str = Field(min_length=1, max_length=MAX_PINNED_ANSWER_CHARS)
    question: str | None = Field(default=None, max_length=MAX_PINNED_QUESTION_CHARS)
    #: Pinned facts are in every agent's instructions; others are searched when asked.
    pinned: bool = False


class FactPatch(Strict):
    text: str | None = Field(default=None, min_length=1, max_length=MAX_PINNED_ANSWER_CHARS)
    question: str | None = Field(default=None, max_length=MAX_PINNED_QUESTION_CHARS)
    pinned: bool | None = None


def _auto_approve(principal: Principal) -> bool:
    return goes_live_without_review(realm=principal.realm, impersonating=principal.impersonating)


async def _audit_fact(
    session: AsyncSession, request: Request, principal: Principal, fact_id: UUID, action: str
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_fact",
        object_id=str(fact_id),
        ip=client_request_ip(request),
    )


@router.post(
    "/v1/kb/facts",
    response_model=FactOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Add a fact by hand; a pinned one goes into every agent's instructions",
)
async def add_fact(
    payload: FactIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> FactOut:
    assert principal.tenant_id is not None
    if payload.pinned:
        fact_id = await pinned_store.add_pinned(
            session,
            tenant_id=principal.tenant_id,
            question=payload.question,
            answer=payload.text,
            origin="taught",
            created_by=principal.user_id,
        )
    else:
        added = await fact_store.add_facts(
            session,
            tenant_id=principal.tenant_id,
            texts=[payload.text],
            origin="taught",
            teaching_id=None,
            created_by=principal.user_id,
            auto_approve=_auto_approve(principal),
        )
        if not added:
            raise ProblemError.conflict("fact_exists", "Your agents already know this fact.")
        fact_id = added[0]
    await _audit_fact(session, request, principal, fact_id, "kb_fact.add")
    found = next(f for f in await fact_store.list_facts(session) if f.id == fact_id)
    return FactOut.model_validate(found, from_attributes=True)


@router.patch(
    "/v1/kb/facts/{fact_id}",
    response_model=FactOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Change a fact's wording or question, or pin or unpin it",
)
async def edit_fact(
    fact_id: UUID,
    payload: FactPatch,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> FactOut:
    assert principal.tenant_id is not None
    updated = await fact_store.update_fact(
        session,
        tenant_id=principal.tenant_id,
        fact_id=fact_id,
        text_value=payload.text,
        question=payload.question,
        pinned=payload.pinned,
        edited_by=principal.user_id,
        auto_approve=_auto_approve(principal),
    )
    await _audit_fact(session, request, principal, fact_id, "kb_fact.edit")
    return FactOut.model_validate(updated, from_attributes=True)


class PinnedOrderIn(Strict):
    #: Every pinned fact's id, once, in the order the agents should read them.
    ids: list[UUID] = Field(min_length=1, max_length=300)


@router.post(
    "/v1/kb/facts/pinned-order",
    status_code=204,
    openapi_extra=permission_meta("kb:write"),
    summary="Put the pinned facts in order",
)
async def order_pinned_facts(
    payload: PinnedOrderIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> None:
    assert principal.tenant_id is not None
    await pinned_store.reorder(session, tenant_id=principal.tenant_id, ids=payload.ids)
    await write_audit(
        session,
        action="kb_fact.reorder",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_fact",
        ip=client_request_ip(request),
        summary={"pinned": len(payload.ids)},
    )


@router.delete(
    "/v1/kb/facts/{fact_id}",
    status_code=204,
    openapi_extra=permission_meta("kb:write"),
    summary="Remove a fact from every agent",
)
async def remove_fact(
    fact_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> None:
    assert principal.tenant_id is not None
    await fact_store.remove_fact(
        session,
        tenant_id=principal.tenant_id,
        fact_id=fact_id,
        removed_by=principal.user_id,
        auto_approve=_auto_approve(principal),
    )
    await write_audit(
        session,
        action="kb_fact.remove",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_fact",
        object_id=str(fact_id),
        ip=client_request_ip(request),
    )


# --- the teach box -----------------------------------------------------------------


class TeachItemIO(Strict):
    kind: Literal["fact", "rule"]
    text: str = Field(min_length=1, max_length=max(MAX_FACT_CHARS, MAX_RULE_CHARS))
    #: A fact to pin: into every agent's instructions instead of the searched facts.
    pinned: bool = False


class TeachingOut(Strict):
    id: UUID
    #: `queued` · `reading` · `heard` (check the words) · `sorting` · `ready` (review) ·
    #: `saved` · `discarded` · `failed`.
    status: str
    #: `text` · `photo` · `file` · `voice`.
    input_kind: str
    #: What was taught, as text: typed, read off the photo or file, or heard.
    words: str | None
    items: list[TeachItemIO]
    agent_id: UUID | None
    gap_id: UUID | None
    #: A sentence to show above the review: another model sorted it, or it was not sorted.
    note: str | None
    #: Why it failed, as a code the screen words: `voice_unreadable`, `nothing_heard`,
    #: `photo_reading_unavailable`, `unreadable`, `nothing_read`, `upload_missing`, `crashed`.
    error_code: str | None
    created_at: datetime


def _teaching_out(found: teaching.Teaching) -> TeachingOut:
    return TeachingOut(
        id=found.id,
        status=found.status,
        input_kind=found.input_kind,
        words=found.words,
        items=[
            TeachItemIO(kind=item.kind, text=item.text, pinned=item.pinned) for item in found.items
        ],
        agent_id=found.agent_id,
        gap_id=found.gap_id,
        note=found.disclosure,
        error_code=found.error_code,
        created_at=found.created_at,
    )


_READ_CHUNK_BYTES = 1024 * 1024


async def read_bounded_upload(file: UploadFile, limit: int) -> bytes:
    """The upload, read a chunk at a time and refused one byte past `limit`. Also the spoken
    brief's reader (`first_run/routes.py`)."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise ProblemError(
                kind="validation",
                code="teach_upload_too_large",
                title="That is too large",
                detail=f"Send something under {limit // (1024 * 1024)} MB.",
                remediation="Record a shorter voice note, or type it.",
                status=413,
            )
        chunks.append(chunk)
    if total == 0:
        raise ProblemError.business_rule("teach_upload_empty", "That file is empty.")
    return b"".join(chunks)


@router.post(
    "/v1/kb/teach/upload",
    response_model=TeachingOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Hear a voice note for the teach box",
    description=(
        "`kind` is `voice` (a voice note under 30 seconds). The teaching stops at `heard`: "
        "the screen puts the words in the teach box for the owner to check, discards the "
        "teaching, and Pip sorts what the owner sends it (D-821). Typed words, photos and "
        "files are taught through Pip."
    ),
)
async def teach_upload(
    session: Session,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Literal["voice"], Form()],
    principal: Principal = Depends(requires_kb_curation()),
) -> TeachingOut:
    assert principal.tenant_id is not None
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in teaching.VOICE_CONTENT_TYPES:
        raise ProblemError.business_rule(
            "teach_voice_kind",
            "We could not play that recording.",
            remediation="Record the voice note again here.",
        )
    data = await read_bounded_upload(file, teaching.MAX_VOICE_BYTES)
    # Local import: `apps.workers.storage` holds the object-store client.
    from apps.workers.storage import kb_object_key, store_kb_object

    teaching_id = uuid7()
    key = kb_object_key(
        tenant_id=principal.tenant_id,
        upload_id=teaching_id,
        slot="teach",
        suffix=content_type.split("/")[-1][:8],
    )
    await store_kb_object(key=key, data=data, content_type=content_type)
    started = await teaching.start_teaching(
        session,
        tenant_id=principal.tenant_id,
        input_kind=kind,
        words=None,
        object_key=key,
        content_type=content_type,
        filename="voice-note",
        teaching_id=teaching_id,
        requested_by=principal.user_id,
    )
    return _teaching_out(started)


class OpenTeachingOut(Strict):
    teaching: TeachingOut | None


@router.get(
    "/v1/kb/teach/open",
    response_model=OpenTeachingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="This person's newest teaching that is being sorted or waits for review",
    description=(
        "What Pip was asked to teach (D-821) lands here for review: the newest of this "
        "person's teachings that is `queued`, `sorting` or `ready`, or null."
    ),
)
async def open_teaching(
    session: Session, principal: Principal = Depends(requires("agents:read"))
) -> OpenTeachingOut:
    found = await teaching.open_teaching(session, requested_by=principal.user_id)
    return OpenTeachingOut(teaching=_teaching_out(found) if found is not None else None)


@router.get(
    "/v1/kb/teach/{teaching_id}",
    response_model=TeachingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="One teaching and where it is",
)
async def read_teaching(
    teaching_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> TeachingOut:
    return _teaching_out(await teaching.get_teaching(session, teaching_id))


class SaveIn(Strict):
    items: list[TeachItemIO] = Field(min_length=1, max_length=30)
    #: The agent whose script receives the rules; required when any item is a rule.
    agent_id: UUID | None = None


class SavedOut(Strict):
    facts_added: int
    rules_added: int
    agent_id: UUID | None


@router.post(
    "/v1/kb/teach/{teaching_id}/save",
    response_model=SavedOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Keep the reviewed facts and rules",
    description=(
        "Facts join the business's knowledge and reach every agent without review. Rules "
        "wait in the chosen agent's script until the owner adds them and puts the script live."
    ),
)
async def save_teaching(
    teaching_id: UUID,
    payload: SaveIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> SavedOut:
    assert principal.tenant_id is not None
    saved = await teaching.save(
        session,
        tenant_id=principal.tenant_id,
        teaching_id=teaching_id,
        items=[
            teaching.TeachItem(kind=i.kind, text=i.text, pinned=i.pinned and i.kind == "fact")
            for i in payload.items
        ],
        agent_id=payload.agent_id,
        saved_by=principal.user_id,
        client_user_id=principal.client_user_id,
        auto_approve=_auto_approve(principal),
    )
    await write_audit(
        session,
        action="kb_teaching.save",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kb_teaching",
        object_id=str(teaching_id),
        ip=client_request_ip(request),
        summary={
            "facts": saved.facts_added,
            "rules": saved.rules_added,
            "agent_id": str(saved.agent_id) if saved.agent_id else None,
        },
    )
    return SavedOut(
        facts_added=saved.facts_added, rules_added=saved.rules_added, agent_id=saved.agent_id
    )


@router.post(
    "/v1/kb/teach/{teaching_id}/discard",
    response_model=TeachingOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Throw a teaching away without saving anything",
)
async def discard_teaching(
    teaching_id: UUID,
    session: Session,
    _: Principal = Depends(requires_kb_curation()),
) -> TeachingOut:
    return _teaching_out(await teaching.discard(session, teaching_id))


# --- where it struggled ------------------------------------------------------------


class StruggleOut(Strict):
    id: UUID
    #: `didnt_know` · `put_off` (pushed to a call back or WhatsApp) · `unanswered` ·
    #: `needed_you` (the call ended needing the owner).
    kind: str
    gap_id: UUID | None
    agent_id: UUID
    agent_name: str | None
    topic: str
    #: Redacted, like every quote on this surface.
    question: str | None
    answer: str | None
    times: int
    calls: int
    last_call_id: UUID | None
    last_seen_at: datetime


@router.get(
    "/v1/kb/struggles",
    response_model=list[StruggleOut],
    openapi_extra=permission_meta("calls:read"),
    summary="Where the agents struggled on real calls, found from the calls",
)
async def where_it_struggled(
    session: Session,
    agent_id: UUID | None = Query(default=None),
    _: Principal = Depends(requires("calls:read")),
) -> list[StruggleOut]:
    return [
        StruggleOut.model_validate(s, from_attributes=True)
        for s in await struggles.list_struggles(session, agent_id=agent_id)
    ]


# --- questions to answer (D-893) ---------------------------------------------------


class TeachQuestionOut(Strict):
    #: The topic key; the path segment the answer and dismiss routes take.
    key: str
    #: The question in plain words.
    question: str
    topic: str
    #: `callers` (asked on real calls) · `practice` (practice callers ask it and nothing
    #: known answers it) · `setup` (the business profile leaves it open).
    why: Literal["callers", "practice", "setup"]
    #: Calls on which a caller asked it; 0 for practice and setup questions.
    callers: int
    times: int
    agent_ids: list[UUID]
    latest_call_id: UUID | None
    latest_at: datetime | None
    #: What a caller said, redacted like every quote on this surface.
    example: str | None
    #: An answer drafted from what the business gave us; only with its source.
    draft: str | None
    #: `profile` · `fact` · `answer` · `file`.
    draft_source_kind: Literal["profile", "fact", "answer", "file"] | None
    #: The source as the owner reads it ("Your business profile", a file's name).
    draft_source_label: str | None
    #: A draft is being written; read again shortly.
    drafting: bool


class TeachQuestionsOut(Strict):
    items: list[TeachQuestionOut]
    open_count: int


def _question_out(q: questions.Question) -> TeachQuestionOut:
    return TeachQuestionOut(
        key=q.key,
        question=q.question,
        topic=q.topic,
        why=q.why,
        callers=q.callers,
        times=q.times,
        agent_ids=list(q.agent_ids),
        latest_call_id=q.latest_call_id,
        latest_at=q.latest_at,
        example=q.example,
        draft=q.draft,
        draft_source_kind=q.draft_source_kind,
        draft_source_label=q.draft_source_label,
        drafting=q.drafting,
    )


@router.get(
    "/v1/teach/questions",
    response_model=TeachQuestionsOut,
    openapi_extra=permission_meta("calls:read"),
    summary="The questions the agents need answered, most-asked first, with drafted answers",
    description=(
        "Open knowledge gaps grouped by topic, the facts practice callers need, and what the "
        "business profile leaves open, merged by topic. `agent_id` narrows the callers' "
        "questions to one agent; the rest belong to the account. A read queues drafts for "
        "questions whose inputs changed (`drafting`), except in a view-as session."
    ),
)
async def list_teach_questions(
    session: Session,
    agent_id: UUID | None = Query(default=None),
    principal: Principal = Depends(requires("calls:read")),
) -> TeachQuestionsOut:
    assert principal.tenant_id is not None
    if agent_id is not None:
        await assert_agent_visible(session, agent_id)
    found = await questions.list_questions(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        queue_drafts=not principal.impersonating,
    )
    return TeachQuestionsOut(
        items=[_question_out(q) for q in found.items], open_count=found.open_count
    )


class AnswerQuestionIn(Strict):
    answer: str = Field(min_length=1, max_length=MAX_FACT_CHARS)


class DismissQuestionIn(Strict):
    #: The owner's own note ("we do not do home visits").
    reason: str | None = Field(default=None, max_length=MAX_DISMISS_REASON_CHARS)


class QuestionSettledOut(Strict):
    key: str
    #: The fact the answer became; null for a dismissal or words the agents already knew.
    fact_id: UUID | None
    gaps_closed: int


async def _audit_question(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    settled: questions.Settled,
    action: str,
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="teach_question",
        object_id=settled.key,
        ip=client_request_ip(request),
        summary={"gaps_closed": settled.gaps_closed, "fact_added": settled.fact_id is not None},
    )


@router.post(
    "/v1/teach/questions/{key}/answer",
    response_model=QuestionSettledOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Answer a question: it becomes a fact every agent knows, and the question closes",
)
async def answer_teach_question(
    key: str,
    payload: AnswerQuestionIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> QuestionSettledOut:
    assert principal.tenant_id is not None
    settled = await questions.answer_question(
        session,
        tenant_id=principal.tenant_id,
        key=key,
        answer=payload.answer,
        saved_by=principal.user_id,
        client_user_id=principal.client_user_id,
        auto_approve=_auto_approve(principal),
    )
    await _audit_question(session, request, principal, settled, "teach_question.answer")
    return QuestionSettledOut(
        key=settled.key, fact_id=settled.fact_id, gaps_closed=settled.gaps_closed
    )


@router.post(
    "/v1/teach/questions/{key}/dismiss",
    response_model=QuestionSettledOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Not something we answer: the question leaves the list",
)
async def dismiss_teach_question(
    key: str,
    payload: DismissQuestionIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires_kb_curation()),
) -> QuestionSettledOut:
    assert principal.tenant_id is not None
    settled = await questions.dismiss_question(
        session,
        tenant_id=principal.tenant_id,
        key=key,
        reason=payload.reason,
        client_user_id=principal.client_user_id,
    )
    await _audit_question(session, request, principal, settled, "teach_question.dismiss")
    return QuestionSettledOut(key=settled.key, fact_id=None, gaps_closed=settled.gaps_closed)


# --- rules waiting for a script ----------------------------------------------------


class RuleOut(Strict):
    id: UUID
    agent_id: UUID
    text: str
    #: `pending` · `applied` · `dismissed`.
    status: str
    created_at: datetime


@router.get(
    "/v1/agents/{agent_id}/script/proposed-rules",
    response_model=list[RuleOut],
    openapi_extra=permission_meta("agents:read"),
    summary="Rules the owner taught that are waiting to be added to this agent's script",
)
async def list_proposed_rules(
    agent_id: UUID,
    session: Session,
    status: Literal["pending", "applied", "dismissed"] = Query(default="pending"),
    _: Principal = Depends(requires("agents:read")),
) -> list[RuleOut]:
    # A neighbour's agent is a 404, not an empty list: one answer for every `{agent_id}`.
    await assert_agent_visible(session, agent_id)
    return [
        RuleOut.model_validate(r, from_attributes=True)
        for r in await rules.list_rules(session, agent_id=agent_id, status=status)
    ]


class ResolveRuleIn(Strict):
    #: `applied` once the rule is written into the script; `dismissed` to drop it.
    status: Literal["applied", "dismissed"]


@router.post(
    "/v1/agents/{agent_id}/script/proposed-rules/{rule_id}",
    response_model=RuleOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Mark a waiting rule as added to the script, or dismiss it",
)
async def resolve_proposed_rule(
    agent_id: UUID,
    rule_id: UUID,
    payload: ResolveRuleIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> RuleOut:
    resolved = await rules.resolve_rule(
        session,
        agent_id=agent_id,
        rule_id=rule_id,
        status=payload.status,
        resolved_by=principal.user_id,
    )
    await write_audit(
        session,
        action=f"agent_rule.{payload.status}",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent_rule_proposal",
        object_id=str(rule_id),
        ip=client_request_ip(request),
        summary={"agent_id": str(agent_id)},
    )
    return RuleOut.model_validate(resolved, from_attributes=True)


# --- saved tests -------------------------------------------------------------------


class TestTurnOut(Strict):
    said: str
    reply: str
    looked_up_knowledge: bool = False
    cut_short: bool = False


class TestCaseOut(Strict):
    id: UUID
    agent_id: UUID
    source_call_id: UUID | None
    title: str
    caller_lines: list[str]
    expected: str
    #: `idle` · `queued` · `running`.
    status: str
    #: What the live agent said to each line on the last run.
    last_result: list[TestTurnOut] | None
    last_error: str | None
    last_run_at: datetime | None
    #: The live script version the last run talked to.
    last_prompt_version: int | None
    created_at: datetime


def _case_out(case: test_cases.TestCase) -> TestCaseOut:
    return TestCaseOut(
        id=case.id,
        agent_id=case.agent_id,
        source_call_id=case.source_call_id,
        title=case.title,
        caller_lines=case.caller_lines,
        expected=case.expected,
        status=case.status,
        last_result=(
            [TestTurnOut.model_validate(turn) for turn in case.last_result]
            if case.last_result is not None
            else None
        ),
        last_error=case.last_error,
        last_run_at=case.last_run_at,
        last_prompt_version=case.last_prompt_version,
        created_at=case.created_at,
    )


class TestCasesOut(Strict):
    cases: list[TestCaseOut]
    available: bool
    unavailable_reason: str | None
    #: The live script version now, so the screen can say a result is out of date.
    live_version: int | None
    cost_note: str


async def _cases_out(session: AsyncSession, agent_id: UUID) -> TestCasesOut:
    ready = await readiness(session, agent_id)
    return TestCasesOut(
        cases=[_case_out(c) for c in await test_cases.list_cases(session, agent_id)],
        available=ready.available,
        unavailable_reason=ready.reason,
        live_version=ready.live_version,
        cost_note=try_chat.COST_NOTE,
    )


@router.get(
    "/v1/agents/{agent_id}/test-cases",
    response_model=TestCasesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="This agent's saved tests and their last answers",
)
async def list_test_cases(
    agent_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> TestCasesOut:
    return await _cases_out(session, agent_id)


class TestCaseIn(Strict):
    title: str = Field(default="", max_length=120)
    caller_lines: list[str] = Field(min_length=1, max_length=MAX_CASE_LINES)
    expected: str = Field(min_length=1, max_length=MAX_CASE_EXPECTED_CHARS)


@router.post(
    "/v1/agents/{agent_id}/test-cases",
    response_model=TestCaseOut,
    status_code=201,
    openapi_extra=permission_meta("agents:write"),
    summary="Save a test written by hand",
)
async def create_test_case(
    agent_id: UUID,
    payload: TestCaseIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write")),
) -> TestCaseOut:
    assert principal.tenant_id is not None
    case = await test_cases.create_case(
        session,
        tenant_id=principal.tenant_id,
        call_id=None,
        agent_id=agent_id,
        title=payload.title,
        caller_lines=[line[:MAX_CASE_LINE_CHARS] for line in payload.caller_lines],
        expected=payload.expected,
        created_by=principal.user_id,
    )
    await _audit_case(session, request, principal, case, "agent_test_case.create")
    return _case_out(case)


async def _audit_case(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    case: test_cases.TestCase,
    action: str,
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent_test_case",
        object_id=str(case.id),
        ip=client_request_ip(request),
        summary={
            "agent_id": str(case.agent_id),
            "call_id": str(case.source_call_id) if case.source_call_id else None,
            "lines": len(case.caller_lines),
        },
    )


@router.delete(
    "/v1/agents/{agent_id}/test-cases/{case_id}",
    status_code=204,
    openapi_extra=permission_meta("agents:write"),
    summary="Delete a saved test",
)
async def delete_test_case(
    agent_id: UUID,
    case_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write")),
) -> None:
    await test_cases.delete_case(session, agent_id=agent_id, case_id=case_id)
    await write_audit(
        session,
        action="agent_test_case.delete",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent_test_case",
        object_id=str(case_id),
        ip=client_request_ip(request),
        summary={"agent_id": str(agent_id)},
    )


@router.post(
    "/v1/agents/{agent_id}/test-cases/run",
    response_model=TestCasesOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Run every saved test against the live agent",
    description=(
        "Runs in the background, a few seconds per caller line. Poll "
        "`GET /v1/agents/{agent_id}/test-cases` while any test is `queued` or `running`."
    ),
)
async def run_test_cases(
    agent_id: UUID,
    session: Session,
    principal: Principal = Depends(requires("agents:write")),
) -> TestCasesOut:
    assert principal.tenant_id is not None
    # A run is up to 20 tests of six caller lines each against the live agent, so it
    # spends the way a try-chat does: withheld from view-as and gated on the AI allowance.
    # The agent is resolved first so a neighbour's id is a 404, never a quota answer.
    assert_view_as_may(principal, "billing.ai_assist")
    await assert_agent_visible(session, agent_id)
    await require_ai_assist(session, tenant_id=principal.tenant_id)
    await test_cases.request_run(session, tenant_id=principal.tenant_id, agent_id=agent_id)
    return await _cases_out(session, agent_id)


class PendingCaseOut(Strict):
    expected: str | None
    title: str | None


class CaseDraftOut(Strict):
    call_id: UUID
    agent_id: UUID
    agent_name: str | None
    #: The caller's lines from the call, redacted, at most six.
    caller_lines: list[str]
    title: str
    #: What Pip prepared for this person from this call, or null (D-822). The form opens
    #: with it; nothing is saved until the person saves the form.
    pending: PendingCaseOut | None


@router.get(
    "/v1/calls/{call_id}/test-case-draft",
    response_model=CaseDraftOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Start a test from this call: its caller lines, redacted",
)
async def draft_test_case(
    call_id: UUID, session: Session, principal: Principal = Depends(requires("calls:read"))
) -> CaseDraftOut:
    draft = await test_cases.draft_from_call(session, call_id)
    pending = (
        await test_cases.read_pending(session, call_id=call_id, user_id=principal.user_id)
        if principal.user_id is not None
        else None
    )
    return CaseDraftOut(
        call_id=draft.call_id,
        agent_id=draft.agent_id,
        agent_name=draft.agent_name,
        caller_lines=draft.caller_lines,
        title=draft.title,
        pending=(
            PendingCaseOut(expected=pending.expected, title=pending.title)
            if pending is not None
            else None
        ),
    )


@router.delete(
    "/v1/calls/{call_id}/test-case-draft/pending",
    status_code=204,
    openapi_extra=permission_meta("agents:write"),
    summary="Discard the test Pip prepared from this call",
)
async def discard_prepared_test_case(
    call_id: UUID,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write")),
) -> None:
    assert principal.user_id is not None
    if not await test_cases.discard_pending(session, call_id=call_id, user_id=principal.user_id):
        raise ProblemError.not_found("Prepared test")
    await write_audit(
        session,
        action="agent_test_case.prepared_discard",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="call",
        object_id=str(call_id),
        ip=client_request_ip(request),
        summary={},
    )


@router.post(
    "/v1/calls/{call_id}/test-case",
    response_model=TestCaseOut,
    status_code=201,
    openapi_extra=permission_meta("agents:write"),
    summary="Make this call a test for its agent",
)
async def make_call_a_test(
    call_id: UUID,
    payload: TestCaseIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("agents:write")),
) -> TestCaseOut:
    assert principal.tenant_id is not None
    case = await test_cases.create_case(
        session,
        tenant_id=principal.tenant_id,
        call_id=call_id,
        agent_id=None,
        title=payload.title,
        caller_lines=payload.caller_lines,
        expected=payload.expected,
        created_by=principal.user_id,
    )
    await _audit_case(session, request, principal, case, "agent_test_case.create")
    return _case_out(case)


# --- try it --------------------------------------------------------------------------


class TryChatIn(Strict):
    message: str = Field(min_length=1, max_length=try_chat.MAX_MESSAGE_CHARS)
    #: The `session` a previous reply answered with, to continue the same conversation.
    session: str | None = Field(default=None, max_length=200)


class TryChatOut(Strict):
    session: str
    reply: str
    looked_up_knowledge: bool
    cut_short: bool
    cost_note: str


@router.post(
    "/v1/agents/{agent_id}/try-chat",
    response_model=TryChatOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Chat with the live agent in text, as a caller would",
)
async def try_chat_send(
    agent_id: UUID,
    payload: TryChatIn,
    session: Session,
    principal: Principal = Depends(requires("agents:write")),
) -> TryChatOut:
    assert principal.tenant_id is not None
    # A chat spends on the client's account the way the AI helper does (founder decision 5).
    assert_view_as_may(principal, "billing.ai_assist")
    reply = await try_chat.send(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        message=payload.message,
        chat_session=payload.session,
    )
    return TryChatOut(
        session=reply.session,
        reply=reply.reply,
        looked_up_knowledge=reply.looked_up_knowledge,
        cut_short=reply.cut_short,
        cost_note=try_chat.COST_NOTE,
    )


__all__ = ["router"]
