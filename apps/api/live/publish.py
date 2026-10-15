"""Publishing change notes to Redis pub/sub, after commit (D-774).

Pub/sub is a HINT, not a message queue: a browser that misses a note refetches
everything on reconnect, and the slow safety poll catches what a reconnect cannot. So a
publish that fails is logged and swallowed — it runs after the write has committed and
must never be able to fail it — and there is no retry, no outbox row and no broker.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from apps.api.core.alerting import record_live_publish_failure
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.live.schemas import LiveChange
from apps.api.live.topics import (
    OPERATOR_CHANNEL,
    TENANT_TOPICS,
    Topic,
    person_channel,
    tenant_channel,
)

log = get_logger(__name__)


def _notes(tenant_id: UUID | None, topics: Iterable[Topic], at: datetime) -> list[tuple[str, str]]:
    """(channel, body) pairs. A client's channel gets its tenant topics without the tenant
    id; the operator channel gets every topic with it."""
    out: list[tuple[str, str]] = []
    for topic in sorted(topics):
        if tenant_id is not None and topic in TENANT_TOPICS:
            out.append(
                (tenant_channel(tenant_id), LiveChange(topic=topic, at=at).model_dump_json())
            )
        out.append(
            (
                OPERATOR_CHANNEL,
                LiveChange(topic=topic, at=at, tenant_id=tenant_id).model_dump_json(),
            )
        )
    return out


async def publish_changes(tenant_id: UUID | None, topics: Iterable[Topic]) -> None:
    """Publish one commit's notes in one round trip. Never raises."""
    notes = _notes(tenant_id, topics, datetime.now(UTC))
    if not notes:
        return
    try:
        async with get_redis().pipeline(transaction=False) as pipe:
            for channel, body in notes:
                pipe.publish(channel, body)
            await pipe.execute()
    except Exception as exc:
        record_live_publish_failure(reason=type(exc).__name__)
        log.warning(
            "live_publish_failed",
            extra={"error": type(exc).__name__, "notes": len(notes)},
        )


async def publish_conversation_note(realm: str, person_id: UUID) -> None:
    """Tell ONE person's open windows that their Pip conversation moved (D-782), on their
    own channel and never on their account's. The note is the same shape as every other — a
    topic and an instant — with no tenant id, no turn id and no text. Never raises."""
    body = LiveChange(topic="conversation", at=datetime.now(UTC)).model_dump_json()
    try:
        await get_redis().publish(person_channel(realm, person_id), body)
    except Exception as exc:
        record_live_publish_failure(reason=type(exc).__name__)
        log.warning("live_publish_failed", extra={"error": type(exc).__name__, "notes": 1})


__all__ = ["publish_changes", "publish_conversation_note"]
