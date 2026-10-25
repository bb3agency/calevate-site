"""A re-published outbox message whose earlier run succeeded is not run again.

`dispatch_outbox` enqueues a message and then marks it published; if that mark never
commits, the message is enqueued again under the same job id once its claim lapses. arq
refuses the repeat only while the first run's result key lasts — five minutes for the
jobs that carry personal data and NOTHING for `deliver_auth_email` — so a database outage
longer than that window sent the same email (or webhook, or notice) twice. The repeat is
driven here through a real arq worker with the result key gone, which is exactly the state
the window leaves behind.

SHARED DATABASE DISCIPLINE: the one outbox row is minted here and deleted here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from apps.api.core.queue import get_queue, job_id_for
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import enqueue_outbox, outbox_message_id
from apps.workers import auth_email, outbox_consumer
from apps.workers.outbox_consumer import ALREADY_CONSUMED, consume_outbox_once
from apps.workers.settings import WorkerSettings
from arq.connections import ArqRedis
from arq.constants import result_key_prefix
from arq.worker import Worker
from sqlalchemy import text

JOB = "deliver_auth_email"


class _Sent:
    def __init__(self) -> None:
        self.count = 0

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.count += 1
        return True


@pytest_asyncio.fixture
async def message_id() -> AsyncIterator[uuid.UUID]:
    payload: dict[str, Any] = {
        "kind": "password_reset",
        "realm": "client",
        "to": "owner@calevate-test.example",
        "secret": f"tok_{uuid.uuid4().hex}",
    }
    async with untenanted_session() as session:
        minted = await enqueue_outbox(session, job=JOB, payload=payload)
    yield minted
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM outbox_messages WHERE id = :id"), {"id": minted})


async def _run_worker(queue_name: str) -> None:
    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        queue_name=queue_name,
        keep_result=WorkerSettings.keep_result,
        burst=True,
        poll_delay=0.01,
        handle_signals=False,
        ctx={},
    )
    try:
        await worker.main()
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_a_republished_message_is_not_delivered_twice(
    monkeypatch: pytest.MonkeyPatch, message_id: uuid.UUID
) -> None:
    sent = _Sent()
    monkeypatch.setattr(auth_email, "get_transport", lambda: sent)
    queue_name = f"arq:test-outbox-once-{uuid.uuid4().hex[:8]}"
    job_id = job_id_for(JOB, str(message_id))  # what `dispatch_outbox` enqueues it as
    async with untenanted_session() as session:
        payload = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE id = :id"), {"id": message_id}
            )
        ).scalar_one()
    redis: ArqRedis = await get_queue()

    # The first publish: the job runs; the dispatcher's `published` mark is then lost, so
    # the row is still `pending` and the next tick will publish it again.
    await redis.enqueue_job(JOB, payload, _job_id=job_id, _queue_name=queue_name)
    await _run_worker(queue_name)
    assert sent.count == 1

    # The re-publish, after arq's result key is gone.
    await redis.delete(result_key_prefix + job_id)
    assert await redis.enqueue_job(JOB, payload, _job_id=job_id, _queue_name=queue_name)
    await _run_worker(queue_name)

    assert sent.count == 1, (
        "the same outbox message was delivered twice once arq's job-id dedupe had expired"
    )
    async with untenanted_session() as session:
        consumed = (
            await session.execute(
                text("SELECT consumed_at IS NOT NULL FROM outbox_messages WHERE id = :id"),
                {"id": message_id},
            )
        ).scalar_one()
    assert consumed


@pytest.mark.asyncio
async def test_a_failed_run_is_not_recorded_so_the_message_can_run_again(
    message_id: uuid.UUID,
) -> None:
    """Only success is recorded: a run that raised (arq's own retry, or a later re-publish)
    must still be allowed to deliver."""
    runs: list[str] = []

    async def deliver_auth_email(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        runs.append("run")
        if len(runs) == 1:
            raise RuntimeError("receiver away")
        return "sent"

    deliver_auth_email.__qualname__ = JOB  # arq registers by qualname; this one is nested
    guarded = consume_outbox_once(deliver_auth_email)
    ctx = {"job_id": job_id_for(JOB, str(message_id))}
    with pytest.raises(RuntimeError):
        await guarded(ctx, {})
    assert await guarded(ctx, {}) == "sent"
    assert await guarded(ctx, {}) == ALREADY_CONSUMED
    assert runs == ["run", "run"]


@pytest.mark.asyncio
async def test_a_job_the_outbox_did_not_publish_runs_untouched() -> None:
    """A job keyed by some other uuid (a call id) has the same id shape; it matches no
    outbox row and runs every time."""
    runs: list[str] = []

    async def deliver_auth_email(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        runs.append("run")
        return "sent"

    deliver_auth_email.__qualname__ = JOB  # arq registers by qualname; this one is nested
    guarded = consume_outbox_once(deliver_auth_email)
    ctx = {"job_id": job_id_for(JOB, str(uuid.uuid4()))}
    await guarded(ctx, {})
    await guarded(ctx, {})
    await guarded({"job_id": "deliver_auth_email:not-a-uuid"}, {})
    await guarded({}, {})
    assert runs == ["run"] * 4
    assert outbox_message_id(JOB, "another_job:" + str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_an_unreachable_database_never_stops_the_message_running(
    monkeypatch: pytest.MonkeyPatch, message_id: uuid.UUID
) -> None:
    """Fail-open: the outbox promises at-least-once, so a database that cannot be asked
    whether the message already ran must not turn into a lost delivery."""

    def unreachable() -> object:
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(outbox_consumer, "untenanted_session", unreachable)
    runs: list[str] = []

    async def deliver_auth_email(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        runs.append("run")
        return "sent"

    deliver_auth_email.__qualname__ = JOB  # arq registers by qualname; this one is nested
    guarded = consume_outbox_once(deliver_auth_email)
    assert await guarded({"job_id": job_id_for(JOB, str(message_id))}, {}) == "sent"
    assert runs == ["run"]
