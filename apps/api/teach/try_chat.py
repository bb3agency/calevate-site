"""'Try it': a text chat with the LIVE agent, through the engine's sandboxed test chat.

The same harness the pre-launch test conversations use (`engine/test_chat.RunsTestChat`;
on ThinnestAI `POST /agents/{id}/test-chat`, mirror snapshots/2026-10-08/pages/api-reference/
agents/test-chat.md:328-460): the real prompt, model, knowledge and actions, with anything
that would contact a person switched off. Founder decision 3: test what is live only, so
there is no draft copy of the agent to chat with.

COST. The engine bills a test chat "like the console's Playground" (test-chat.md:7) and
publishes no per-reply rate for an agent on its own models (the ₹0.02 a reply in the same
file is the all-keys-BYOK rate, which this account does not run). UNKNOWN, so nothing is
written to the ledger (hard rule 7 forbids a guessed price). Founder decision 5 puts the chat
inside the client's AI allowance, so a chat is refused once that allowance is used up, and
the cost sentence says the replies are not charged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.test_conversations import readiness
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.core.errors import ProblemError
from apps.api.engine import get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.test_chat import RunsTestChat

MAX_MESSAGE_CHARS: Final = 1000

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
) -> ChatReply:
    cleaned = message.strip()
    if not cleaned:
        raise ProblemError.business_rule("try_chat_empty", "Type what a caller would say.")
    if len(cleaned) > MAX_MESSAGE_CHARS:
        raise ProblemError.business_rule(
            "try_chat_too_long", f"Keep a message under {MAX_MESSAGE_CHARS} characters."
        )
    ready = await readiness(session, agent_id)
    if not ready.available:
        raise ProblemError.business_rule("try_chat_unavailable", ready.reason or "")
    await require_ai_assist(session, tenant_id=tenant_id)
    ref = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agents WHERE id = :id"), {"id": agent_id}
        )
    ).scalar()
    engine = get_engine()
    if not isinstance(engine, RunsTestChat) or ref is None:
        raise ProblemError.business_rule("try_chat_unavailable", "This agent cannot chat yet.")
    turn = await engine.test_chat(str(ref), cleaned, session=chat_session or None)
    knowledge_tool = hosted_agent_limits(get_engine()).knowledge_tool
    return ChatReply(
        session=turn.session,
        reply=turn.reply,
        looked_up_knowledge=knowledge_tool is not None and knowledge_tool in turn.tools,
        cut_short=turn.failed_part_way,
    )


__all__ = ["COST_NOTE", "MAX_MESSAGE_CHARS", "ChatReply", "send"]
