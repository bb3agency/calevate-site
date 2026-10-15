"""Keeping one person's Pip conversation in step on every device they have open (D-782).

The conversation is stored per PERSON (D-540), so a phone and a desktop already read the
same rows; what this module adds is that each of them hears, within a second, that the rows
moved — and whether Pip is still answering a question asked on another device.

WHAT A DEVICE IS TOLD, and what it is not. A note on the person's own live channel
(`live.topics.person_channel`) says "your conversation changed" and nothing else: no turn
id, no text (hard rule 6). The device then refetches `GET .../copilot/conversation` through
the ordinary authorised route, which also answers `answering`. The note never reaches the
account's channel, so a colleague signed in to the same account hears nothing.

WHY "ANSWERING" IS A REDIS SET AND NOT A COLUMN. It is a fact about a request in flight,
not about the conversation: it must disappear on its own if the process answering dies
mid-run, and it must not cost a write to a durable table twice per question. A sorted set
per person, one member per run scored by its start, answers "is any run of mine still
going?" for two devices asking at once (one finishing does not clear the other), and every
member older than `ANSWERING_TTL_S` is ignored, so a run whose `finally` never ran stops
counting once the loop's own wall clock has certainly expired.

Every function here NEVER RAISES: it runs beside an answer that has been delivered or a
question that is being answered, and a missed note costs a device one refetch on its next
reconnect or focus — never an answer.
"""

from __future__ import annotations

import time
from typing import Final, Literal
from uuid import UUID

from apps.api.copilot.service import TOTAL_BUDGET_S
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.live.publish import publish_conversation_note

log = get_logger(__name__)

ConversationRealm = Literal["client", "admin"]

#: How long a run counts as "answering" without being settled: the loop's whole wall clock
#: (`service.TOTAL_BUDGET_S`) plus the meter and the transcript write after it.
ANSWERING_TTL_S: Final = int(TOTAL_BUDGET_S) + 30


def answering_key(realm: ConversationRealm, owner_id: UUID) -> str:
    return f"calevate:copilot:answering:{realm}:{owner_id}"


async def answer_started(realm: ConversationRealm, owner_id: UUID, run: UUID) -> None:
    """The question is stored and Pip has started answering it. Called after the question's
    transaction committed, so a device that refetches on this note finds the question."""
    key = answering_key(realm, owner_id)
    try:
        async with get_redis().pipeline(transaction=True) as pipe:
            pipe.zadd(key, {str(run): time.time()})
            pipe.expire(key, ANSWERING_TTL_S)
            await pipe.execute()
    except Exception as exc:
        log.warning("copilot_answering_mark_failed", extra={"error": type(exc).__name__})
    await publish_conversation_note(realm, owner_id)


async def answer_settled(realm: ConversationRealm, owner_id: UUID, run: UUID) -> None:
    """The run is over, whichever way it ended, and its answer (if any) is stored."""
    try:
        await get_redis().zrem(answering_key(realm, owner_id), str(run))
    except Exception as exc:
        log.warning("copilot_answering_clear_failed", extra={"error": type(exc).__name__})
    await publish_conversation_note(realm, owner_id)


async def conversation_changed(realm: ConversationRealm, owner_id: UUID) -> None:
    """Something else moved the conversation — "Start again" on one device."""
    await publish_conversation_note(realm, owner_id)


async def is_answering(realm: ConversationRealm, owner_id: UUID) -> bool:
    """Whether a run of this person's is still answering, on any device."""
    try:
        live = await get_redis().zcount(
            answering_key(realm, owner_id), time.time() - ANSWERING_TTL_S, "+inf"
        )
    except Exception as exc:
        log.warning("copilot_answering_read_failed", extra={"error": type(exc).__name__})
        return False
    return int(live) > 0


__all__ = [
    "ANSWERING_TTL_S",
    "ConversationRealm",
    "answer_settled",
    "answer_started",
    "answering_key",
    "conversation_changed",
    "is_answering",
]
