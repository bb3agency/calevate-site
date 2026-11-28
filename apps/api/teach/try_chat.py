"""'Try it': a text chat with the LIVE agent, through the engine's sandboxed test chat.

The same harness the pre-launch test conversations use (`engine/test_chat.RunsTestChat`;
on ThinnestAI `POST /agents/{id}/test-chat`, mirror snapshots/2026-10-08/pages/api-reference/
agents/test-chat.md:328-460): the real prompt, model, knowledge and actions, with anything
that would contact a person switched off. Founder decision 3: test what is live only, so
there is no draft copy of the agent to chat with. The agent page's "Just the business" chats
with the agent's business-only test copy instead (`agents/business_only`, founder 16 Nov 2026),
and so does the plain chat of an agent that holds no engine agent of its own (D-1019).

COST. A test-chat reply costs what a website chat reply costs: on an agent answering on our
own language-model key (`byok: llm` or `llm_voice`) the flat ₹0.02 own-key reply price, plus
the reply's tokens on our Google key (snapshots/2026-10-19/pages/api-reference/agents/
test-chat.md:7). The price of a reply on the engine's own models is not published. Neither
reaches the ledger: there is no attested per-reply price to put on it (hard rule 7), so test
chats are platform overhead today (D-835). Founder decision 5 puts the chat inside the
client's AI allowance, so a chat is refused once that allowance is used up, and the cost
sentence says the replies are not charged.

REHEARSE (W3.2). A campaign's or an inbound line's Script tab chats with that holder's own
engine agent (D-997, D-1003), never the agent's: a holder on calls (a running or paused
campaign, a live line) as it is, since saving its script puts it on calls; any other is
published first as its test holder (`campaign_test_dial`, `line_test_dial`), the separate
engine agent a test call of it rings, which carries the saved script and the client's
knowledge (`engine_facts.sync_business_facts`, D-964, D-997, D-1003). The vendor's test chat
"always runs the agent as saved: there is no separate draft" and says to test a change on a
second agent (VERIFIED-VENDOR-DOCS, thinnest-findings/mirror/snapshots/2026-11-26/pages/
api-reference/agents/test-chat.md:7), which is what the test holder is. An unsaved Pip draft
is never rehearsed: there is no hidden draft twin (founder, 10 Oct 2026). Every tool the agent
used comes back in the owner's words, marked as not run (the sandbox switches off whatever
would reach a person and our actions answer `*_in_test`, `worker/engine_actions`), and each
reply carries the reply checks the after-call review runs (`turn_checks.turn_problems`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.paid_test_calls import copy_call_live, refresh_test_copy
from apps.api.agents.test_conversations import readiness
from apps.api.agents.test_window import send_test_message
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.core.errors import ProblemError
from apps.api.engine import get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.test_chat import RunsTestChat, TestChatTool
from apps.api.reliability.engine_actions import (
    ACTION_NAMES,
    CALLBACK,
    CALLBACK_CANCEL,
    HANDOFF,
    OPT_OUT,
)

MAX_MESSAGE_CHARS: Final = 1000

CANNOT_CHAT: Final = "This agent cannot chat yet."

COST_NOTE: Final = (
    "Replies here are not charged. Chatting is paused when this month's AI help is used up."
)


@dataclass(frozen=True, slots=True)
class ChatReply:
    session: str
    reply: str
    #: The agent looked something up in the business's knowledge for this reply.
    looked_up_knowledge: bool
    #: The reply stopped part-way.
    cut_short: bool


async def send(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    message: str,
    chat_session: str | None,
    business: bool = False,
) -> ChatReply:
    """One line of the chat. `business` chats with "Just the business" (the agent's
    business-only test copy, `agents/business_only`) instead of the agent as callers hear it;
    that copy needs no "Get it ready", because nothing is dialled."""
    cleaned = message.strip()
    if not cleaned:
        raise ProblemError.business_rule("try_chat_empty", "Type what a caller would say.")
    if len(cleaned) > MAX_MESSAGE_CHARS:
        raise ProblemError.business_rule(
            "try_chat_too_long", f"Keep a message under {MAX_MESSAGE_CHARS} characters."
        )
    engine = get_engine()
    if business:
        if not isinstance(engine, RunsTestChat):
            raise ProblemError.business_rule("try_chat_unavailable", CANNOT_CHAT)
        await require_ai_assist(session, tenant_id=tenant_id)
        ref, chat_session = await _business_copy(
            session, tenant_id=tenant_id, agent_id=agent_id, chat_session=chat_session
        )
    else:
        ready = await readiness(session, agent_id)
        if not ready.available:
            raise ProblemError.business_rule("try_chat_unavailable", ready.reason or CANNOT_CHAT)
        await require_ai_assist(session, tenant_id=tenant_id)
        if not isinstance(engine, RunsTestChat):
            raise ProblemError.business_rule("try_chat_unavailable", CANNOT_CHAT)
        own = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar()
        if own is None:
            # An agent holding no engine agent of its own (D-1019) is heard alone only as
            # "Just the business"; its lines and campaigns are tried from their own pages.
            ref, chat_session = await _business_copy(
                session, tenant_id=tenant_id, agent_id=agent_id, chat_session=chat_session
            )
        else:
            ref = str(own)
    turn = await send_test_message(
        engine,
        agent_id=agent_id,
        engine_agent_ref=str(ref),
        message=cleaned,
        session=chat_session or None,
    )
    knowledge_tool = hosted_agent_limits(get_engine()).knowledge_tool
    return ChatReply(
        session=turn.session,
        reply=turn.reply,
        looked_up_knowledge=knowledge_tool is not None and knowledge_tool in turn.tools,
        cut_short=turn.failed_part_way,
    )


async def _business_copy(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, chat_session: str | None
) -> tuple[str, str | None]:
    """The business-only copy to chat with, and the chat session to continue on it.

    A new chat republishes the copy first, so it holds the agent and the training as they
    are now. A chat already running keeps the copy as it is, unless it no longer holds
    "Just the business" (a campaign's test call puts the agent, with that campaign's script,
    on the same copy): then it is republished and the chat starts again on it. While a test
    call may be on the copy it is never republished (`copy_call_live`): a copy already holding
    "Just the business" is chatted with as it is, and any other waits for that call."""
    row = (
        await session.execute(
            text(
                "SELECT engine_agent_ref, business_only FROM agent_test_copies "
                "WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is not None and row.business_only:
        if chat_session:
            return str(row.engine_agent_ref), chat_session
        if await copy_call_live(session, agent_id):
            return str(row.engine_agent_ref), None
    ref = await refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id, business=True)
    return ref, None


HolderKind = Literal["campaign", "line"]

REHEARSE_COST_NOTE: Final = (
    "Nothing here calls anyone. Replies are not charged, and chatting is paused when this "
    "month's AI help is used up."
)

#: Our actions and the engine's hand-over tool (`ThinnestEngine.built_in_tools_body`), as
#: the owner reads what the agent would have done.
_ACTION_WORDS: Final[dict[str, str]] = {
    ACTION_NAMES[OPT_OUT]: "Would stop calling this person",
    ACTION_NAMES[CALLBACK_CANCEL]: "Would cancel their call-back",
    ACTION_NAMES[HANDOFF]: "Would pass the call to your team",
    "escalate_to_human": "Would pass the call to your team",
}
#: A tool that ends the conversation. ASSUMPTION: the engine's name for a hang-up tool is not
#: in the mirrored docs (thinnest-findings/mirror, snapshots to 26 Nov 2026), so it is
#: recognised by the words such a name would hold.
_ENDS_CALL: Final = re.compile(r"hang|end_?call|end_?conversation", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RehearsedAction:
    """One tool the agent used, in the owner's words. `ran` is False for every tool that
    acts on a call: the sandbox runs none of them."""

    said: str
    ran: bool = False


@dataclass(frozen=True, slots=True)
class ReplyFlag:
    """A reply check's finding (`turn_checks.turn_problems`), and whether a line of the
    script can cause it, so "Fix this in the script" is offered only where it can help."""

    kind: str
    reason: str
    in_script: bool


@dataclass(frozen=True, slots=True)
class Rehearsed:
    session: str
    reply: str
    cut_short: bool
    actions: tuple[RehearsedAction, ...]
    flags: tuple[ReplyFlag, ...]
    #: "saved": the holder's test holder, republished with the saved script; "live": the
    #: holder's engine agent on calls, which holds what callers hear.
    runs: Literal["saved", "live"]


def _spoken_time(raw: str) -> str | None:
    """ "16:00" as "4 PM", "09:30" as "9:30 AM"; None for anything else."""
    try:
        at = time.fromisoformat(raw.strip())
    except ValueError:
        return None
    clock = f"{at.hour % 12 or 12}" + (f":{at.minute:02d}" if at.minute else "")
    return f"{clock} {'AM' if at.hour < 12 else 'PM'}"


def _spoken_day(raw: str) -> str | None:
    try:
        day = date.fromisoformat(raw.strip())
    except ValueError:
        return None
    return f"{day.day} {day.strftime('%b')}"


def action_words(tool: TestChatTool, *, knowledge_tool: str | None) -> RehearsedAction:
    """What the agent did with one tool, as the owner reads it."""
    if knowledge_tool is not None and tool.name == knowledge_tool:
        # A lookup reaches nobody, so the sandbox really runs it.
        return RehearsedAction("Looked up what you taught it", ran=True)
    if tool.name == ACTION_NAMES[CALLBACK]:
        given = dict(tool.arguments)
        when = " on ".join(
            part
            for part in (
                _spoken_time(given.get("callback_time", "")),
                _spoken_day(given.get("callback_date", "")),
            )
            if part
        )
        return RehearsedAction(
            f"Would book a call-back for {when}" if when else "Would book a call-back"
        )
    if tool.name in _ACTION_WORDS:
        return RehearsedAction(_ACTION_WORDS[tool.name])
    if _ENDS_CALL.search(tool.name):
        return RehearsedAction("Would end the call")
    return RehearsedAction(f"Would use its {tool.name.replace('_', ' ')} tool")


_HOLDER_SQL: Final[dict[HolderKind, str]] = {
    "campaign": (
        "SELECT agent_id, engine_agent_ref, status IN ('running', 'paused'), "
        "script IS NOT NULL FROM campaigns WHERE id = :h AND archived_at IS NULL"
    ),
    "line": (
        "SELECT agent_id, engine_agent_ref, published_at IS NOT NULL, script IS NOT NULL "
        "FROM inbound_lines WHERE id = :h AND archived_at IS NULL"
    ),
}

#: A call on this engine agent that may not have ended, bounded as `copy_call_live` is.
_REF_CALL_LIVE_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM calls WHERE engine_agent_ref = :ref "
    "AND status IN ('queued', 'ringing', 'in_progress') "
    "AND created_at > now() - make_interval(secs => :horizon))"
)


async def _ref_call_live(session: AsyncSession, ref: str) -> bool:
    from apps.api.compliance.trial_access import live_test_call_horizon

    return bool(
        (
            await session.execute(
                text(_REF_CALL_LIVE_SQL),
                {"ref": ref, "horizon": live_test_call_horizon().total_seconds()},
            )
        ).scalar()
    )


async def _holder_row(session: AsyncSession, kind: HolderKind, holder_id: UUID) -> Any:
    """The holder, read first so another account's id is a 404 before anything is spent."""
    row = (await session.execute(text(_HOLDER_SQL[kind]), {"h": holder_id})).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if kind == "campaign" else "Inbound line")
    if not row[3]:
        raise ProblemError.business_rule(
            "rehearse_no_script",
            "There is no saved script to try yet.",
            remediation="Save a script first, then try it here.",
        )
    return row


async def _rehearsal_ref(
    session: AsyncSession,
    row: Any,
    *,
    tenant_id: UUID,
    kind: HolderKind,
    holder_id: UUID,
    chat_session: str | None,
) -> tuple[UUID, str, Literal["saved", "live"], str | None]:
    """The holder's agent, the engine agent to rehearse on, what it holds, and the chat
    session to go on with.

    A holder on calls is rehearsed on its own engine agent as it is. A chat already running
    stays on the engine agent it began on. A new one publishes the test holder first, so it
    holds the script saved now, unless a call may be on it: what republishing does to a call
    in progress is not documented (OPERATIONS T-28), so the rehearsal then runs on it as it
    is."""
    agent_id = UUID(str(row[0]))
    ref = str(row[1]) if row[1] else None
    if ref is not None and row[2]:
        return agent_id, ref, "live", chat_session
    if ref is not None and (chat_session or await _ref_call_live(session, ref)):
        return agent_id, ref, "saved", chat_session
    # Kept in the workspace it is in: a chat places no call, so it has no line to need.
    in_client = ref is not None and scope_of(ref) is not None
    if kind == "campaign":
        from apps.api.campaigns.engine_agent import campaign_test_dial

        made = await campaign_test_dial(
            tenant_id=tenant_id, campaign_id=holder_id, in_client=in_client
        )
        return agent_id, made.ref, "saved", None
    from apps.api.inbound.publish import line_test_dial

    held = await line_test_dial(tenant_id=tenant_id, line_id=holder_id, in_client=in_client)
    return agent_id, held.ref, "saved", None


async def rehearse(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: HolderKind,
    holder_id: UUID,
    message: str,
    chat_session: str | None,
) -> Rehearsed:
    """One line of a rehearsal of the holder's saved script (see the module)."""
    cleaned = message.strip()
    if not cleaned:
        raise ProblemError.business_rule("try_chat_empty", "Type what a caller would say.")
    if len(cleaned) > MAX_MESSAGE_CHARS:
        raise ProblemError.business_rule(
            "try_chat_too_long", f"Keep a message under {MAX_MESSAGE_CHARS} characters."
        )
    row = await _holder_row(session, kind, holder_id)
    engine = get_engine()
    if not isinstance(engine, RunsTestChat):
        raise ProblemError.business_rule("try_chat_unavailable", CANNOT_CHAT)
    await require_ai_assist(session, tenant_id=tenant_id)
    agent_id, ref, runs, chat_session = await _rehearsal_ref(
        session,
        row,
        tenant_id=tenant_id,
        kind=kind,
        holder_id=holder_id,
        chat_session=chat_session,
    )
    turn = await send_test_message(
        engine, agent_id=agent_id, engine_agent_ref=ref, message=cleaned, session=chat_session
    )
    knowledge_tool = hosted_agent_limits(engine).knowledge_tool
    tools = turn.tool_results or tuple(TestChatTool(name=name) for name in turn.tools)
    return Rehearsed(
        session=turn.session,
        reply=turn.reply,
        cut_short=turn.failed_part_way,
        actions=tuple(action_words(tool, knowledge_tool=knowledge_tool) for tool in tools),
        flags=await _reply_flags(session, kind, holder_id, agent_id, cleaned, turn.reply),
        runs=runs,
    )


async def _reply_flags(
    session: AsyncSession,
    kind: HolderKind,
    holder_id: UUID,
    agent_id: UUID,
    said: str,
    reply: str,
) -> tuple[ReplyFlag, ...]:
    """The reply checks on one rehearsed reply, in the holder's own call language."""
    # Imported here: `script_heal` reaches `campaigns.workspace`, which reaches the writer.
    from apps.api.agents.script_checks import SCRIPT_FIXABLE_KINDS
    from apps.api.agents.script_heal import holder_lint_context
    from apps.api.agents.turn_checks import SCRIPT_KINDS, turn_problems

    lint = await holder_lint_context(session, kind, holder_id, agent_id)
    names = [n for n in (lint.business_name, lint.agent_name) if n]
    found = turn_problems(reply, caller_said=said, language=lint.language, names=names)
    # Each kind once, at its first finding: one flag says what to change in the script.
    first = {problem.kind: problem for problem in reversed(found)}
    return tuple(
        ReplyFlag(
            problem.kind,
            problem.reason,
            in_script=problem.kind in SCRIPT_FIXABLE_KINDS or problem.kind in SCRIPT_KINDS,
        )
        for problem in found
        if first[problem.kind] is problem
    )


__all__ = [
    "COST_NOTE",
    "MAX_MESSAGE_CHARS",
    "REHEARSE_COST_NOTE",
    "ChatReply",
    "HolderKind",
    "Rehearsed",
    "RehearsedAction",
    "ReplyFlag",
    "action_words",
    "rehearse",
    "send",
]
