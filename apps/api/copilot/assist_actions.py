"""Pip's abilities that replaced the last standalone AI helpers (D-821).

Founder, 18 Oct 2026: Pip is the one AI assistant (D-820), and every AI request a person
makes on a screen is asked of Pip with "Let Pip do it", reviewed where its result lands.
D-820 moved the Script tab's helper and the Training tab's fixes (`script_actions.py`);
this module moves the rest, each through the same service function its old button called:

* `knowledge_teach` — the Knowledge base teach box. Pip sends the words (typed, or read off
  a photo or a file the person attached to Pip); `teach/teaching.start_teaching` queues the
  sort, and the facts and rules wait in the teach box for review.
* `lead_fields_draft` — the one AI draft of a custom business's lead details;
  `agents/lead_fields.request_draft` queues it, and the drafted fields wait on the Lead
  details screen for the owner to keep field by field (a review step it did not have).
* `call_summarise_again` — a second reading of one call over its REDACTED transcript;
  `crm/resummarise.second_reading`, shown in the confirmation and stored nowhere.
* `call_test_prepare` — "Make this call a test" (D-822). No model: it fills in the call
  page's test form (`teach/test_cases.write_pending`), which the person checks and saves.

The first three are `confirm`: the first and third spend the AI allowance, and the second is
a one-time request that can never be made again. The fourth is `immediate` with an Undo: it
saves no test, reaches no caller and spends nothing, and the form's own Save is the click.
Permissions are the old buttons' own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lead_fields
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
    parse_args,
)
from apps.api.copilot.identity import ASSISTANT_NAME
from apps.api.copilot.sanitize import strip_invisible
from apps.api.crm import resummarise
from apps.api.db.ownership import assert_visible
from apps.api.kb.curation import CURATE_PERMISSION
from apps.api.teach import teaching, test_cases
from apps.api.teach.models import MAX_CASE_EXPECTED_CHARS, MAX_TEACH_WORDS

_NULLABLE_TEXT: Final = {"anyOf": [{"type": "string"}, {"type": "null"}]}


# --- knowledge_teach ----------------------------------------------------------------------


class _TeachArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    words: Annotated[str, Field(max_length=MAX_TEACH_WORDS + 1)]
    gap_id: UUID | None


async def _plan_teach(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. The words are what the person checks on the card: what Pip read off a
    photo or a file is shown before anything is sorted."""
    del actor
    parsed = parse_args(_TeachArgs, args)
    words = strip_invisible(parsed.words).strip()
    if len(words) < teaching.MIN_TEACH_CHARS:
        raise WriteRefusedError("`words` was empty, so ask what the agents should know")
    if len(words) > MAX_TEACH_WORDS:
        raise WriteRefusedError(
            f"`words` is longer than {MAX_TEACH_WORDS} characters, so teach it in parts"
        )
    if parsed.gap_id is not None:
        found = (
            await session.execute(
                text("SELECT 1 FROM knowledge_gaps WHERE id = :id"), {"id": parsed.gap_id}
            )
        ).scalar()
        if found is None:
            raise WriteRefusedError(
                "`gap_id` is not a caller question of this account; use the one in SCREEN "
                "STATE, or null"
            )
    return Plan(
        object_id="",
        title="Teach your agents",
        summary=(
            f"{ASSISTANT_NAME} sorts these words into facts every agent gets and rules for "
            "one agent. They wait in the teach box on the Knowledge base screen for you to "
            "check before anything is saved."
        ),
        current=None,
        proposed=words,
        cost=(
            "Sorting uses your account's AI help allowance; when it is used up, the words "
            "come back unsorted for you to mark."
        ),
        reversal="Nothing is saved until you keep it in the teach box; discard it there.",
        args={"words": words, "gap_id": str(parsed.gap_id) if parsed.gap_id else None},
    )


async def _execute_teach(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`teaching.start_teaching` — what the teach box's own button called."""
    parsed = parse_args(_TeachArgs, args)
    started = await teaching.start_teaching(
        session,
        tenant_id=actor.tenant_id,
        input_kind="text",
        words=teaching.clean_words(parsed.words),
        gap_id=parsed.gap_id,
        requested_by=actor.user_id,
    )
    return Executed(
        applied=True,
        detail=(
            f"{ASSISTANT_NAME} is sorting it; it takes a few seconds. Check the facts and "
            "rules in the teach box on the Knowledge base screen: nothing is saved until "
            "you keep them."
        ),
        audit_summary={"teaching_id": str(started.id), "gap": parsed.gap_id is not None},
        object_id=str(started.id),
    )


KNOWLEDGE_TEACH: Final = ActionTool(
    name="knowledge_teach",
    tier="confirm",
    undo=None,
    # The teach box's own gate: `kb:write`, the role table plus the owner's curation switch.
    permission=CURATE_PERMISSION,
    object_type="kb_teaching",
    audit_action="kb_teaching.start",
    where="in the teach box on the Knowledge base screen",
    schema=action_schema(
        "knowledge_teach",
        "Teach the agents something about the business: the words are sorted into facts "
        "and rules the person keeps on the Knowledge base screen. Pass what they typed, or "
        "the words of a photo or file they attached, as written. For one fact to add to "
        "knowledge directly, use `propose_knowledge`." + PROPOSES_ONLY,
        {
            "words": {"type": "string", "description": "What the agents should know."},
            "gap_id": {
                **_NULLABLE_TEXT,
                "description": "The caller question being answered, from SCREEN STATE, or null.",
            },
        },
    ),
    plan=_plan_teach,
    execute=_execute_teach,
)


# --- lead_fields_draft --------------------------------------------------------------------


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def _plan_lead_fields(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. A business with a standard set, or one already drafted, is refused here
    with the reason, before any card."""
    parse_args(_NoArgs, args)
    vertical = await lead_fields.vertical_of(session, tenant_id=actor.tenant_id)
    if lead_fields.has_standard_set(vertical):
        raise WriteRefusedError(
            "this business has the standard lead details for its type, so there is nothing "
            "to draft; changes are made on the Lead details screen"
        )
    draft = await lead_fields.read_draft(session, tenant_id=actor.tenant_id)
    if draft is not None and draft.status in ("queued", "running"):
        raise WriteRefusedError(
            "the lead details are already being drafted, so tell the person they will "
            "appear on the Lead details screen"
        )
    if draft is not None and draft.status == "done":
        raise WriteRefusedError(
            "the lead details were already drafted once and are never drafted again"
            + ("" if draft.reviewed else "; the draft waits for review on the Lead details screen")
        )
    return Plan(
        object_id=str(actor.tenant_id),
        title="Draft your lead details",
        summary=(
            f"{ASSISTANT_NAME} drafts the details your agents write down about each caller, "
            "from your business details. They wait on the Lead details screen for you to "
            "keep the ones you want; no agent gets them before that."
        ),
        current=None,
        proposed="Lead details drafted from your business details",
        cost=None,
        reversal=(
            "They are drafted once and never again. Keep none of them if you do not want "
            "them, and change any of them afterwards."
        ),
        args={},
    )


async def _execute_lead_fields(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lead_fields.request_draft` — what the Lead details screen's button called."""
    parse_args(_NoArgs, args)
    draft = await lead_fields.request_draft(
        session, tenant_id=actor.tenant_id, requested_by=actor.user_id
    )
    return Executed(
        applied=True,
        detail=(
            f"{ASSISTANT_NAME} is drafting them; it usually takes under a minute. Keep the "
            "ones you want on the Lead details screen."
        ),
        audit_summary={"status": draft.status},
    )


LEAD_FIELDS_DRAFT: Final = ActionTool(
    name="lead_fields_draft",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="lead_fields.draft_requested",
    where="on the Lead details screen, under Settings & account",
    schema=action_schema(
        "lead_fields_draft",
        "Draft, once, the details a custom business's agents write down about each caller, "
        "from its business details; the owner keeps them field by field on the Lead "
        "details screen. Refused for a business type with standard details." + PROPOSES_ONLY,
        {},
    ),
    plan=_plan_lead_fields,
    execute=_execute_lead_fields,
)


# --- call_summarise_again -----------------------------------------------------------------


class _CallArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: UUID


async def _plan_second_reading(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY: the call, its redacted transcript, then the allowance — each refusal
    before the card, as the old card refused before its model call."""
    parsed = parse_args(_CallArgs, args)
    await assert_visible(session, "call", parsed.call_id)
    await resummarise.check_readable(session, parsed.call_id)
    await require_ai_assist(session, tenant_id=actor.tenant_id)
    return Plan(
        object_id=str(parsed.call_id),
        title="Summarise this call again",
        summary=(
            f"{ASSISTANT_NAME} reads this call's transcript with phone numbers and other "
            "identifiers hidden and writes a fresh summary. It is shown here once; the "
            "summary on file stays as it is."
        ),
        current=None,
        proposed="A second summary of this call",
        cost="Uses your account's AI help allowance.",
        reversal="Nothing on file changes, and the new summary is not saved.",
        args={"call_id": str(parsed.call_id)},
    )


async def _execute_second_reading(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    parsed = parse_args(_CallArgs, args)
    reading = await resummarise.second_reading(
        session, tenant_id=actor.tenant_id, call_id=parsed.call_id
    )
    lines = [
        f"Second summary: {reading.summary}"
        if reading.summary.strip()
        else "The call was read again and no summary came back. Nothing on the call changed."
    ]
    if reading.disclosure is not None:
        lines.append(reading.disclosure)  # G-6: a fallback is always disclosed.
    if not reading.metered:
        lines.append("This one did not use any of your AI allowance.")
    return Executed(
        applied=True,
        detail="\n\n".join(lines),
        # The summary is derived from a caller's words: shown once, never kept in the
        # activity log (D-127: nothing of a second reading is stored).
        recorded="Summarised a call again.",
        audit_summary={
            "provider": reading.provider,
            "fallback_reason": reading.fallback_reason,
            "metered": reading.metered,
            "ref": reading.ref,
        },
    )


CALL_SUMMARISE_AGAIN: Final = ActionTool(
    name="call_summarise_again",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="call",
    audit_action="call.ai_assist",
    where="in this conversation; it is not saved",
    # The model is paid inside the confirm: a failure after it keeps the card spent.
    external_spend=True,
    schema=action_schema(
        "call_summarise_again",
        "Write a fresh summary of one call from its transcript with identifiers hidden, "
        "shown to the person once. Use it when they ask to summarise a call again or for a "
        "second reading; to answer questions about a call, read it with `call_detail`."
        + PROPOSES_ONLY,
        {
            "call_id": {
                "type": "string",
                "description": "The call's id, from SCREEN STATE or `calls_recent`.",
            }
        },
    ),
    plan=_plan_second_reading,
    execute=_execute_second_reading,
)


# --- call_test_prepare --------------------------------------------------------------------


class _CallTestArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    expected: Annotated[str, Field(max_length=MAX_CASE_EXPECTED_CHARS + 1)] | None
    title: Annotated[str, Field(max_length=test_cases.MAX_TITLE_CHARS + 1)] | None


def _pending_of(parsed: _CallTestArgs) -> test_cases.PendingCase:
    return test_cases.PendingCase(
        expected=test_cases.clean_pending_text(
            strip_invisible(parsed.expected or ""), MAX_CASE_EXPECTED_CHARS
        ),
        title=test_cases.clean_pending_text(
            strip_invisible(parsed.title or ""), test_cases.MAX_TITLE_CHARS
        ),
    )


async def _plan_call_test(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY. Refuses, before anything is written, what the form would refuse on save:
    a call with no caller lines, or an agent that already keeps the most tests."""
    del actor
    parsed = parse_args(_CallTestArgs, args)
    await assert_visible(session, "call", parsed.call_id)
    draft = await test_cases.draft_from_call(session, parsed.call_id)
    if not draft.caller_lines:
        raise WriteRefusedError(
            "the caller said nothing in this call that a test could send, so it cannot "
            "become a test"
        )
    if await test_cases.saved_count(session, draft.agent_id) >= test_cases.MAX_CASES_PER_AGENT:
        raise WriteRefusedError(
            f"this call's agent already keeps {test_cases.MAX_CASES_PER_AGENT} saved tests, "
            "so one must be deleted on its Training tab first"
        )
    pending = _pending_of(parsed)
    return Plan(
        object_id=str(parsed.call_id),
        title="Make this call a test",
        summary=(
            f"{ASSISTANT_NAME} fills in the test form on this call's page with what the "
            "caller said, phone numbers and other identifiers hidden. You check it, change "
            "anything, and save it there."
        ),
        current=None,
        proposed=pending.expected or "What the agent should do: you write it on the form",
        cost=None,
        reversal="Nothing is saved until you save the form; discard it there.",
        args={
            "call_id": str(parsed.call_id),
            "expected": pending.expected,
            "title": pending.title,
        },
    )


async def _capture_call_test(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    parsed = parse_args(_CallTestArgs, args)
    pending = await test_cases.read_pending(session, call_id=parsed.call_id, user_id=actor.user_id)
    if pending is None:
        return {"exists": False}
    return {"exists": True, "expected": pending.expected, "title": pending.title}


async def _execute_call_test(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`test_cases.write_pending`: what the form opens with. Saving stays the form's own
    `POST /v1/calls/{call_id}/test-case`, so nothing reaches the agent's tests unseen."""
    parsed = parse_args(_CallTestArgs, args)
    await test_cases.write_pending(
        session,
        tenant_id=actor.tenant_id,
        call_id=parsed.call_id,
        user_id=actor.user_id,
        pending=_pending_of(parsed),
    )
    return Executed(
        applied=True,
        detail=(
            "The test form on this call's page is filled in. Check what the caller says "
            "and what the agent should do, then save it there."
        ),
        audit_summary={"call_id": str(parsed.call_id), "expected": parsed.expected is not None},
        object_id=str(parsed.call_id),
    )


async def _invert_call_test(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    """Put back what the form would have opened with, if nobody has saved or changed it."""
    call_id = UUID(str(record.args["call_id"]))
    live = await test_cases.read_pending(session, call_id=call_id, user_id=actor.user_id, lock=True)
    if live is None:
        raise UndoRefusedError("that test was already saved or discarded, so it was left alone")
    if (live.expected, live.title) != (
        record.result_state.get("expected"),
        record.result_state.get("title"),
    ):
        raise UndoRefusedError("that test was prepared again since, so it was left alone")
    if not record.prior_state.get("exists"):
        await test_cases.discard_pending(session, call_id=call_id, user_id=actor.user_id)
        return "The test form on that call is empty again."
    await test_cases.write_pending(
        session,
        tenant_id=actor.tenant_id,
        call_id=call_id,
        user_id=actor.user_id,
        pending=test_cases.PendingCase(
            expected=record.prior_state.get("expected"), title=record.prior_state.get("title")
        ),
    )
    return "The test form on that call is back to what it held before."


CALL_TEST_PREPARE: Final = ActionTool(
    name="call_test_prepare",
    # TIER 1. It saves no test: it fills in a form the person saves themselves. It reaches no
    # caller, calls no model, spends nothing, and Undo puts the form back exactly.
    tier="immediate",
    # `POST /v1/calls/{call_id}/test-case`'s own permission: the save the form makes.
    permission="agents:write",
    object_type="call",
    audit_action="agent_test_case.prepared",
    where="in the test form on the call's page",
    schema=action_schema(
        "call_test_prepare",
        "Make one call a test for its agent: fills in the test form on the call's page "
        "with the caller's lines, which the person checks and saves there." + DOES_IT,
        {
            "call_id": {
                "type": "string",
                "description": "The call's id, from SCREEN STATE or `calls_recent`.",
            },
            "expected": {
                **_NULLABLE_TEXT,
                "description": "What the agent should do instead, in their words, or null.",
            },
            "title": {**_NULLABLE_TEXT, "description": "A name for the test, or null."},
        },
    ),
    plan=_plan_call_test,
    execute=_execute_call_test,
    undo=Undo(capture=_capture_call_test, invert=_invert_call_test),
)


#: Registration order is wire order: new actions APPEND.
ASSIST_ACTIONS: Final[tuple[ActionTool, ...]] = (
    KNOWLEDGE_TEACH,
    LEAD_FIELDS_DRAFT,
    CALL_SUMMARISE_AGAIN,
    CALL_TEST_PREPARE,
)

__all__ = [
    "ASSIST_ACTIONS",
    "CALL_SUMMARISE_AGAIN",
    "CALL_TEST_PREPARE",
    "KNOWLEDGE_TEACH",
    "LEAD_FIELDS_DRAFT",
]
