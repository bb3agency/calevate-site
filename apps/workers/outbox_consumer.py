"""Run each outbox message's job at most once per success, durably.

`reliability.service` carries the argument (the "Outbox consumption" block): the
dispatcher's `published` mark can be lost after the job is already on the queue, and arq's
job-id dedupe outlives a finished run only by its `keep_result` window. This wrapper is
the consumer half: a run of an outbox message first asks the database whether a run of
that message already succeeded, and records its own success.

FAIL-OPEN, deliberately. If the database cannot be asked, the job runs: the outbox's
promise is at-least-once, and refusing to run would turn a database blip into a lost
notification (`deliver_auth_email` holds no session on purpose and must keep working).
The cost is the residue every idempotent consumer has: a run that succeeds while its
success cannot be recorded can be repeated by a later re-publish. Both failures are
logged with the message id so the residue is visible.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import (
    mark_outbox_consumed,
    outbox_message_consumed,
    outbox_message_id,
)

log = get_logger(__name__)

#: What a skipped run returns, so the arq result says why nothing happened.
ALREADY_CONSUMED = "outbox_message_already_consumed"

Job = Callable[..., Awaitable[Any]]


def consume_outbox_once(job: Job) -> Job:
    """Wrap an arq job so a re-published outbox message whose earlier run succeeded is
    skipped. A job enqueued any other way runs untouched."""
    # arq registers by `__qualname__` and the outbox enqueues by that name.
    name = getattr(job, "__qualname__", getattr(job, "__name__", ""))

    @functools.wraps(job)
    async def run(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        message_id = outbox_message_id(name, ctx.get("job_id"))
        if message_id is None:
            return await job(ctx, *args, **kwargs)
        extra = {"job": name, "message_id": str(message_id)}
        try:
            async with untenanted_session() as session:
                consumed = await outbox_message_consumed(session, message_id=message_id, job=name)
        except Exception as exc:
            log.warning(
                "outbox_consumed_check_failed", extra={**extra, "error": type(exc).__name__}
            )
            consumed = False
        if consumed:
            log.info("outbox_message_already_consumed", extra=extra)
            return ALREADY_CONSUMED
        result = await job(ctx, *args, **kwargs)
        try:
            async with untenanted_session() as session:
                await mark_outbox_consumed(session, message_id=message_id, job=name)
        except Exception as exc:
            # Never raised: the side effect has happened, and a raise here would make arq
            # retry it.
            log.warning("outbox_consumed_unrecorded", extra={**extra, "error": type(exc).__name__})
        return result

    return run


__all__ = ["ALREADY_CONSUMED", "consume_outbox_once"]
