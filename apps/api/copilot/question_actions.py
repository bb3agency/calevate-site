"""Pip's knowledge and training actions (D-893 lane L5, PIP-AGENT-PLAN §4 items 18, 20, 21).

Each calls the function the page's own button calls:

* `knowledge_question_settle` — confirm, `kb:write` with the curation switch:
  `teach/questions.answer_question`, or `dismiss_question` when `answer` is null.
* `knowledge_fact_change` — confirm, `kb:write`: `teach/facts.update_fact` / `remove_fact`
  and `teach/pinned.reorder`.
* `agent_tests_run` — confirm, `org:manage`: `agents/test_conversations.request_run` after
  `require_ai_assist`, as the Training tab's Run button.
* `agent_test_add` — immediate with Undo, `agents:write`: `teach/test_cases.create_case`.

Answering a question and changing a fact are `confirm`: what they change is said to callers
by every live agent on its next call, and a sentence said to a caller cannot be taken back
(the reason `knowledge_facts_pin` is confirm). A test run spends the AI allowance. A saved
test reaches no caller and spends nothing until it is run, and Undo deletes it exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import test_conversations
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.copilot.actions import (
    DOES_IT,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    Undo,
    UndoRecord,
    UndoRefusedError,
    WriteRefusedError,
    action_schema,
    actor_realm,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible
from apps.api.kb import store as kb_store
from apps.api.kb.curation import CURATE_PERMISSION, goes_live_without_review
from apps.api.teach import facts as fact_store
from apps.api.teach import pinned as pinned_store
from apps.api.teach import questions, test_cases
from apps.api.teach.models import (
    MAX_CASE_EXPECTED_CHARS,
    MAX_CASE_LINE_CHARS,
    MAX_CASE_LINES,
    MAX_FACT_CHARS,
    MAX_PINNED_ANSWER_CHARS,
    MAX_QUESTION_KEY_CHARS,
)
from apps.workers.redaction import redact

_NULLABLE_TEXT: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_WHERE_KNOWLEDGE: Final = "on What your agents know"


def _auto_approve(actor: ToolActor) -> bool:
    return goes_live_without_review(realm=actor_realm(actor), impersonating=actor.impersonating)


def _client_user_id(actor: ToolActor) -> UUID | None:
    # `settled_by` and `knowledge_gaps.resolved_by` hold a `users.id`; in a view-as session
    # `actor.user_id` is an `admin_users.id`, so an operator is recorded as nobody, as
    # `Principal.client_user_id` answers for the page's own buttons.
    return None if actor.impersonating else actor.user_id


def _owner_words(value: str, *, limit: int, what: str) -> str:
    cleaned = " ".join(strip_invisible(value).split())
    if not cleaned:
        raise WriteRefusedError(f"`{what}` was empty, so ask the person for it")
    if len(cleaned) > limit:
        raise WriteRefusedError(f"`{what}` is longer than {limit} characters, so shorten it")
    if redact(cleaned).changed:
        # The value is never named: this reason reaches a log line and the next prompt.
        raise WriteRefusedError(
            f"`{what}` contains something shaped like a phone number, an email address or an "
            "identity number; the person can add it themselves on the page"
        )
    return cleaned


# --- knowledge_question_settle ------------------------------------------------------------


class _SettleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_key: Annotated[str, Field(max_length=MAX_QUESTION_KEY_CHARS)]
    answer: Annotated[str, Field(max_length=MAX_FACT_CHARS + 1)] | None


async def _plan_settle(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_SettleArgs, args)
    try:
        question = await questions.find_question(
            session, tenant_id=actor.tenant_id, key=parsed.question_key
        )
    except ProblemError as missing:
        raise WriteRefusedError(
            "that question is not waiting any more; read `knowledge_questions` again"
        ) from missing
    if parsed.answer is None:
        return Plan(
            object_id=question.key,
            title="Not something we answer",
            summary=f"“{question.question}” leaves the list of questions to answer.",
            current=None,
            proposed="Dismissed",
            cost=None,
            reversal="If a caller asks it again, it comes back on the list.",
            args={"question_key": question.key, "answer": None},
        )
    answer = _owner_words(parsed.answer, limit=MAX_FACT_CHARS, what="answer")
    return Plan(
        object_id=question.key,
        title="Answer this question",
        summary=(
            f"“{question.question}” is answered, and every agent uses the answer from its "
            "next call."
        ),
        current=None,
        proposed=answer,
        cost=None,
        reversal=f"Edit or remove the fact {_WHERE_KNOWLEDGE} at any time.",
        args={"question_key": question.key, "answer": answer},
    )


async def _execute_settle(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_SettleArgs, args)
    if parsed.answer is None:
        settled = await questions.dismiss_question(
            session,
            tenant_id=actor.tenant_id,
            key=parsed.question_key,
            reason=None,
            client_user_id=_client_user_id(actor),
        )
        detail = "Dismissed. It comes back only if a caller asks it again."
    else:
        settled = await questions.answer_question(
            session,
            tenant_id=actor.tenant_id,
            key=parsed.question_key,
            answer=parsed.answer,
            saved_by=actor.user_id,
            client_user_id=_client_user_id(actor),
            auto_approve=_auto_approve(actor),
        )
        detail = "Saved. Your agents use the answer from their next call."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={
            "question_key": settled.key,
            "answered": parsed.answer is not None,
            "gaps_closed": settled.gaps_closed,
        },
        object_id=settled.key,
    )


KNOWLEDGE_QUESTION_SETTLE: Final = ActionTool(
    name="knowledge_question_settle",
    tier="confirm",
    undo=None,
    permission=CURATE_PERMISSION,
    object_type="teach_question",
    audit_action="teach_question.answer",
    where=_WHERE_KNOWLEDGE,
    schema=action_schema(
        "knowledge_question_settle",
        "Answer a `knowledge_questions` question in the person's words, or null to dismiss "
        "it. Never invent; use a draft only if they accept it." + PROPOSES_ONLY,
        {"question_key": {"type": "string"}, "answer": _NULLABLE_TEXT},
    ),
    plan=_plan_settle,
    execute=_execute_settle,
)


# --- knowledge_fact_change ----------------------------------------------------------------

FactChange = Literal["edit", "pin", "unpin", "move", "remove"]


class _FactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: UUID
    change: FactChange
    text: Annotated[str, Field(max_length=MAX_PINNED_ANSWER_CHARS + 1)] | None
    position: Annotated[int, Field(ge=1, le=300)] | None

    @field_validator("fact_id", mode="before")
    @classmethod
    def _fact_ref(cls, value: object) -> object:
        # `knowledge_sources` names a fact by its store reference (`fact:<id>`,
        # `pinned_fact:<id>`); a bare id is accepted too.
        if isinstance(value, str) and ":" in value:
            if not kb_store.is_ref(value):
                raise ValueError("not a reference from knowledge_sources")
            kind, item_id = kb_store.parse_ref(value)
            if kind not in ("fact", "pinned_fact"):
                raise ValueError("not a fact; facts are the fact: items in knowledge_sources")
            return item_id
        return value


async def _fact(session: AsyncSession, fact_id: UUID) -> fact_store.Fact:
    for fact in await fact_store.list_facts(session):
        if fact.id == fact_id:
            return fact
    raise WriteRefusedError("no fact has that id; read `knowledge_sources` for the facts")


async def _plan_fact(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_FactArgs, args)
    fact = await _fact(session, parsed.fact_id)
    canonical: dict[str, Any] = {
        "fact_id": str(fact.id),
        "change": parsed.change,
        "text": None,
        "position": None,
    }
    proposed: str
    if parsed.change == "edit":
        if parsed.text is None:
            raise WriteRefusedError("an edit needs `text`, the new words")
        limit = MAX_PINNED_ANSWER_CHARS if fact.pinned else MAX_FACT_CHARS
        canonical["text"] = proposed = _owner_words(parsed.text, limit=limit, what="text")
        title = "Change this fact"
    elif parsed.change == "pin":
        if fact.pinned:
            raise WriteRefusedError("that fact is already pinned")
        title, proposed = "Pin this fact", "Said on every call by every agent"
    elif parsed.change == "unpin":
        if not fact.pinned:
            raise WriteRefusedError("that fact is not pinned")
        if len(fact.text) > MAX_FACT_CHARS:
            raise WriteRefusedError(
                f"that fact is longer than {MAX_FACT_CHARS} characters, so shorten it first"
            )
        title, proposed = "Unpin this fact", "Looked up when a caller asks"
    elif parsed.change == "move":
        if not fact.pinned:
            raise WriteRefusedError("only pinned facts have an order; pin it first")
        if parsed.position is None:
            raise WriteRefusedError("a move needs `position`, 1 for first")
        pinned = await pinned_store.list_pinned(session)
        canonical["position"] = min(parsed.position, len(pinned))
        title, proposed = "Move this pinned fact", f"Position {canonical['position']}"
    else:
        title, proposed = "Remove this fact", "Removed from every agent"
    return Plan(
        object_id=str(fact.id),
        title=title,
        summary="Every agent uses the change from its next call.",
        current=fact.text,
        proposed=proposed,
        cost=None,
        reversal=(
            "A removed fact is gone; add it again to bring it back."
            if parsed.change == "remove"
            else f"Change it back {_WHERE_KNOWLEDGE} at any time."
        ),
        args=canonical,
    )


async def _execute_fact(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_FactArgs, args)
    common = {"tenant_id": actor.tenant_id, "fact_id": parsed.fact_id}
    if parsed.change == "remove":
        await fact_store.remove_fact(
            session, **common, removed_by=actor.user_id, auto_approve=_auto_approve(actor)
        )
    elif parsed.change == "move":
        order = [f.id for f in await pinned_store.list_pinned(session) if f.id != parsed.fact_id]
        order.insert((parsed.position or 1) - 1, parsed.fact_id)
        await pinned_store.reorder(session, tenant_id=actor.tenant_id, ids=order)
    else:
        await fact_store.update_fact(
            session,
            **common,
            text_value=parsed.text if parsed.change == "edit" else None,
            question=None,
            pinned={"pin": True, "unpin": False}.get(parsed.change),
            edited_by=actor.user_id,
            auto_approve=_auto_approve(actor),
        )
    return Executed(
        applied=True,
        detail="Done. Every agent uses it from its next call.",
        audit_summary={"fact_id": str(parsed.fact_id), "change": parsed.change},
    )


KNOWLEDGE_FACT_CHANGE: Final = ActionTool(
    name="knowledge_fact_change",
    tier="confirm",
    undo=None,
    permission=CURATE_PERMISSION,
    object_type="kb_fact",
    audit_action="kb_fact.edit",
    where=_WHERE_KNOWLEDGE,
    schema=action_schema(
        "knowledge_fact_change",
        "Change one fact from `knowledge_sources`: edit, pin (said every call), unpin, move "
        "a pinned one, or remove." + PROPOSES_ONLY,
        {
            "fact_id": {"type": "string", "description": "Its fact: ref."},
            "change": {"type": "string", "enum": ["edit", "pin", "unpin", "move", "remove"]},
            "text": {**_NULLABLE_TEXT, "description": "For edit."},
            "position": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "For move; 1 is first.",
            },
        },
    ),
    plan=_plan_fact,
    execute=_execute_fact,
)


# --- agent_tests_run ----------------------------------------------------------------------


class _RunArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    again: bool


async def _plan_run(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    parsed = parse_args(_RunArgs, args)
    await assert_visible(session, "agent", parsed.agent_id)
    ready = await test_conversations.readiness(session, parsed.agent_id)
    if not ready.available:
        raise WriteRefusedError(ready.reason or "this agent cannot be tested yet")
    retest_of: UUID | None = None
    if parsed.again:
        runs = await test_conversations.recent_runs(session, parsed.agent_id)
        if not runs:
            raise WriteRefusedError("no test has finished yet, so run a new set (again false)")
        retest_of = runs[0].id
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    return Plan(
        object_id=str(parsed.agent_id),
        title="Test again" if parsed.again else "Run the practice tests",
        summary=(
            "The same tests are asked again, so you can compare."
            if parsed.again
            else "A new set: your saved tests and what real callers asked."
        ),
        current=None,
        proposed="Results on the agent's Training tab in a few minutes.",
        cost="Uses your account's AI help allowance.",
        reversal="Nothing about the agent changes; a test only reads its answers.",
        args={
            "agent_id": str(parsed.agent_id),
            "again": parsed.again,
            "retest_of": str(retest_of) if retest_of else None,
        },
    )


async def _execute_run(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    agent_id = UUID(str(args["agent_id"]))
    retest_of = UUID(str(args["retest_of"])) if args.get("retest_of") else None
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    run = await test_conversations.request_run(
        session,
        tenant_id=actor.tenant_id,
        agent_id=agent_id,
        requested_by=actor.user_id,
        retest_of=retest_of,
    )
    return Executed(
        applied=True,
        detail="The tests are running. Results appear on the agent's Training tab.",
        audit_summary={
            "run_id": str(run.id),
            "retest": retest_of is not None,
            "set_version": run.set_version,
        },
    )


AGENT_TESTS_RUN: Final = ActionTool(
    name="agent_tests_run",
    tier="confirm",
    undo=None,
    # `POST /v1/agents/{id}/script/tests`'s permission (the Training tab's Run button).
    permission="org:manage",
    object_type="agent",
    audit_action="agent.tests_requested",
    where="on the agent's Training tab",
    schema=action_schema(
        "agent_tests_run",
        "Run an agent's practice tests; again true repeats the last set to compare."
        + PROPOSES_ONLY,
        {"agent_id": {"type": "string"}, "again": {"type": "boolean"}},
    ),
    plan=_plan_run,
    execute=_execute_run,
)


# --- agent_test_add -----------------------------------------------------------------------


class _AddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    caller_lines: Annotated[
        list[Annotated[str, Field(max_length=MAX_CASE_LINE_CHARS + 1)]],
        Field(min_length=1, max_length=MAX_CASE_LINES),
    ]
    expected: Annotated[str, Field(max_length=MAX_CASE_EXPECTED_CHARS + 1)]
    title: Annotated[str, Field(max_length=test_cases.MAX_TITLE_CHARS + 1)] | None


async def _plan_add(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_AddArgs, args)
    await assert_visible(session, "agent", parsed.agent_id)
    if await test_cases.saved_count(session, parsed.agent_id) >= test_cases.MAX_CASES_PER_AGENT:
        raise WriteRefusedError(
            f"this agent already keeps {test_cases.MAX_CASES_PER_AGENT} saved tests, so one "
            "must be deleted on its Training tab first"
        )
    lines = [
        _owner_words(line, limit=MAX_CASE_LINE_CHARS, what="caller_lines")
        for line in parsed.caller_lines
    ]
    expected = _owner_words(parsed.expected, limit=MAX_CASE_EXPECTED_CHARS, what="expected")
    title = test_cases.written_title(strip_invisible(parsed.title or ""))
    return Plan(
        object_id=str(parsed.agent_id),
        title="Save a practice test",
        summary="Saved with the agent's tests; it runs with the next practice run.",
        current=None,
        proposed=expected,
        cost=None,
        reversal="Undo deletes it; you can also delete it on the Training tab.",
        args={
            "agent_id": str(parsed.agent_id),
            "caller_lines": lines,
            "expected": expected,
            "title": title or None,
        },
    )


async def _execute_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_AddArgs, args)
    case = await test_cases.create_case(
        session,
        tenant_id=actor.tenant_id,
        call_id=None,
        agent_id=parsed.agent_id,
        # No title: `create_case` names it from the first caller line.
        title=parsed.title or "",
        caller_lines=parsed.caller_lines,
        expected=parsed.expected,
        created_by=actor.user_id,
    )
    return Executed(
        applied=True,
        detail="Saved with this agent's tests on its Training tab.",
        audit_summary={"agent_id": str(parsed.agent_id), "case_id": str(case.id)},
        object_id=str(case.id),
    )


async def _capture_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    case_id = args.get("agent_test_case_id")
    if case_id is None:
        return {"exists": False}
    row = (
        await session.execute(
            text("SELECT expected, status FROM agent_test_cases WHERE id = :id"),
            {"id": UUID(str(case_id))},
        )
    ).first()
    return {"exists": row is not None, "status": None if row is None else str(row[1])}


async def _invert_add(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    del actor
    case_id = UUID(record.object_id)
    agent_id = UUID(str(record.args["agent_id"]))
    row = (
        await session.execute(
            text("SELECT status FROM agent_test_cases WHERE id = :id FOR UPDATE"),
            {"id": case_id},
        )
    ).first()
    if row is None:
        raise UndoRefusedError("that test was already deleted")
    if str(row[0]) != "idle":
        raise UndoRefusedError("that test is running now, so it was kept")
    await test_cases.delete_case(session, agent_id=agent_id, case_id=case_id)
    return "The test is deleted."


AGENT_TEST_ADD: Final = ActionTool(
    name="agent_test_add",
    tier="immediate",
    undo=Undo(capture=_capture_add, invert=_invert_add),
    # `POST /v1/agents/{agent_id}/test-cases`'s permission.
    permission="agents:write",
    object_type="agent_test_case",
    audit_action="agent_test_case.create",
    where="on the agent's Training tab",
    schema=action_schema(
        "agent_test_add",
        "Save a hand-written practice test: caller lines and what the agent should do. "
        "From a call: `call_test_prepare`." + DOES_IT,
        {
            "agent_id": {"type": "string"},
            "caller_lines": {"type": "array", "items": {"type": "string"}},
            "expected": {"type": "string"},
            "title": {**_NULLABLE_TEXT, "description": test_cases.TITLE_HINT},
        },
    ),
    plan=_plan_add,
    execute=_execute_add,
)

TRAINING_ACTIONS: Final[tuple[ActionTool, ...]] = (
    KNOWLEDGE_QUESTION_SETTLE,
    KNOWLEDGE_FACT_CHANGE,
    AGENT_TESTS_RUN,
    AGENT_TEST_ADD,
)

__all__ = ["TRAINING_ACTIONS"]
