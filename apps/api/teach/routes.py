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

from apps.api.agents.test_conversations import readiness
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.kb.curation import goes_live_without_review, requires_kb_curation
from apps.api.kb.uploads import classify_upload, file_extension
from apps.api.teach import facts as fact_store
from apps.api.teach import knows, rules, struggles, teaching, test_cases, try_chat
from apps.api.teach import pinned as pinned_store
from apps.api.teach.models import (
    MAX_CASE_EXPECTED_CHARS,
    MAX_CASE_LINE_CHARS,
    MAX_CASE_LINES,
    MAX_FACT_CHARS,
    MAX_PINNED_ANSWER_CHARS,
    MAX_PINNED_QUESTION_CHARS,
    MAX_RULE_CHARS,
    MAX_TEACH_WORDS,
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


class KnowsOut(Strict):
    facts: list[FactOut]
    #: Whether the newest facts have reached the agents: `none` · `live` · `publishing` ·
    #: `in_review`.
    facts_state: str
    items: list[KnownItemOut]


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


class TeachIn(Strict):
    words: str = Field(min_length=1, max_length=MAX_TEACH_WORDS)
    #: The struggle this answers, when opened from "Add the answer".
    gap_id: UUID | None = None


@router.post(
    "/v1/kb/teach",
    response_model=TeachingOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Teach in words; the AI sorts them into facts and rules for review",
    description=(
        "Sorting runs in the background and is counted against this month's AI help. Poll "
        "`GET /v1/kb/teach/{id}` until `status` is `ready`. When the AI help is used up the "
        "words come back unsorted for the owner to mark."
    ),
)
async def teach_words(
    payload: TeachIn,
    session: Session,
    principal: Principal = Depends(requires_kb_curation()),
) -> TeachingOut:
    assert principal.tenant_id is not None
    started = await teaching.start_teaching(
        session,
        tenant_id=principal.tenant_id,
        input_kind="text",
        words=teaching.clean_words(payload.words),
        gap_id=payload.gap_id,
        requested_by=principal.user_id,
    )
    return _teaching_out(started)


_READ_CHUNK_BYTES = 1024 * 1024


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """The upload, read a chunk at a time and refused one byte past `limit`."""
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
                remediation="Send a smaller photo, or add a long document under Files.",
                status=413,
            )
        chunks.append(chunk)
    if total == 0:
        raise ProblemError.business_rule("teach_upload_empty", "That file is empty.")
    return b"".join(chunks)


#: A photo is read by the OCR leg, whose own ceiling this is
#: (`calevate_shared.document_ingest.MAX_IMAGE_BYTES`).
_PHOTO_LIMIT = 12 * 1024 * 1024
_FILE_LIMIT = 20 * 1024 * 1024


@router.post(
    "/v1/kb/teach/upload",
    response_model=TeachingOut,
    status_code=201,
    openapi_extra=permission_meta("kb:write"),
    summary="Teach with a photo, a file or a voice note",
    description=(
        "`kind` is `photo` (a picture of a price list or menu), `file` (.docx, .txt, .csv, "
        ".xlsx) or `voice` (a voice note under 30 seconds). A voice note stops at `heard` "
        "so the owner can check the words; confirm them with `POST .../words`."
    ),
)
async def teach_upload(
    session: Session,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Literal["photo", "file", "voice"], Form()],
    gap_id: Annotated[UUID | None, Form()] = None,
    principal: Principal = Depends(requires_kb_curation()),
) -> TeachingOut:
    assert principal.tenant_id is not None
    filename = file.filename or "upload"
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if kind == "voice":
        if content_type not in teaching.VOICE_CONTENT_TYPES:
            raise ProblemError.business_rule(
                "teach_voice_kind",
                "We could not play that recording.",
                remediation="Record the voice note again here.",
            )
        data = await _read_bounded(file, teaching.MAX_VOICE_BYTES)
        suffix = content_type.split("/")[-1]
    else:
        source_kind = (
            "image"
            if kind == "photo"
            else classify_upload(filename=filename, content_type=content_type)
        )
        if source_kind == "pdf":
            raise ProblemError.business_rule(
                "teach_pdf",
                "A PDF goes to your agents as it is, so add it under Files instead.",
            )
        if source_kind == "image" and not content_type.startswith("image/"):
            raise ProblemError.business_rule("teach_photo_kind", "That is not a photo.")
        data = await _read_bounded(file, _PHOTO_LIMIT if source_kind == "image" else _FILE_LIMIT)
        suffix = file_extension(filename) or ("jpg" if source_kind == "image" else "bin")
    # Local import: `apps.workers.storage` holds the object-store client.
    from apps.workers.storage import kb_object_key, store_kb_object

    teaching_id = uuid7()
    key = kb_object_key(
        tenant_id=principal.tenant_id, upload_id=teaching_id, slot="teach", suffix=suffix[:8]
    )
    await store_kb_object(
        key=key, data=data, content_type=content_type or "application/octet-stream"
    )
    started = await teaching.start_teaching(
        session,
        tenant_id=principal.tenant_id,
        input_kind=kind,
        words=None,
        object_key=key,
        content_type=content_type,
        filename=filename[:200],
        gap_id=gap_id,
        teaching_id=teaching_id,
        requested_by=principal.user_id,
    )
    return _teaching_out(started)


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


class WordsIn(Strict):
    words: str = Field(min_length=1, max_length=MAX_TEACH_WORDS)


@router.post(
    "/v1/kb/teach/{teaching_id}/words",
    response_model=TeachingOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Confirm (or correct) the words heard in a voice note, then sort them",
)
async def confirm_words(
    teaching_id: UUID,
    payload: WordsIn,
    session: Session,
    principal: Principal = Depends(requires_kb_curation()),
) -> TeachingOut:
    assert principal.tenant_id is not None
    return _teaching_out(
        await teaching.confirm_words(
            session, tenant_id=principal.tenant_id, teaching_id=teaching_id, words=payload.words
        )
    )


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
    await test_cases.request_run(session, tenant_id=principal.tenant_id, agent_id=agent_id)
    return await _cases_out(session, agent_id)


class CaseDraftOut(Strict):
    call_id: UUID
    agent_id: UUID
    agent_name: str | None
    #: The caller's lines from the call, redacted, at most six.
    caller_lines: list[str]
    title: str


@router.get(
    "/v1/calls/{call_id}/test-case-draft",
    response_model=CaseDraftOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Start a test from this call: its caller lines, redacted",
)
async def draft_test_case(
    call_id: UUID, session: Session, _: Principal = Depends(requires("calls:read"))
) -> CaseDraftOut:
    return CaseDraftOut.model_validate(
        await test_cases.draft_from_call(session, call_id), from_attributes=True
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
