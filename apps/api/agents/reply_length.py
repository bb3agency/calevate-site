"""The longest reply one agent may give, in tokens (D-769, operators only).

ThinnestAI cuts an agent's reply off where it reaches `maxReplyTokens`, an integer 100-800
whose default is 300, one ceiling for chat and calls (`thinnest-findings/mirror/snapshots/
2026-10-13/pages/api-reference/agents/update-agent.md:839-845`, create-agent.md:760-768).
Every publish states it: the agent's own `agents.max_reply_tokens` when an operator set one,
else the console's `thinnest_reply_length`. Stating it on every write, rather than only
when set, is what lets the settings sweep read it back and repair a console edit
(`reply_length`), the way `voice.turnDetection` is held.

Operators only, like the Studio voice tuning (`agents/voice_tuning`): a client neither sees
nor sets it, because the number is a model-token budget whose effect depends on the model
and the language, which a client cannot judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from calevate_shared.engine import REPLY_TOKENS_MAX, REPLY_TOKENS_MIN
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import queue_live_apply
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

TOKENS_MIN: Final = REPLY_TOKENS_MIN
TOKENS_MAX: Final = REPLY_TOKENS_MAX
#: The live-apply reason a change is queued under.
LIVE_APPLY_REASON: Final = "reply_length"

_READ_SQL: Final = (
    "SELECT max_reply_tokens, status, engine_agent_ref FROM agents "
    "WHERE id = :aid AND deleted_at IS NULL"
)
_UPDATE_SQL: Final = (
    "UPDATE agents SET max_reply_tokens = :tokens, updated_at = now() WHERE id = :aid"
)


@dataclass(frozen=True, slots=True)
class ReplyLengthState:
    agent_id: UUID
    #: The agent's own ceiling; None inherits the console's.
    own: int | None
    #: The console's ceiling, which an agent with none of its own is published with.
    default: int

    @property
    def effective(self) -> int:
        return self.own if self.own is not None else self.default


def resolve_max_reply_tokens(own: object) -> int:
    """The ceiling a publish sends: the agent's own, else the console's."""
    return own if isinstance(own, int) else get_settings().thinnest_reply_length


async def read_reply_length(session: AsyncSession, agent_id: UUID) -> ReplyLengthState:
    row = (await session.execute(text(_READ_SQL), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return ReplyLengthState(
        agent_id=agent_id, own=row[0], default=get_settings().thinnest_reply_length
    )


async def set_reply_length(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, tokens: int | None
) -> tuple[ReplyLengthState, bool]:
    """Write the agent's own ceiling (None inherits) and queue its live apply when it is
    live. The row is locked first, so the comparison and the write are one step and a repeat
    of the held value writes and queues nothing. The bounds are the route's and the column
    CHECK's. Answers the new state and whether it moved."""
    row = (await session.execute(text(_READ_SQL + " FOR UPDATE"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    moved = row[0] != tokens
    if moved:
        await session.execute(text(_UPDATE_SQL), {"tokens": tokens, "aid": agent_id})
        if str(row[1]) == "live" and row[2]:
            await queue_live_apply(
                session,
                scope="agent",
                tenant_id=tenant_id,
                agent_id=agent_id,
                reason=LIVE_APPLY_REASON,
            )
    log.info("agent_reply_length_set", extra={"agent_id": str(agent_id), "moved": moved})
    state = ReplyLengthState(
        agent_id=agent_id, own=tokens, default=get_settings().thinnest_reply_length
    )
    return state, moved


__all__ = [
    "LIVE_APPLY_REASON",
    "TOKENS_MAX",
    "TOKENS_MIN",
    "ReplyLengthState",
    "read_reply_length",
    "resolve_max_reply_tokens",
    "set_reply_length",
]
